#!/usr/bin/env python3
"""
buddy-hook — per-machine Claude Code hook agent for the buddy bridge.

One script, wired into several hook events in ~/.claude/settings.json. It reads
the hook JSON on stdin, derives a session event, and reports it to buddyhub.

For PreToolUse it implements the CONTROL path: register a permission with the
hub, long-poll for the device's A/B decision, then emit the PreToolUse
permission-decision JSON. If the hub is unreachable or no one answers in time,
it stays silent so Claude Code falls back to its normal interactive prompt —
a dead bridge must never block you.

Config (env):
  BUDDY_HUB      hub base URL          (default http://127.0.0.1:8787)
  BUDDY_MACHINE  name shown on device  (default: hostname)
  BUDDY_TOKEN    shared secret for hub auth (optional, must match hub/app)

Wire it up (per event) as:
  {"type":"command","command":"python3 /path/buddy-hook.py","timeout":60}
"""
import json
import os
import socket
import sys
import urllib.request

HUB = os.environ.get("BUDDY_HUB", "http://127.0.0.1:8787").rstrip("/")
MACHINE = os.environ.get("BUDDY_MACHINE") or socket.gethostname().split(".")[0]
TOKEN = os.environ.get("BUDDY_TOKEN", "")

# how long the PreToolUse hook waits for a device decision before falling back
DECISION_WAIT = int(os.environ.get("BUDDY_DECISION_WAIT", "30"))
QUICK = 2.0          # connect/read timeout for fire-and-forget events


def post(path, payload, timeout):
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Buddy-Token"] = TOKEN
    req = urllib.request.Request(HUB + path,
                                 data=json.dumps(payload).encode(),
                                 headers=headers,
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def get(path, timeout):
    with urllib.request.urlopen(HUB + path, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def count_tokens(transcript_path):
    """Sum input+output tokens from the session transcript file."""
    if not transcript_path:
        return None
    try:
        total = 0
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                try:
                    u = json.loads(line).get("message", {}).get("usage", {})
                    total += u.get("input_tokens", 0) + u.get("output_tokens", 0)
                except (json.JSONDecodeError, AttributeError):
                    pass
        return total or None
    except OSError:
        return None


def fire(kind, session, msg=None, tokens=None):
    """Best-effort session event; never raises."""
    try:
        post("/event", {"machine": MACHINE, "session": session,
                        "kind": kind, "msg": msg, "tokens": tokens}, QUICK)
    except Exception:
        pass


def hint_for(tool, tool_input):
    """A short, screen-friendly summary of what's being approved."""
    if not isinstance(tool_input, dict):
        return tool or ""
    if tool == "Bash":
        return (tool_input.get("command") or "")[:80]
    for k in ("file_path", "path", "url", "pattern", "command", "query"):
        if k in tool_input:
            return f"{tool_input[k]}"[:80]
    return tool or ""


def snip(s, n=52):
    """Collapse whitespace and trim to a small-screen-friendly snippet."""
    s = " ".join((s or "").split())
    return (s[:n - 1] + "…") if len(s) > n else s


def tool_label(tool, tool_input):
    """A compact 'what just happened' line for the activity feed."""
    h = hint_for(tool, tool_input)
    if tool == "Bash":
        return snip("$ " + h)
    if tool in ("Edit", "Write", "Read", "NotebookEdit") and h:
        return snip(f"{tool} {os.path.basename(h)}")
    return snip(f"{tool} {h}".strip()) if h else snip(tool)


def emit_decision(event, behavior, reason="via buddy"):
    """Emit the approve/deny JSON and exit 0. PreToolUse and PermissionRequest
    use different output shapes; pick by event."""
    if event == "PermissionRequest":
        out = {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": behavior},       # allow | deny
        }}
    else:  # PreToolUse
        out = {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": behavior,           # allow | deny | ask
            "permissionDecisionReason": reason,
        }}
    print(json.dumps(out))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)                               # malformed: do nothing

    evt = data.get("hook_event_name", "")
    session = data.get("session_id", "?")
    transcript = data.get("transcript_path")

    if evt == "SessionStart":
        fire("session_start", session)
    elif evt == "SessionEnd":
        fire("session_end", session)
    elif evt == "UserPromptSubmit":
        fire("running", session, snip(data.get("prompt") or "") or "thinking…",
             tokens=count_tokens(transcript))
    elif evt == "Stop":
        fire("idle", session, tokens=count_tokens(transcript))
    elif evt == "PostToolUse":
        fire("tool_done", session, tool_label(data.get("tool_name", ""), data.get("tool_input")),
             tokens=count_tokens(transcript))
    elif evt in ("PermissionRequest", "PreToolUse"):
        # ---- the control path (opt-in per session) ----
        # PermissionRequest fires ONLY on genuine prompts (preferred wiring);
        # PreToolUse is still handled for back-compat if wired.
        if os.environ.get("BUDDY_CONTROL") != "1":
            sys.exit(0)                           # not opted in: normal prompt
        tool = data.get("tool_name", "?")
        hint = hint_for(tool, data.get("tool_input"))
        try:
            r = post("/permission", {"machine": MACHINE, "session": session,
                                     "tool": tool, "hint": hint}, QUICK)
            pid = r.get("id")
            if not pid:
                sys.exit(0)                       # hub odd: fall back to prompt
            d = get(f"/decision?id={pid}&wait={DECISION_WAIT}", DECISION_WAIT + 5).get("decision")
        except Exception:
            sys.exit(0)                           # hub down: normal prompt
        if d == "once":
            emit_decision(evt, "allow")
        elif d == "deny":
            emit_decision(evt, "deny")
        else:
            sys.exit(0)                           # timeout: normal prompt

    sys.exit(0)


if __name__ == "__main__":
    main()
