"""Per-machine buddy-bridge config (hub URL + display name).

Kept tiny and JSON so the hook can read it on every OS without the POSIX-only
`VAR=val cmd` env-prefix syntax that would have to be baked into Claude Code's
settings.json (and which fails silently on Windows cmd).
"""
import json
import os
import sys
from pathlib import Path

APP = "buddybridge"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(data: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
