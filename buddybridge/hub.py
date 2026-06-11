#!/usr/bin/env python3
"""
buddyhub — the brain of the Claude Desktop Buddy multi-machine bridge.

Aggregates Claude Code session state from one or more machines (each running
the `buddy-hook` agent) and drives a transport that talks to the M5Stick over
the Hardware Buddy BLE protocol (REFERENCE.md schema).

Phase 1 ships a MockTransport: heartbeats print to the console and you type
`a` / `d` to simulate the stick's A (approve) / B (deny) buttons, exercising
the full remote-permission control loop with zero hardware.

stdlib only — runs anywhere python3 does.

  buddyhub --port 8787            # console entry point (installed via pip/pipx)

HTTP API (hooks POST here):
  POST /event       {machine, session, kind, msg?, tokens?}
                    kind: session_start | session_end | running | idle | tool_done
  POST /permission  {machine, session, tool, hint}      -> {"id": "<prompt id>"}
  GET  /decision?id=<id>   long-poll -> {"decision": "once"|"deny"|"timeout"}
  GET  /state       debug snapshot
"""
import argparse
import json
import socket
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

KEEPALIVE_ACTIVE_SEC = 10   # heartbeat cadence when sessions are active
KEEPALIVE_IDLE_SEC = 20     # heartbeat cadence when nothing is happening
KEEPALIVE_FLOOR_SEC = 20    # always retransmit after this long, even if unchanged
                            # (must be < firmware's 30s disconnect window)
DECISION_TIMEOUT_SEC = 30   # how long a PreToolUse hook waits before fallback
STALE_SESSION_SEC = 300     # reap an idle session only after this long (5 min)
STALE_RUNNING_SEC = 1800    # running sessions get a longer leash (30 min)
PROMPT_TTL = 90             # drop an unanswered/orphaned prompt after this long


# --------------------------------------------------------------------------- #
# State                                                                        #
# --------------------------------------------------------------------------- #
class Pending:
    """A permission prompt awaiting a decision from the device."""
    def __init__(self, machine, session, tool, hint):
        self.id = "req_" + uuid.uuid4().hex[:10]
        self.machine = machine
        self.session = session
        self.tool = tool
        self.hint = hint
        self.created = time.monotonic()
        self.decision = None                 # "once" | "deny" | "timeout"
        self.event = threading.Event()       # set when decided


class Hub:
    def __init__(self, transport):
        self.lock = threading.RLock()
        self.transport = transport
        transport.hub = self
        # sessions: key (machine, session) -> dict(status, msg, ts, tokens)
        self.sessions = {}
        self.entries = deque(maxlen=8)        # recent activity lines, newest first
        self.pending = deque()                # FIFO of Pending awaiting display
        self.by_id = {}                       # id -> Pending
        self.current = None                   # Pending currently shown on device
        self._dirty = threading.Event()

    # ---- session events -------------------------------------------------- #
    def event(self, machine, session, kind, msg=None, tokens=None):
        key = (machine, session)
        with self.lock:
            if kind == "session_start":
                self.sessions.setdefault(key, {"status": "idle", "msg": "", "ts": 0, "tokens": 0})
            elif kind == "session_end":
                self.sessions.pop(key, None)
                # Purge entries from this session's machine so the device
                # doesn't keep showing stale transcript lines from dead sessions.
                self.entries = deque(
                    (e for e in self.entries if not e.startswith(f"{machine} ▸")),
                    maxlen=8)
            else:
                s = self.sessions.setdefault(key, {"status": "idle", "msg": "", "ts": 0, "tokens": 0})
                if kind == "running":
                    s["status"] = "running"
                elif kind == "tool_done":
                    s["status"] = "running"      # a tool ran; still mid-turn
                elif kind == "idle":
                    s["status"] = "idle"
                if msg:
                    s["msg"] = msg
                    self.entries.appendleft(f"{machine} ▸ {msg}")
                if tokens is not None:
                    s["tokens"] = tokens
            s = self.sessions.get(key)
            if s:
                s["ts"] = time.monotonic()
        self._dirty.set()

    # ---- permission control loop ----------------------------------------- #
    def register_permission(self, machine, session, tool, hint):
        p = Pending(machine, session, tool, hint)
        with self.lock:
            self.by_id[p.id] = p
            self.pending.append(p)
            s = self.sessions.setdefault((machine, session),
                                         {"status": "idle", "msg": "", "ts": time.monotonic(), "tokens": 0})
            s["status"] = "waiting"
        self._dirty.set()
        return p.id

    def await_decision(self, pid, timeout=DECISION_TIMEOUT_SEC):
        p = self.by_id.get(pid)
        if not p:
            return "timeout"
        decided = p.event.wait(timeout)
        with self.lock:
            self.by_id.pop(pid, None)
            try:
                self.pending.remove(p)
            except ValueError:
                pass
            if self.current is p:
                self.current = None
            # mark the session no longer waiting
            s = self.sessions.get((p.machine, p.session))
            if s and s["status"] == "waiting":
                s["status"] = "idle"
        self._dirty.set()
        return p.decision if decided and p.decision else "timeout"

    def resolve(self, pid, decision):
        """Resolve a prompt from ANY source (device A/B, dashboard, timeout…).
        Drop it from the display queue immediately so the next heartbeat clears
        the device's alert + LED even when no hook long-poll is waiting to do it.
        Keep it in by_id so a slightly-later await_decision still reads the
        decision (avoids losing a fast approve made before the hook long-polls)."""
        with self.lock:
            p = self.by_id.get(pid)
            if not p:
                return False
            p.decision = decision
            try:
                self.pending.remove(p)
            except ValueError:
                pass
            if self.current is p:
                self.current = None
            s = self.sessions.get((p.machine, p.session))
            if s and s["status"] == "waiting":
                s["status"] = "idle"
            p.event.set()
        self._dirty.set()
        return True

    def resolve_current(self, decision):
        """Convenience for the mock: decide whatever prompt is on screen."""
        with self.lock:
            p = self.current or (self.pending[0] if self.pending else None)
        if p:
            return self.resolve(p.id, decision)
        return False

    # ---- heartbeat ------------------------------------------------------- #
    def build_heartbeat(self):
        with self.lock:
            now = time.monotonic()
            reaped = set()
            for k, s in list(self.sessions.items()):
                limit = STALE_RUNNING_SEC if s["status"] == "running" else STALE_SESSION_SEC
                if now - s["ts"] > limit:
                    reaped.add(k[0])   # machine name
                    del self.sessions[k]
            # Clear entries from reaped machines so stale transcript lines
            # don't linger on the device indefinitely.
            if reaped:
                self.entries = deque(
                    (e for e in self.entries
                     if not any(e.startswith(f"{m} ▸") for m in reaped)),
                    maxlen=8)
            # reap orphaned prompts (hook died mid-poll, etc.) so the device
            # can never latch its alert indefinitely
            for pid, p in list(self.by_id.items()):
                if now - p.created > PROMPT_TTL:
                    self.by_id.pop(pid, None)
                    try:
                        self.pending.remove(p)
                    except ValueError:
                        pass
                    p.event.set()
            # pick the prompt to display (FIFO, one at a time)
            self.current = self.pending[0] if self.pending else None
            total = len(self.sessions)
            running = sum(1 for s in self.sessions.values() if s["status"] == "running")
            waiting = len(self.pending)
            tokens = sum(s["tokens"] for s in self.sessions.values())
            hb = {
                "total": total,
                "running": running,
                "waiting": waiting,
                "tokens": tokens,
                "entries": list(self.entries),
            }
            if self.current:
                hb["msg"] = f"approve: {self.current.tool}"
                hb["prompt"] = {"id": self.current.id,
                                "tool": self.current.tool,
                                "hint": self.current.hint}
            elif running:
                hb["msg"] = next((s["msg"] for s in self.sessions.values()
                                  if s["status"] == "running" and s["msg"]), "working")
            elif total:
                hb["msg"] = "idle"
            else:
                hb["msg"] = ""
            return hb

    def detail(self):
        """Heartbeat plus per-machine + per-session breakdown (for the dashboard)."""
        hb = self.build_heartbeat()
        with self.lock:
            now = time.monotonic()
            sessions, machines = [], {}
            for (machine, sid), s in self.sessions.items():
                sessions.append({"machine": machine, "id": sid[:6], "status": s["status"],
                                 "msg": s["msg"], "idle": int(now - s["ts"])})
                m = machines.setdefault(machine, {"total": 0, "running": 0, "waiting": 0, "idle": 0})
                m["total"] += 1
                m[s["status"] if s["status"] in ("running", "waiting") else "idle"] += 1
            sessions.sort(key=lambda x: (x["status"] != "waiting", x["status"] != "running", x["idle"]))
        hb["machines"], hb["sessions"] = machines, sessions
        return hb

    # ---- driver loop ----------------------------------------------------- #
    def run(self):
        last = 0.0
        while True:
            fired = self._dirty.wait(timeout=1.0)
            self._dirty.clear()
            now = time.monotonic()
            # Adaptive keepalive: fast when sessions are active (prompt
            # responsiveness matters), slow when idle (saves device battery).
            with self.lock:
                active = bool(self.sessions)
            interval = KEEPALIVE_ACTIVE_SEC if active else KEEPALIVE_IDLE_SEC
            if fired or (now - last) >= interval:
                self.transport.send(self.build_heartbeat())
                last = now


# --------------------------------------------------------------------------- #
# Transports                                                                    #
# --------------------------------------------------------------------------- #
class MockTransport:
    """Prints heartbeats to the console; reads a/d from stdin as A/B buttons."""
    def __init__(self):
        self.hub = None
        self._last_sig = None
        self._last_sent = 0.0

    def send(self, hb):
        # only redraw when something meaningful changed — but always retransmit
        # after KEEPALIVE_FLOOR_SEC so the firmware never times out
        now = time.monotonic()
        sig = (hb["total"], hb["running"], hb["waiting"], hb.get("tokens"),
               hb.get("msg"), (hb.get("prompt") or {}).get("id"),
               hash(tuple(hb.get("entries", []))))
        if sig == self._last_sig and (now - self._last_sent) < KEEPALIVE_FLOOR_SEC:
            return
        self._last_sig, self._last_sent = sig, now
        state = self._state_name(hb)
        line = (f"[{time.strftime('%H:%M:%S')}] {state:9s} "
                f"total={hb['total']} running={hb['running']} waiting={hb['waiting']} "
                f"tok={hb['tokens']}  {hb.get('msg','')}")
        print("\n" + line)
        if hb.get("prompt"):
            p = hb["prompt"]
            print(f"    ⚑ PERMISSION  {p['tool']}: {p['hint']}")
            print(f"      press  a = approve   d = deny")
        if hb["entries"]:
            print("    recent: " + " | ".join(hb["entries"][:3]))
        sys.stdout.flush()

    @staticmethod
    def _state_name(hb):
        if hb["waiting"]:
            return "ATTENTION"
        if hb["running"]:
            return "BUSY"
        if hb["total"]:
            return "IDLE"
        return "SLEEP"

    def input_loop(self):
        for raw in sys.stdin:
            cmd = raw.strip().lower()
            if cmd in ("a", "y", "approve", "once"):
                ok = self.hub.resolve_current("once")
                print("  -> approved" if ok else "  (no prompt to approve)")
            elif cmd in ("d", "n", "deny"):
                ok = self.hub.resolve_current("deny")
                print("  -> denied" if ok else "  (no prompt to deny)")
            elif cmd in ("s", "state"):
                print(json.dumps(self.hub.build_heartbeat(), indent=2))
            elif cmd in ("q", "quit"):
                import os
                os._exit(0)


class RelayTransport:
    """TCP bridge to the Windows-side BLE relay. Heartbeats go out as JSON
    lines (the relay writes them to the stick's Nordic UART RX); the stick's
    lines (button-press permission decisions) come back and resolve prompts.
    One relay connects at a time; reconnects are handled."""
    def __init__(self, port=8790, owner="there"):
        self.hub = None
        self.port = port
        self.owner = owner
        self.conn = None
        self.lock = threading.Lock()
        self._last_sig = None    # dedup: skip sending identical heartbeats
        self._last_sent = 0.0    # monotonic time of last actual send
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))      # reachable from the Windows relay
        srv.listen(1)
        print(f"relay transport: waiting for BLE relay on 0.0.0.0:{self.port}")
        while True:
            conn, _ = srv.accept()
            with self.lock:
                old, self.conn = self.conn, conn
            if old is not None:               # a reconnecting relay (e.g. after a
                self._drop(old)               # device reboot) takes over the stale one
            print(f"[{time.strftime('%H:%M:%S')}] relay connected")
            self._on_connect()
            threading.Thread(target=self._reader, args=(conn,), daemon=True).start()

    @staticmethod
    def _drop(conn):
        for op in (lambda: conn.shutdown(socket.SHUT_RDWR), conn.close):
            try:
                op()
            except OSError:
                pass

    def _on_connect(self):
        off = time.localtime().tm_gmtoff or 0
        self._raw({"time": [int(time.time()), off]})
        self._raw({"cmd": "owner", "name": self.owner})
        if self.hub:
            self._raw(self.hub.build_heartbeat())

    def send(self, hb):
        # Skip sending if the heartbeat is identical to the last one —
        # avoids waking the BLE radio for duplicate idle keepalives.
        # But always retransmit after KEEPALIVE_FLOOR_SEC so the firmware
        # never sees >30s silence and marks itself disconnected.
        now = time.monotonic()
        sig = (hb["total"], hb["running"], hb["waiting"], hb.get("tokens"),
               hb.get("msg"), (hb.get("prompt") or {}).get("id"),
               hash(tuple(hb.get("entries", []))))
        if sig == self._last_sig and (now - self._last_sent) < KEEPALIVE_FLOOR_SEC:
            return
        self._last_sig, self._last_sent = sig, now
        self._raw(hb)

    def _raw(self, obj):
        line = (json.dumps(obj) + "\n").encode()
        with self.lock:
            if self.conn:
                try:
                    self.conn.sendall(line)
                except OSError:
                    self.conn = None

    def _reader(self, conn):
        buf = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._handle(line)
        except OSError:
            pass
        finally:
            with self.lock:
                if self.conn is conn:         # only clear if a newer relay
                    self.conn = None          # hasn't already taken over
            self._drop(conn)
            print(f"[{time.strftime('%H:%M:%S')}] relay disconnected")

    def _handle(self, line):
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        if msg.get("cmd") == "permission" and self.hub:
            ok = self.hub.resolve(msg.get("id", ""), msg.get("decision", "deny"))
            print(f"[{time.strftime('%H:%M:%S')}] device decision "
                  f"{msg.get('decision')} for {msg.get('id')} -> {'ok' if ok else 'stale'}")


# --------------------------------------------------------------------------- #
# HTTP server                                                                   #
# --------------------------------------------------------------------------- #
from importlib.resources import files
try:
    DASHBOARD_HTML = (files("buddybridge.resources") / "dashboard.html").read_text(encoding="utf-8")
except (OSError, ModuleNotFoundError):
    DASHBOARD_HTML = "<!doctype html><title>Claude Buddy</title><body>dashboard.html missing</body>"



def make_handler(hub):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):       # quiet
            pass

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                return {}

        def do_POST(self):
            path = urlparse(self.path).path
            data = self._read()
            if path == "/event":
                hub.event(data.get("machine", "?"), data.get("session", "?"),
                          data.get("kind", "idle"), data.get("msg"), data.get("tokens"))
                return self._json(200, {"ok": True})
            if path == "/permission":
                pid = hub.register_permission(data.get("machine", "?"),
                                              data.get("session", "?"),
                                              data.get("tool", "?"),
                                              data.get("hint", ""))
                return self._json(200, {"id": pid})
            if path == "/button":
                # stand-in for the device A/B buttons (headless test / web UI)
                ok = hub.resolve_current(data.get("decision", "once"))
                return self._json(200, {"ok": ok})
            return self._json(404, {"ok": False, "error": "no route"})

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/dashboard"):
                body = DASHBOARD_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path == "/decision":
                q = parse_qs(u.query)
                pid = (q.get("id") or [""])[0]
                try:
                    wait = float((q.get("wait") or [DECISION_TIMEOUT_SEC])[0])
                except ValueError:
                    wait = DECISION_TIMEOUT_SEC
                decision = hub.await_decision(pid, timeout=wait)
                return self._json(200, {"decision": decision})
            if u.path == "/detail":
                return self._json(200, hub.detail())
            if u.path == "/state":
                return self._json(200, hub.build_heartbeat())
            return self._json(404, {"ok": False})
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--transport", choices=["mock", "relay"], default="mock")
    ap.add_argument("--relay-port", type=int, default=8790)
    ap.add_argument("--owner", default="there")
    args = ap.parse_args()

    if args.transport == "relay":
        transport = RelayTransport(port=args.relay_port, owner=args.owner)
    else:
        transport = MockTransport()
    hub = Hub(transport)

    srv = ThreadingHTTPServer((args.bind, args.port), make_handler(hub))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=hub.run, daemon=True).start()

    print(f"buddyhub listening on {args.bind}:{args.port}  ({args.transport} transport)")
    if args.transport == "mock" and sys.stdin.isatty():
        print("  type  a = approve   d = deny   s = state   q = quit")
        transport.input_loop()
    else:
        # headless service / relay mode: A/B come from the device or POST /button
        print("  POST /button {\"decision\":\"once\"|\"deny\"} also works")
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
