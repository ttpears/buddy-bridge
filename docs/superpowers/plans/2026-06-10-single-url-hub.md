# Single-URL Hub + Relay-Only Phone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all relay traffic onto the hub's single HTTP port so every machine and the phone become outbound clients of one URL — fixing Android reachability, deleting the SSH-tunnel/WSL special-casing, and adding macOS install parity.

**Architecture:** The hub gains two HTTP endpoints — `GET /relay/stream` (chunked newline-JSON heartbeats out) and `POST /button` (A/B decisions in) — replacing the raw TCP `:8790` `RelayTransport`. `relay.py` and the Android app both become outbound clients of `/relay/stream`. Auth (`BUDDY_TOKEN`) is extended to gate every endpoint. `buddyctl` drops `tunnel`/`--tunnel`/`--relay-port` and gains a macOS `launchd` path. Spec: `docs/superpowers/specs/2026-06-10-single-url-hub-design.md`.

**Tech Stack:** Python 3 stdlib (`http.server`, `urllib`, `threading`, `queue`); `bleak` (relay BLE); Kotlin/Android (NanoHTTPD, coroutines, OkHttp-free `HttpURLConnection`); pytest.

---

## File Structure

**Python — modified:**
- `buddybridge/hub.py` — add `StreamClient` + `HttpRelayTransport`; delete `RelayTransport`; `/relay/stream` + id-aware `/button`; auth on all endpoints; `main()` wiring.
- `buddybridge/relay.py` — consume `/relay/stream` over HTTP, POST `/button`; `--hub` is now a URL; token from env/config.
- `buddybridge/ctl/__init__.py` — delete `tunnel` subcommand + `--tunnel`; relay install points at hub URL; status shows hub URL.
- `buddybridge/ctl/services.py` — add macOS `launchd` LaunchAgent path.
- `buddybridge/ctl/hooks.py` — unchanged (reference only).

**Python — deleted:**
- `buddybridge/ctl/tunnel.py`
- `tests/test_ctl_tunnel.py`

**Python — tests added/modified:**
- `tests/test_hub_relay_stream.py` — new: transport unit + HTTP stream/button integration + auth.
- `tests/test_ctl_services.py` — add macOS launchd cases.
- `tests/test_ctl_cli.py` — drop tunnel expectations; relay-URL expectation.

**Android — modified:**
- `android/app/src/main/java/com/claudebuddy/bridge/data/Settings.kt` — `MODE` + `REMOTE_HUB_URL`.
- `android/app/src/main/java/com/claudebuddy/bridge/service/BuddyService.kt` — branch serve-hub vs relay-to-remote.
- `android/app/src/main/java/com/claudebuddy/bridge/ui/BridgeScreen.kt` — mode toggle + URL field.

**Android — added:**
- `android/app/src/main/java/com/claudebuddy/bridge/relay/RelayClient.kt` — outbound `/relay/stream` consumer + `/button` POST.

**Docs:**
- `README.md` — single-URL model, Traefik recipe, macOS, phone relay-only; delete tunnel recipes.

---

## Phase A — Hub: HTTP relay stream

### Task A1: `/button` resolves a specific prompt id

**Files:**
- Modify: `buddybridge/hub.py:474-477` (the `/button` POST branch)
- Test: `tests/test_hub_relay_stream.py`

The device's button press is a line `{"cmd":"permission","id":"req_…","decision":"once"|"deny"}`. Today the TCP relay parsed that and called `hub.resolve(id, …)`. With the relay POSTing to `/button`, the endpoint must honor an `id` when present and fall back to `resolve_current` (dashboard buttons send no id).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_relay_stream.py
from buddybridge import hub as hubmod


def _hub():
    return hubmod.Hub(hubmod.MockTransport())


def test_button_resolves_specific_id():
    h = _hub()
    pid = h.register_permission("box", "s1", "Bash", "ls")
    # a second, newer prompt becomes "current"; id routing must still hit pid
    h.register_permission("box", "s2", "Edit", "f.py")
    h.build_heartbeat()  # sets current = first pending (FIFO)
    decided = {}

    def waiter():
        decided["d"] = h.await_decision(pid, timeout=2)

    import threading
    t = threading.Thread(target=waiter); t.start()
    assert hubmod.resolve_button(h, {"id": pid, "decision": "deny"}) is True
    t.join(3)
    assert decided["d"] == "deny"


def test_button_without_id_uses_current():
    h = _hub()
    pid = h.register_permission("box", "s1", "Bash", "ls")
    h.build_heartbeat()
    assert hubmod.resolve_button(h, {"decision": "once"}) is True
    assert h.by_id[pid].decision == "once"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hub_relay_stream.py -v`
Expected: FAIL — `AttributeError: module 'buddybridge.hub' has no attribute 'resolve_button'`

- [ ] **Step 3: Add the helper and use it in the handler**

Add this module-level function to `buddybridge/hub.py` (just above `def make_handler`):

```python
def resolve_button(hub, data):
    """Resolve a permission from a /button POST or a device line: honor an
    explicit prompt id when present, else decide whatever is on screen."""
    pid = data.get("id")
    decision = data.get("decision", "once")
    if pid:
        return hub.resolve(pid, decision)
    return hub.resolve_current(decision)
```

Replace the `/button` branch in `do_POST` (currently `hub.resolve_current(...)`):

```python
            if path == "/button":
                ok = resolve_button(hub, data)
                return self._json(200, {"ok": ok})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hub_relay_stream.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add buddybridge/hub.py tests/test_hub_relay_stream.py
git commit -m "feat(hub): /button resolves a specific prompt id"
```

---

### Task A2: `StreamClient` + `HttpRelayTransport`

**Files:**
- Modify: `buddybridge/hub.py` (add classes after `MockTransport`, near line 315)
- Test: `tests/test_hub_relay_stream.py`

A `StreamClient` is one connected relay's outbound queue. `HttpRelayTransport` keeps exactly one current client (last attach wins, mirroring the old TCP "one relay" rule), dedups heartbeats with the same floor logic as the old transport, and primes a newly-attached client with `time`/`owner`/current heartbeat.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_hub_relay_stream.py
def test_transport_attach_primes_and_send_enqueues():
    t = hubmod.HttpRelayTransport(owner="me")
    h = hubmod.Hub(t)            # Hub.__init__ sets transport.hub = self
    c = t.attach()
    # priming frames: time, owner, an initial heartbeat
    kinds = [c.get(timeout=1) for _ in range(3)]
    assert any("time" in f for f in kinds)
    assert any(f.get("cmd") == "owner" and f.get("name") == "me" for f in kinds)
    # a state change pushes a fresh heartbeat to the client
    h.event("box", "s1", "running", msg="building")
    t.send(h.build_heartbeat())
    assert c.get(timeout=1)["running"] == 1


def test_transport_attach_displaces_old_client():
    t = hubmod.HttpRelayTransport()
    hubmod.Hub(t)
    c1 = t.attach()
    c2 = t.attach()                 # newer relay takes over
    assert c1.closed is True
    t.send({"total": 0, "running": 0, "waiting": 0, "tokens": 0, "entries": []})
    # closed client never receives further frames; current one does
    assert c2.get(timeout=1)["total"] == 0


def test_transport_send_dedups_until_floor():
    t = hubmod.HttpRelayTransport()
    hubmod.Hub(t)
    c = t.attach()
    for _ in range(3):
        c.get(timeout=1)            # drain priming frames
    hb = {"total": 1, "running": 0, "waiting": 0, "tokens": 5, "entries": []}
    t.send(hb)
    assert c.get(timeout=1)["tokens"] == 5
    t.send(dict(hb))                # identical -> deduped, nothing enqueued
    assert c.empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hub_relay_stream.py -k transport -v`
Expected: FAIL — `AttributeError: module 'buddybridge.hub' has no attribute 'HttpRelayTransport'`

- [ ] **Step 3: Implement the classes**

Add `import queue` to the imports block at the top of `buddybridge/hub.py`. Add these classes after the `MockTransport` class (after line 315):

```python
class StreamClient:
    """One connected relay's outbound frame queue (newline-JSON objects)."""
    def __init__(self):
        self._q = queue.Queue()
        self.closed = False

    def put(self, obj):
        if not self.closed:
            self._q.put(obj)

    def get(self, timeout=None):
        return self._q.get(timeout=timeout)

    def empty(self):
        return self._q.empty()

    def close(self):
        self.closed = True
        self._q.put(None)            # sentinel unblocks a waiting writer


class HttpRelayTransport:
    """Heartbeats stream out over HTTP (GET /relay/stream); A/B presses come
    back via POST /button. Replaces the TCP RelayTransport so everything rides
    one HTTP port (one URL, one token, Traefik-friendly). One relay at a time:
    a new attach() displaces the previous client, matching the old socket."""
    def __init__(self, owner="there"):
        self.hub = None
        self.owner = owner
        self.lock = threading.Lock()
        self.client = None
        self._last_sig = None
        self._last_sent = 0.0

    def attach(self):
        c = StreamClient()
        with self.lock:
            old, self.client = self.client, c
            self._last_sig = None       # force a full heartbeat to the newcomer
        if old is not None:
            old.close()
        off = time.localtime().tm_gmtoff or 0
        c.put({"time": [int(time.time()), off]})
        c.put({"cmd": "owner", "name": self.owner})
        if self.hub:
            c.put(self.hub.build_heartbeat())
        return c

    def detach(self, c):
        with self.lock:
            if self.client is c:
                self.client = None
                self._last_sig = None

    def send(self, hb):
        # Same dedup + floor rule as the old RelayTransport: skip identical
        # heartbeats, but always retransmit after KEEPALIVE_FLOOR_SEC so the
        # firmware never sees >30s silence.
        now = time.monotonic()
        sig = (hb["total"], hb["running"], hb["waiting"], hb.get("tokens"),
               hb.get("msg"), (hb.get("prompt") or {}).get("id"),
               hash(tuple(hb.get("entries", []))))
        with self.lock:
            if sig == self._last_sig and (now - self._last_sent) < KEEPALIVE_FLOOR_SEC:
                return
            self._last_sig, self._last_sent = sig, now
            c = self.client
        if c is not None:
            c.put(hb)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hub_relay_stream.py -k transport -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add buddybridge/hub.py tests/test_hub_relay_stream.py
git commit -m "feat(hub): HttpRelayTransport + StreamClient (HTTP relay stream)"
```

---

### Task A3: `GET /relay/stream` chunked endpoint + auth on every route

**Files:**
- Modify: `buddybridge/hub.py` — `make_handler` (lines 428-504)
- Test: `tests/test_hub_relay_stream.py`

The relay stream is a chunked HTTP/1.1 response: one newline-JSON frame per chunk. Auth (when a token is set) now gates **every** route — the dashboard, `/decision`, `/detail`, `/state`, `/relay/stream`, and writes. Stream GETs accept the token via header **or** `?token=` (BLE relays/phones set it on the query for simplicity).

- [ ] **Step 1: Write the failing integration test**

```python
# add to tests/test_hub_relay_stream.py
import json
import threading
import urllib.request
import urllib.error

from http.server import ThreadingHTTPServer


def _serve(token=""):
    t = hubmod.HttpRelayTransport(owner="me")
    h = hubmod.Hub(t)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hubmod.make_handler(h, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=h.run, daemon=True).start()
    return h, srv, srv.server_address[1]


def test_relay_stream_delivers_frames_and_button_resolves():
    h, srv, port = _serve()
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/relay/stream", timeout=3)
        first = json.loads(resp.readline())          # primed "time" frame
        assert "time" in first
        # raise a prompt; a heartbeat with the prompt should stream out
        pid = h.register_permission("box", "s1", "Bash", "ls -la")
        prompt = None
        for _ in range(20):
            obj = json.loads(resp.readline())
            if obj.get("prompt"):
                prompt = obj["prompt"]; break
        assert prompt and prompt["id"] == pid
        # approve via /button
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/button",
            data=json.dumps({"id": pid, "decision": "once"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        assert json.loads(urllib.request.urlopen(req, timeout=3).read())["ok"] is True
        resp.close()
    finally:
        srv.shutdown()


def test_token_gates_stream_and_reads():
    h, srv, port = _serve(token="secret")
    try:
        for path in ("/relay/stream", "/decision?id=x", "/detail", "/state", "/"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3)
                assert False, f"{path} should require a token"
            except urllib.error.HTTPError as e:
                assert e.code == 401
        # query-string token is accepted for the stream
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/relay/stream?token=secret", timeout=3)
        assert "time" in json.loads(resp.readline())
        resp.close()
    finally:
        srv.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hub_relay_stream.py -k "stream or token_gates" -v`
Expected: FAIL — `/relay/stream` returns 404 (route missing).

- [ ] **Step 3: Implement the handler changes**

In `make_handler`, set the protocol version (needed for chunked) by adding inside `class H(BaseHTTPRequestHandler):` near the top:

```python
        protocol_version = "HTTP/1.1"
```

Replace `_authed` so it also reads a query token:

```python
        def _authed(self):
            if not token:
                return True
            provided = self.headers.get("X-Buddy-Token", "")
            if not provided:
                provided = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
            return hmac.compare_digest(provided, token)
```

In `do_GET`, add the auth gate as the first line and add the `/relay/stream` route. The method becomes:

```python
        def do_GET(self):
            if not self._authed():
                return self._json(401, {"ok": False, "error": "unauthorized"})
            u = urlparse(self.path)
            if u.path == "/relay/stream":
                return self._stream()
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

        def _stream(self):
            transport = hub.transport
            if not hasattr(transport, "attach"):
                return self._json(404, {"ok": False, "error": "no relay transport"})
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            client = transport.attach()
            try:
                while True:
                    obj = client.get(timeout=KEEPALIVE_FLOOR_SEC)
                    if obj is None:           # displaced by a newer relay
                        break
                    chunk = (json.dumps(obj) + "\n").encode()
                    self.wfile.write(f"{len(chunk):X}\r\n".encode())
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
            except (queue.Empty, BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                transport.detach(client)
```

Note `queue.Empty` from a `client.get(timeout=…)` simply ends the stream; the relay reconnects (its supervise loop), and the firmware's 30s window is covered because `KEEPALIVE_FLOOR_SEC` (20s) < 30s, so `Hub.run` always re-sends within the window and the timeout rarely fires.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_hub_relay_stream.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add buddybridge/hub.py tests/test_hub_relay_stream.py
git commit -m "feat(hub): GET /relay/stream chunked endpoint; auth gates all routes"
```

---

### Task A4: Wire `main()` to `HttpRelayTransport`; delete `RelayTransport`

**Files:**
- Modify: `buddybridge/hub.py` — delete `RelayTransport` (lines 317-414), update `main()` (507-545), update module docstring (17-23)

- [ ] **Step 1: Delete the `RelayTransport` class**

Remove the entire `class RelayTransport:` block (from `class RelayTransport:` through its final `_handle` method). `socket` is still imported but now unused by hub — remove `import socket` from the imports if nothing else references it (grep first: `grep -n "socket" buddybridge/hub.py`; only the import should remain — delete it).

- [ ] **Step 2: Update `main()`**

Replace the transport construction and the `--relay-port` argument:

```python
    ap.add_argument("--transport", choices=["mock", "relay"], default="mock")
    ap.add_argument("--owner", default="there")
```

(delete the `--relay-port` line), and:

```python
    if args.transport == "relay":
        transport = HttpRelayTransport(owner=args.owner)
    else:
        transport = MockTransport()
    hub = Hub(transport)
```

- [ ] **Step 3: Update the docstring**

In the module docstring (lines 17-23) add the two endpoints under "HTTP API":

```
  GET  /relay/stream   chunked newline-JSON heartbeats -> the BLE relay
  POST /button      {id?, decision}   A/B decision from the relay/device/web
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS (the old `RelayTransport` had no direct test; `test_hub_relay_stream.py` covers the replacement).

- [ ] **Step 5: Commit**

```bash
git add buddybridge/hub.py
git commit -m "refactor(hub): use HttpRelayTransport in main(); delete TCP RelayTransport"
```

---

## Phase B — Relay client (Python)

### Task B1: `relay.py` consumes `/relay/stream`, POSTs `/button`

**Files:**
- Modify: `buddybridge/relay.py` (whole file — transport swap; BLE half unchanged)
- Test: `tests/test_ctl_cli.py::test_relay_main_accepts_argv` (already asserts `--help` works; keep it green)

The relay stops dialing a TCP socket and instead opens `GET {hub}/relay/stream`, reads newline-JSON lines, and writes them to BLE verbatim. Device notifications (button presses) are parsed and POSTed to `{hub}/button`. `--hub` is now a URL; the token comes from `$BUDDY_TOKEN` or the per-machine config (same resolution as the hook).

- [ ] **Step 1: Rewrite the transport half of `relay.py`**

Replace the imports and `relay_once`/`main` with the version below. Keep `single_instance`, `setup_logging`, `_drain` is dropped (no socket writer). Full file:

```python
#!/usr/bin/env python3
"""
relay.py — M5Stick BLE relay (runs on the machine with the Bluetooth radio).
Bridges a buddyhub's HTTP relay stream <-> the stick's BLE Nordic UART.

Outbound only: opens GET {hub}/relay/stream (chunked newline-JSON heartbeats),
writes each line to the stick verbatim, and POSTs the stick's button presses to
{hub}/button. No inbound port — so it works behind NAT, on a laptop, anywhere.

  buddy-relay                   # background run (logs to relay.log)
  buddy-relay --console         # foreground + console logging (debugging)
  buddy-relay --hub https://buddy.example.com   # remote hub over TLS
"""
import argparse
import asyncio
import json
import logging
import logging.handlers
import socket
import sys
import urllib.request
from pathlib import Path

from buddybridge import config as _config

NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write   host -> device
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify  device -> host

LOCK_PORT = 8791
LOGFILE = Path(__file__).resolve().parent / "relay.log"
_lock = None


def single_instance():
    global _lock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
    except OSError:
        return False
    _lock = s
    return True


def setup_logging(console):
    handlers = [logging.handlers.RotatingFileHandler(
        LOGFILE, maxBytes=512 * 1024, backupCount=1, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)


def resolve_hub(arg):
    return (arg or _config.load_config().get("hub") or "http://127.0.0.1:8787").rstrip("/")


def resolve_token():
    import os
    return os.environ.get("BUDDY_TOKEN") or _config.load_config().get("token") or ""


def post_button(hub, token, payload):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Buddy-Token"] = token
    req = urllib.request.Request(hub + "/button", data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        logging.info("button POST failed: %s", e)


def open_stream(hub, token):
    url = hub + "/relay/stream"
    headers = {}
    if token:
        headers["X-Buddy-Token"] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    return urllib.request.urlopen(req, timeout=None)


async def relay_once(hub, token, name_prefix, scan_timeout, do_pair, pair_timeout):
    from bleak import BleakScanner, BleakClient
    logging.info("scanning for the stick")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or "").startswith(name_prefix), timeout=scan_timeout)
    if not dev:
        logging.info("no BLE device advertising '%s*' found", name_prefix)
        return
    logging.info("found %s [%s]; connecting BLE", dev.name, dev.address)
    loop = asyncio.get_running_loop()
    lines = asyncio.Queue()

    def reader_thread(resp):
        """Blocking HTTP stream reader -> asyncio queue (runs in a thread)."""
        try:
            for raw in resp:
                line = raw.decode(errors="ignore").strip()
                if line:
                    loop.call_soon_threadsafe(lines.put_nowait, line)
        except Exception as e:
            logging.info("stream read ended: %s", e)
        finally:
            loop.call_soon_threadsafe(lines.put_nowait, None)   # EOF sentinel

    async with BleakClient(dev) as client:
        if do_pair:
            try:
                await client.pair()
            except Exception as e:
                logging.info("pair() note: %s", e)
        logging.info("BLE connected")

        def on_notify(_s, data: bytearray):
            # Device -> host: button-press permission lines. Parse and POST.
            for piece in bytes(data).decode(errors="ignore").splitlines():
                piece = piece.strip()
                if not piece:
                    continue
                try:
                    msg = json.loads(piece)
                except json.JSONDecodeError:
                    continue
                if msg.get("cmd") == "permission":
                    loop.run_in_executor(None, post_button, hub, token,
                                         {"id": msg.get("id", ""),
                                          "decision": msg.get("decision", "deny")})

        deadline = loop.time() + pair_timeout
        while True:
            try:
                await client.start_notify(NUS_TX, on_notify)
                break
            except Exception as e:
                if loop.time() >= deadline:
                    raise
                logging.info("waiting for pairing — enter the passkey on the desktop (%s)", e)
                await asyncio.sleep(2.0)

        logging.info("connecting hub stream %s", hub)
        resp = await loop.run_in_executor(None, open_stream, hub, token)
        loop.run_in_executor(None, reader_thread, resp)
        logging.info("subscribed; relaying")
        mtu = (client.mtu_size - 3) if getattr(client, "mtu_size", 0) else 20
        try:
            while True:
                line = await lines.get()
                if line is None:
                    logging.info("hub stream closed")
                    break
                payload = (line + "\n").encode()
                chunks = [payload[i:i + mtu] for i in range(0, len(payload), mtu)]
                for idx, chunk in enumerate(chunks):
                    await client.write_gatt_char(NUS_RX, chunk, response=False)
                    if idx < len(chunks) - 1:
                        await asyncio.sleep(0.005)
        finally:
            try:
                resp.close()
            except Exception:
                pass


async def supervise(args):
    hub = resolve_hub(args.hub)
    token = resolve_token()
    while True:
        try:
            await relay_once(hub, token, args.name, args.scan_timeout,
                             not args.no_pair, args.pair_timeout)
        except Exception as e:
            logging.info("relay error: %s", e)
        await asyncio.sleep(args.retry)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=None,
                    help="hub base URL (default: config hub or http://127.0.0.1:8787)")
    ap.add_argument("--name", default="Claude")
    ap.add_argument("--scan-timeout", type=float, default=15.0)
    ap.add_argument("--no-pair", action="store_true")
    ap.add_argument("--pair-timeout", type=float, default=60.0,
                    help="seconds to keep one passkey on screen while you enter it")
    ap.add_argument("--retry", type=float, default=5.0)
    ap.add_argument("--console", action="store_true")
    args = ap.parse_args(argv)

    try:
        import bleak  # noqa: F401
    except ModuleNotFoundError:
        print("buddy-relay needs Bluetooth support. Install it with:\n"
              "    pipx install 'buddy-bridge[relay]'   (or: pip install bleak)",
              file=sys.stderr)
        sys.exit(1)

    setup_logging(args.console)
    if not single_instance():
        logging.info("another relay instance already running (lock %d held); exiting", LOCK_PORT)
        return
    logging.info("relay starting (hub %s)", resolve_hub(args.hub))
    try:
        asyncio.run(supervise(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the relay CLI test**

Run: `pytest tests/test_ctl_cli.py::test_relay_main_accepts_argv -v`
Expected: PASS (`--help` still exits 0; argv honored).

- [ ] **Step 3: Sanity-check parsing of a URL hub**

Run: `python -c "from buddybridge.relay import resolve_hub; print(resolve_hub('https://buddy.x.com/'))"`
Expected output: `https://buddy.x.com`

- [ ] **Step 4: Commit**

```bash
git add buddybridge/relay.py
git commit -m "feat(relay): consume hub /relay/stream over HTTP; POST /button"
```

---

## Phase C — buddyctl

### Task C1: Delete the tunnel feature

**Files:**
- Delete: `buddybridge/ctl/tunnel.py`, `tests/test_ctl_tunnel.py`
- Modify: `buddybridge/ctl/__init__.py` (remove tunnel import, `_tunnel_*`, `--tunnel`, the `tunnel` subparser, tunnel branches in `_client_install`)

- [ ] **Step 1: Delete the files**

```bash
git rm buddybridge/ctl/tunnel.py tests/test_ctl_tunnel.py
```

- [ ] **Step 2: Strip tunnel from `ctl/__init__.py`**

- Line 8: change `from buddybridge.ctl import hooks, services, tunnel` → `from buddybridge.ctl import hooks, services`.
- In `_client_install` (24-44): remove the `if args.tunnel:` / `elif args.hub:` branch and replace with:

```python
def _client_install(args):
    cfg = config.load_config()
    if args.hub:
        cfg["hub"] = args.hub.rstrip("/")
    cfg.setdefault("hub", "http://127.0.0.1:8787")
    cfg["machine"] = args.name or cfg.get("machine") or socket.gethostname().split(".")[0]
    if args.token is not None:
        cfg["token"] = args.token
    config.save_config(cfg)
    cmd = hooks.install(str(_claude_settings_path()))
    print(f"client installed: machine={cfg['machine']}  hub={cfg['hub']}")
    print(f"  hook command: {cmd}")
    print("  restart any running `claude` session to load the hooks.")
```

- Delete `_tunnel_install` and `_tunnel_uninstall` (90-99).
- Delete the `--tunnel` argument line (126).
- Delete the `tunnel` subparser block (152-157).

- [ ] **Step 3: Run the CLI tests**

Run: `pytest tests/test_ctl_cli.py -v`
Expected: PASS. (`test_client_install_writes_config_and_hooks` still matches the `{"hub","machine"}` config.)

- [ ] **Step 4: Verify no dangling references**

Run: `grep -rn "tunnel" buddybridge/ tests/`
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(ctl): delete SSH-tunnel feature (single-URL hub makes it moot)"
```

---

### Task C2: Relay install points at the hub URL; status shows hub URL

**Files:**
- Modify: `buddybridge/ctl/__init__.py` — `_relay_install` (73-76), relay subparser defaults (145, 149), `_relay_pair` (84-87)
- Test: `tests/test_ctl_cli.py`

The relay now takes a hub **URL**. Default it from the saved config so a machine that already ran `client install --hub …` needs no repeat.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_ctl_cli.py
def test_relay_install_uses_hub_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    reg = []
    monkeypatch.setattr("buddybridge.ctl.services.register",
                        lambda name, cmd, desc: reg.append((name, cmd)))
    ctl.main(["relay", "install", "--hub", "https://buddy.x.com"])
    assert any(name == "buddy-relay" and "--hub https://buddy.x.com" in cmd
               for name, cmd in reg)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_ctl_cli.py::test_relay_install_uses_hub_url -v`
Expected: FAIL — current default `--hub 127.0.0.1:8790` is baked unconditionally and the value isn't a URL.

- [ ] **Step 3: Update relay install + subparser**

Replace `_relay_install`:

```python
def _relay_install(args):
    hub = args.hub or config.load_config().get("hub") or "http://127.0.0.1:8787"
    exec_cmd = f'"{_python_for_service()}" -m buddybridge.relay --hub {hub}'
    services.register("buddy-relay", exec_cmd, "Claude Buddy BLE relay")
    print(f"relay installed (hub {hub}).")
```

Replace `_relay_pair`:

```python
def _relay_pair(args):
    from buddybridge import relay
    relay.main(["--console"] + (["--hub", args.hub] if args.hub else []))
```

In the subparsers, change the relay `--hub` defaults (lines 145, 149) from `default="127.0.0.1:8790"` to `default=None` for both `pri` and `prp`.

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_ctl_cli.py::test_relay_install_uses_hub_url -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add buddybridge/ctl/__init__.py tests/test_ctl_cli.py
git commit -m "feat(ctl): relay install targets the hub URL (default from config)"
```

---

### Task C3: macOS `launchd` service path

**Files:**
- Modify: `buddybridge/ctl/services.py` (add `launchd_plist`, branch macOS in `register`/`unregister`/`status`)
- Test: `tests/test_ctl_services.py`

`sys.platform == "darwin"` gets a `LaunchAgent` plist in `~/Library/LaunchAgents/<name>.plist`, loaded with `launchctl`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_ctl_services.py
def test_launchd_plist_has_label_and_program():
    p = services.launchd_plist("com.claudebuddy.buddyhub",
                               "/usr/bin/python3 -m buddybridge.hub --port 8787")
    assert "<string>com.claudebuddy.buddyhub</string>" in p
    assert "buddybridge.hub" in p and "<key>RunAtLoad</key>" in p
    assert "<key>KeepAlive</key>" in p


def test_register_macos_writes_plist_and_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(services.sys, "platform", "darwin")
    monkeypatch.setattr(services, "_launchd_dir", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(services, "_run", lambda cmd: calls.append(cmd))
    services.register("buddyhub", "python3 -m buddybridge.hub", "Buddy Hub")
    plist = (tmp_path / "com.claudebuddy.buddyhub.plist")
    assert plist.exists() and "buddybridge.hub" in plist.read_text()
    assert any("bootstrap" in c or "load" in c for c in (" ".join(map(str, x)) for x in calls))
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_ctl_services.py -k "launchd or macos" -v`
Expected: FAIL — `AttributeError: module 'buddybridge.ctl.services' has no attribute 'launchd_plist'`

- [ ] **Step 3: Implement the macOS path**

Add to `buddybridge/ctl/services.py`:

```python
import shlex

_LABEL_PREFIX = "com.claudebuddy."


def _label(name):
    return _LABEL_PREFIX + name


def launchd_plist(label, exec_cmd):
    args = shlex.split(exec_cmd)
    arg_xml = "\n".join(f"    <string>{a}</string>" for a in args)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f'  <key>Label</key>\n  <string>{label}</string>\n'
        f'  <key>ProgramArguments</key>\n  <array>\n{arg_xml}\n  </array>\n'
        '  <key>RunAtLoad</key>\n  <true/>\n'
        '  <key>KeepAlive</key>\n  <true/>\n'
        '</dict>\n</plist>\n'
    )


def _launchd_dir():
    return Path.home() / "Library" / "LaunchAgents"
```

Add a `darwin` branch at the top of `register`, `unregister`, and `status` (before the win32 check). `register`:

```python
def register(name, exec_cmd, description):
    if sys.platform == "darwin":
        d = _launchd_dir(); d.mkdir(parents=True, exist_ok=True)
        plist = d / f"{_label(name)}.plist"
        plist.write_text(launchd_plist(_label(name), exec_cmd), encoding="utf-8")
        _run(["launchctl", "unload", str(plist)])           # idempotent reload
        _run(["launchctl", "load", str(plist)])
        return
    if sys.platform == "win32":
        ...
```

`unregister`:

```python
def unregister(name):
    if sys.platform == "darwin":
        plist = _launchd_dir() / f"{_label(name)}.plist"
        _run(["launchctl", "unload", str(plist)])
        plist.unlink(missing_ok=True)
        return
    if sys.platform == "win32":
        ...
```

`status`:

```python
def status(name):
    if sys.platform == "darwin":
        out = subprocess.run(["launchctl", "list", _label(name)],
                             capture_output=True, text=True)
        return "active" if out.returncode == 0 else "not installed"
    if sys.platform == "win32":
        ...
```

(The test stubs `_run`, so `launchctl unload` of a not-yet-existing plist is fine; in production it's a harmless no-op before load.)

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_ctl_services.py -v`
Expected: PASS (existing linux/windows cases + new macOS cases).

- [ ] **Step 5: Commit**

```bash
git add buddybridge/ctl/services.py tests/test_ctl_services.py
git commit -m "feat(ctl): macOS launchd LaunchAgent service path"
```

---

### Task C4: Hub install drops `--relay-port`

**Files:**
- Modify: `buddybridge/ctl/__init__.py` — `_hub_install` (53-64), hub subparser (132-140)

- [ ] **Step 1: Confirm current exec line has no relay-port**

Run: `grep -n "relay-port\|relay_port" buddybridge/ctl/__init__.py`
Expected: no matches (hub install never passed it — nothing to change there). If matches appear, delete those tokens from `exec_cmd`.

- [ ] **Step 2: No-op verification of hub install**

Run: `pytest tests/test_ctl_cli.py -v`
Expected: PASS. (Task kept as an explicit checkpoint; `--relay-port` lived only in `hub.py`'s argparse, already removed in Task A4.)

- [ ] **Step 3: Commit (if anything changed)**

```bash
git add buddybridge/ctl/__init__.py
git commit -m "chore(ctl): confirm hub install carries no relay-port" || echo "nothing to commit"
```

---

## Phase D — Android: relay-only mode

> No Kotlin test harness exists in this repo; Android tasks are verified by `./gradlew assembleDebug` (JDK 17 + Android SDK). Each task ends by building.

### Task D1: Settings — mode + remote hub URL

**Files:**
- Modify: `android/app/src/main/java/com/claudebuddy/bridge/data/Settings.kt`

- [ ] **Step 1: Add keys + flows + setters**

In `SettingsKeys` add:

```kotlin
    val MODE = stringPreferencesKey("mode")                 // "serve_hub" | "relay"
    val REMOTE_HUB_URL = stringPreferencesKey("remote_hub_url")
```

In `SettingsRepository` add:

```kotlin
    val mode: Flow<String> = context.dataStore.data.map { it[SettingsKeys.MODE] ?: "serve_hub" }
    val remoteHubUrl: Flow<String> = context.dataStore.data.map { it[SettingsKeys.REMOTE_HUB_URL] ?: "" }

    suspend fun setMode(mode: String) {
        context.dataStore.edit { it[SettingsKeys.MODE] = mode }
    }
    suspend fun setRemoteHubUrl(url: String) {
        context.dataStore.edit { it[SettingsKeys.REMOTE_HUB_URL] = url }
    }
```

- [ ] **Step 2: Build**

Run: `cd android && ./gradlew assembleDebug`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add android/app/src/main/java/com/claudebuddy/bridge/data/Settings.kt
git commit -m "feat(android): mode + remote hub URL settings"
```

---

### Task D2: `RelayClient.kt` — outbound stream consumer + button POST

**Files:**
- Create: `android/app/src/main/java/com/claudebuddy/bridge/relay/RelayClient.kt`

Mirror `relay.py`: open `GET {hub}/relay/stream` (token header), read newline-JSON, hand each line to a callback (the BLE writer); expose `postButton(id, decision)`.

- [ ] **Step 1: Create the file**

```kotlin
package com.claudebuddy.bridge.relay

import android.util.Log
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Outbound client of a remote buddyhub's relay stream — the phone-as-relay path.
 * Reads GET {hub}/relay/stream (chunked newline-JSON) and feeds each line to the
 * BLE writer; POSTs A/B presses back to {hub}/button. Mirrors relay.py.
 */
class RelayClient(
    private val hubUrl: String,
    private val token: String,
    private val onLine: (String) -> Unit,    // heartbeat line -> write to BLE
) {
    companion object { private const val TAG = "RelayClient" }

    private val base = hubUrl.trimEnd('/')
    @Volatile private var running = false
    private var job: Job? = null

    fun start(scope: CoroutineScope) {
        running = true
        job = scope.launch(Dispatchers.IO) {
            while (running) {
                try { streamOnce() }
                catch (e: Exception) { Log.i(TAG, "stream error: ${e.message}") }
                if (running) delay(5000)     // supervise: reconnect with backoff
            }
        }
    }

    fun stop() { running = false; job?.cancel() }

    private fun streamOnce() {
        val conn = (URL("$base/relay/stream").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 10_000
            readTimeout = 0                  // infinite — it's a long-lived stream
            if (token.isNotEmpty()) setRequestProperty("X-Buddy-Token", token)
        }
        try {
            if (conn.responseCode != 200) { Log.i(TAG, "stream HTTP ${conn.responseCode}"); return }
            BufferedReader(InputStreamReader(conn.inputStream)).use { r ->
                while (running) {
                    val line = r.readLine() ?: break
                    if (line.isNotBlank()) onLine(line)
                }
            }
        } finally { conn.disconnect() }
    }

    /** Device pressed A/B — relay the decision to the hub. Call off the main thread. */
    fun postButton(id: String, decision: String) {
        try {
            val conn = (URL("$base/button").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 5_000; readTimeout = 5_000
                setRequestProperty("Content-Type", "application/json")
                if (token.isNotEmpty()) setRequestProperty("X-Buddy-Token", token)
            }
            val body = JSONObject().put("id", id).put("decision", decision).toString()
            conn.outputStream.use { it.write(body.toByteArray()) }
            conn.inputStream.use { it.readBytes() }
            conn.disconnect()
        } catch (e: Exception) { Log.i(TAG, "button POST failed: ${e.message}") }
    }
}
```

- [ ] **Step 2: Build**

Run: `cd android && ./gradlew assembleDebug`
Expected: BUILD SUCCESSFUL

- [ ] **Step 3: Commit**

```bash
git add android/app/src/main/java/com/claudebuddy/bridge/relay/RelayClient.kt
git commit -m "feat(android): RelayClient — outbound /relay/stream consumer"
```

---

### Task D3: `BuddyService` branches on mode

**Files:**
- Modify: `android/app/src/main/java/com/claudebuddy/bridge/service/BuddyService.kt`

In **relay** mode the service starts BLE + a `RelayClient` and no Hub/HttpServer. Device lines POST to the remote hub instead of resolving a local hub. The wiring already isolates this: `startBridge()` builds the three components — split it.

- [ ] **Step 1: Add mode fields**

After `var buddyToken` (line 45-49) add:

```kotlin
    // "serve_hub" (embedded hub + BLE) or "relay" (BLE + outbound RelayClient)
    var mode: String = "serve_hub"
    var remoteHubUrl: String = ""
    private var relayClient: com.claudebuddy.bridge.relay.RelayClient? = null
```

- [ ] **Step 2: Branch `startBridge()`**

Replace `startBridge()` with:

```kotlin
    private fun startBridge() {
        if (bleManager != null) return  // already running

        val ble = BleManager(this, namePrefix = "Claude",
            onLine = { line -> handleDeviceLine(line) })
        ble.onConnected = { onBleConnected() }
        bleManager = ble

        if (mode == "relay") {
            val rc = com.claudebuddy.bridge.relay.RelayClient(
                hubUrl = remoteHubUrl, token = buddyToken,
                onLine = { line -> bleManager?.sendJson(line) })
            relayClient = rc
            ble.start(scope)
            rc.start(scope)
            Log.i(TAG, "bridge started (relay -> $remoteHubUrl)")
            return
        }

        val h = Hub { hb -> sendHeartbeat(hb) }
        hub = h
        val http = BuddyHttpServer(h, 8787).also { it.token = buddyToken }
        httpServer = http
        try {
            http.start(); _httpRunning.value = true
            Log.i(TAG, "HTTP server listening on 0.0.0.0:8787")
        } catch (e: Exception) { Log.e(TAG, "HTTP server failed: ${e.message}") }
        ble.start(scope)
        h.startHeartbeatLoop(scope)
        Log.i(TAG, "bridge started (serve_hub)")
    }
```

- [ ] **Step 3: Route device lines by mode**

Replace `handleDeviceLine`:

```kotlin
    private fun handleDeviceLine(line: String) {
        try {
            val json = JSONObject(line)
            if (json.optString("cmd") == "permission") {
                val pid = json.optString("id", "")
                val decision = json.optString("decision", "deny")
                val rc = relayClient
                if (rc != null) {
                    scope.launch(Dispatchers.IO) { rc.postButton(pid, decision) }
                } else {
                    scope.launch {
                        val ok = hub?.resolve(pid, decision) ?: false
                        Log.i(TAG, "device decision $decision for $pid -> ${if (ok) "ok" else "stale"}")
                    }
                }
            }
        } catch (e: Exception) { Log.w(TAG, "bad device line: $line") }
    }
```

- [ ] **Step 4: Tear down the relay client**

In `onDestroy()` add before `bleManager?.stop()`:

```kotlin
        relayClient?.stop(); relayClient = null
```

- [ ] **Step 5: Build**

Run: `cd android && ./gradlew assembleDebug`
Expected: BUILD SUCCESSFUL

- [ ] **Step 6: Commit**

```bash
git add android/app/src/main/java/com/claudebuddy/bridge/service/BuddyService.kt
git commit -m "feat(android): BuddyService relay-to-remote-hub mode"
```

---

### Task D4: UI — mode toggle + remote hub URL field

**Files:**
- Modify: `android/app/src/main/java/com/claudebuddy/bridge/ui/BridgeScreen.kt`
- Modify: `android/app/src/main/java/com/claudebuddy/bridge/MainActivity.kt` (wire new params from Settings into the service — read its current pattern and mirror owner/token plumbing)

- [ ] **Step 1: Read MainActivity to follow the existing plumbing pattern**

Run: `sed -n '1,200p' android/app/src/main/java/com/claudebuddy/bridge/MainActivity.kt`
Expected: shows how `ownerName`/`buddyToken` flow from `SettingsRepository` → `BridgeScreen` params → `service.ownerName`/`buddyToken`. Mirror that exactly for `mode` and `remoteHubUrl`.

- [ ] **Step 2: Add the toggle + URL field to `BridgeScreen`**

Extend the signature:

```kotlin
    mode: String = "serve_hub",
    onModeChange: (String) -> Unit = {},
    remoteHubUrl: String = "",
    onRemoteHubUrlChange: (String) -> Unit = {},
```

After the token field, add (before the Start/Stop toggle), using existing Material3 imports:

```kotlin
        Spacer(modifier = Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Relay to remote hub", color = MaterialTheme.colorScheme.onBackground)
            Spacer(modifier = Modifier.width(12.dp))
            Switch(
                checked = mode == "relay",
                enabled = !isRunning,
                onCheckedChange = { onModeChange(if (it) "relay" else "serve_hub") }
            )
        }
        if (mode == "relay") {
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(
                value = remoteHubUrl,
                onValueChange = onRemoteHubUrlChange,
                enabled = !isRunning,
                singleLine = true,
                label = { Text("Hub URL (https://buddy.example.com)") },
                modifier = Modifier.fillMaxWidth()
            )
        }
```

- [ ] **Step 3: Wire MainActivity → service**

In MainActivity, collect `settings.mode` and `settings.remoteHubUrl` (mirroring `ownerName`/`buddyToken`), pass them and their setters into `BridgeScreen`, and set `service.mode` / `service.remoteHubUrl` before `startService`/`startBridge` (exactly where `ownerName`/`buddyToken` are set today).

- [ ] **Step 4: Build**

Run: `cd android && ./gradlew assembleDebug`
Expected: BUILD SUCCESSFUL

- [ ] **Step 5: Commit**

```bash
git add android/app/src/main/java/com/claudebuddy/bridge/ui/BridgeScreen.kt \
        android/app/src/main/java/com/claudebuddy/bridge/MainActivity.kt
git commit -m "feat(android): UI mode toggle + remote hub URL"
```

---

## Phase E — Docs

### Task E1: README — single-URL model, Traefik, macOS, phone relay-only

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite the topology + install sections**

- Replace the ASCII topology block (the `server A/B/C ──HTTP :8787──► hub ──BLE──► stick`) with the proposed before/after from the spec, emphasizing one URL + outbound clients.
- **Install:** keep the two `pipx` lines. Recipe 1 unchanged. **Recipe 2** stays (`buddyctl client install --hub https://buddy.<you>.<co>.<tld> --token …`). **Delete Recipe 3 (tunnels)** entirely.
- Add a **Deploying the hub behind Traefik** subsection: a Docker/Traefik label snippet routing `buddy.<you>.<co>.<tld>` → the hub container/port `8787`, TLS via your resolver; note the bare `--hub http://host:8787 --token …` path for no-proxy/Tailscale.
- **`buddyctl` reference:** delete the `tunnel` line; note relay `--hub` is a URL now.
- **macOS clients:** add a short note that `buddyctl client install` registers a `launchd` LaunchAgent (same one-liner as Linux).
- **Android section:** document the **mode toggle** — "Serve hub here" (all-in-one) vs **"Relay to remote hub"** (enter the hub URL + token; phone drives BLE, no inbound needed — works on cellular). Replace the "point your machines at the phone over Tailscale" guidance with "point the phone at your hub URL."
- Remove the **Windows clients** `.cmd` note's reliance on hand-set env vars if it conflicts (leave `buddy.cmd`/`buddy-hook.cmd` mention, but point at config-file precedence).

- [ ] **Step 2: Verify no stale tunnel references remain**

Run: `grep -n "tunnel\|:8790\|relay-port\|reverse" README.md`
Expected: no matches (or only unrelated prose).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: single-URL hub model, Traefik deploy, macOS, phone relay-only"
```

---

## Final verification

- [ ] **Run the whole Python suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Build the APK**

Run: `cd android && ./gradlew assembleDebug`
Expected: BUILD SUCCESSFUL; APK at `android/app/build/outputs/apk/debug/app-debug.apk`.

- [ ] **Smoke test the loop locally (mock-free, real HTTP)**

Run the hub with the relay transport and confirm a client can stream + a button resolves:

```bash
python -m buddybridge.hub --transport relay --owner you --port 8787 &
python - <<'PY'
import json, urllib.request, threading, time
base="http://127.0.0.1:8787"
s=urllib.request.urlopen(base+"/relay/stream", timeout=3)
print("stream open:", json.loads(s.readline()))      # time frame
pid=json.loads(urllib.request.urlopen(urllib.request.Request(
    base+"/permission", data=json.dumps({"machine":"m","session":"x","tool":"Bash","hint":"ls"}).encode(),
    headers={"Content-Type":"application/json"}, method="POST")).read())["id"]
print("permission:", pid)
urllib.request.urlopen(urllib.request.Request(base+"/button",
    data=json.dumps({"id":pid,"decision":"once"}).encode(),
    headers={"Content-Type":"application/json"}, method="POST")).read()
print("decision:", json.loads(urllib.request.urlopen(base+f"/decision?id={pid}&wait=2", timeout=3).read()))
PY
kill %1
```

Expected: prints a `time` frame, a `pid`, then `decision: {'decision': 'once'}`.
