#!/usr/bin/env python3
"""
Idempotently merge buddy-bridge hooks into a Claude Code settings.json.

  python3 install_hooks.py <settings.json> <machine> <hub_url> <hook_path>

Preserves all existing settings and any non-buddy hooks. Re-running updates the
buddy entries in place (matched by the buddy-hook.py path in the command).
"""
import json
import os
import sys

settings_path, machine, hub_url, hook_path = sys.argv[1:5]

cmd = f"BUDDY_HUB={hub_url} BUDDY_MACHINE={machine} python3 {hook_path}"
AMBIENT = ["SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"]
ENTRIES = {
    # control via PermissionRequest: fires ONLY on genuine prompts, so
    # auto-approved tools are never needlessly routed to the stick.
    "PermissionRequest": {"matcher": "Bash|Edit|Write|NotebookEdit",
                          "hooks": [{"type": "command", "command": cmd, "timeout": 60}]},
    # activity feed: every completed tool becomes a small snippet on the device
    "PostToolUse": {"matcher": "*",
                    "hooks": [{"type": "command", "command": cmd, "timeout": 5}]},
    **{e: {"hooks": [{"type": "command", "command": cmd, "timeout": 5}]} for e in AMBIENT},
}

data = {}
if os.path.exists(settings_path):
    with open(settings_path) as f:
        data = json.load(f)
hooks = data.setdefault("hooks", {})

def is_buddy(entry):
    return any("buddy-hook.py" in h.get("command", "")
               for h in entry.get("hooks", []))

# migration: strip buddy entries from EVERY event (e.g. an old PreToolUse one),
# preserving non-buddy hooks; drop arrays that become empty and aren't ours
for event in list(hooks.keys()):
    hooks[event][:] = [e for e in hooks[event] if not is_buddy(e)]
    if not hooks[event] and event not in ENTRIES:
        del hooks[event]

for event, entry in ENTRIES.items():
    hooks.setdefault(event, []).append(entry)

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"merged buddy hooks into {settings_path}  (machine={machine}, hub={hub_url})")
print("events:", ", ".join(["PermissionRequest", "PostToolUse"] + AMBIENT))
