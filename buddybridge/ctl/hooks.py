"""Install/remove the buddy hooks in a Claude Code settings.json.

Replaces install_hooks.py. The baked command is `"<python>" -m buddybridge.hook`
with no POSIX env-prefix, so it runs on Windows cmd too; hub/machine come from
buddybridge.config (written by `buddyctl client install`).
"""
import json
import sys
from pathlib import Path

AMBIENT = ["SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"]


def _entries(command):
    return {
        "PermissionRequest": {"matcher": "Bash|Edit|Write|NotebookEdit",
                              "hooks": [{"type": "command", "command": command, "timeout": 60}]},
        "PostToolUse": {"matcher": "*",
                        "hooks": [{"type": "command", "command": command, "timeout": 5}]},
        **{e: {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
           for e in AMBIENT},
    }


def _is_buddy(entry):
    return any(("buddybridge.hook" in h.get("command", "")) or
               ("buddy-hook.py" in h.get("command", ""))
               for h in entry.get("hooks", []))


def _load(path):
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _strip_buddy(hooks, keep_events):
    """Remove buddy entries from every event; drop now-empty arrays we don't own."""
    for event in list(hooks.keys()):
        hooks[event][:] = [e for e in hooks[event] if not _is_buddy(e)]
        if not hooks[event] and event not in keep_events:
            del hooks[event]


def install(settings_path, python=None):
    """Idempotently merge buddy hooks; preserves any non-buddy hooks. Returns the command."""
    command = f'"{python or sys.executable}" -m buddybridge.hook'
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    entries = _entries(command)
    _strip_buddy(hooks, keep_events=set(entries))
    for event, entry in entries.items():
        hooks.setdefault(event, []).append(entry)
    _save(settings_path, data)
    return command


def remove(settings_path):
    """Strip only buddy entries, preserving everything else."""
    data = _load(settings_path)
    hooks = data.get("hooks", {})
    _strip_buddy(hooks, keep_events=set())
    if not hooks:
        data.pop("hooks", None)
    _save(settings_path, data)
