# buddyctl CLI Implementation Plan (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A single cross-platform `buddyctl` command that installs/manages the hub, relay, and client roles, replacing `manage.ps1` + `install_hooks.py` with one Python codebase.

**Architecture:** New `buddybridge/ctl/` subpackage. A thin config file (`~/.config/buddybridge/config.json`, OS-appropriate) holds `{hub, machine}` so the hook command baked into `settings.json` is just `python3 -m buddybridge.hook` — no POSIX env-prefix, so it works on Windows `cmd` too. Service registration is OS-detected: Linux `systemd --user`, Windows a `.cmd` in the Startup folder.

**Tech Stack:** Python stdlib (argparse, json, pathlib, subprocess, platform), pytest. No new deps.

---

## Cross-platform decision (the keystone)

Today `install_hooks.py` bakes `BUDDY_HUB=url BUDDY_MACHINE=name python3 /path/buddy-hook.py`. The `VAR=val cmd` prefix is POSIX-shell only — on Windows `cmd` it fails silently. Fix:

- `buddyctl client install` writes **`config.json`** (`{ "hub": "...", "machine": "..." }`) into the platform config dir.
- `buddybridge.hook` reads that config, with precedence: **env var > config file > default** (env keeps back-compat for the existing live deployment).
- The hook command baked into `settings.json` becomes `"<python> -m buddybridge.hook"` (absolute `sys.executable`), identical on every OS.
- `BUDDY_CONTROL` stays an env var set by the `buddy` launcher at runtime (per-session), never baked.

## File Structure

Created:
- `buddybridge/config.py` — locate + read/write `config.json` (`platform_config_dir()`, `load_config()`, `save_config()`)
- `buddybridge/ctl/__init__.py` — `main()`: argparse subcommands + dispatch
- `buddybridge/ctl/hooks.py` — install/remove buddy hooks in `settings.json` (idempotent; baked command uses `-m buddybridge.hook`)
- `buddybridge/ctl/services.py` — OS-detected service register/unregister (Linux systemd `--user`; Windows Startup `.cmd`); pure text-builders + a thin apply layer
- `buddybridge/ctl/tunnel.py` — forward SSH tunnel as a service (Linux first; Windows later)
- `tests/test_config.py`, `tests/test_ctl_hooks.py`, `tests/test_ctl_services.py`, `tests/test_ctl_cli.py`

Modified:
- `buddybridge/hook.py` — read hub/machine via `buddybridge.config` (env override preserved)
- `pyproject.toml` — add `buddyctl = "buddybridge.ctl:main"`; add `buddybridge.ctl` to packages

Deleted at end (superseded): `install_hooks.py`, root `manage.ps1` (after parity reached; deferred to the last task).

---

### Task 1: config module

**Files:** Create `buddybridge/config.py`; Test `tests/test_config.py`

- [ ] **Step 1: failing test**

```python
# tests/test_config.py
import json
from buddybridge import config


def test_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    assert config.load_config() == {}
    config.save_config({"hub": "http://h:8787", "machine": "box"})
    assert config.load_config() == {"hub": "http://h:8787", "machine": "box"}
    assert json.loads((tmp_path / "config.json").read_text())["machine"] == "box"


def test_config_dir_is_platform_appropriate(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    p = config.config_path()
    assert p.name == "config.json" and "buddybridge" in str(p)
```

- [ ] **Step 2: run -> fail** (`python -m pytest tests/test_config.py -v`; ModuleNotFoundError)

- [ ] **Step 3: implement `buddybridge/config.py`**

```python
"""Per-machine buddy-bridge config (hub URL + display name).

Kept tiny and JSON so the hook can read it on every OS without POSIX-only
env-prefix syntax baked into Claude Code's settings.json.
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
```

- [ ] **Step 4: run -> pass.  Step 5: commit** `feat: add buddybridge.config (per-machine hub/name)`

---

### Task 2: hook reads config (env > config > default)

**Files:** Modify `buddybridge/hook.py`; Test `tests/test_ctl_hooks.py` (hook-config part)

- [ ] **Step 1: failing test**

```python
# tests/test_ctl_hooks.py
import importlib
from buddybridge import config


def test_hook_uses_config_then_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    config.save_config({"hub": "http://cfg:8787", "machine": "cfgbox"})
    monkeypatch.delenv("BUDDY_HUB", raising=False)
    monkeypatch.delenv("BUDDY_MACHINE", raising=False)
    hook = importlib.reload(importlib.import_module("buddybridge.hook"))
    assert hook.resolve_hub() == "http://cfg:8787"
    assert hook.resolve_machine() == "cfgbox"
    monkeypatch.setenv("BUDDY_HUB", "http://env:8787")
    assert hook.resolve_hub() == "http://env:8787"   # env wins
```

- [ ] **Step 2: run -> fail** (`resolve_hub` missing)

- [ ] **Step 3:** In `buddybridge/hook.py`, replace the module-level `HUB`/`MACHINE` constants with functions:

```python
from buddybridge import config as _config

def resolve_hub():
    env = os.environ.get("BUDDY_HUB")
    if env:
        return env.rstrip("/")
    return (_config.load_config().get("hub") or "http://127.0.0.1:8787").rstrip("/")

def resolve_machine():
    return (os.environ.get("BUDDY_MACHINE")
            or _config.load_config().get("machine")
            or socket.gethostname().split(".")[0])
```

Replace uses of `HUB`/`MACHINE` in `post`/`get`/`fire`/`main` with `resolve_hub()`/`resolve_machine()`.

- [ ] **Step 4: run -> pass (plus existing suite).  Step 5: commit** `feat: hook resolves hub/machine from config with env override`

---

### Task 3: ctl hooks install/remove (settings.json)

**Files:** Create `buddybridge/ctl/__init__.py` (stub), `buddybridge/ctl/hooks.py`; Test `tests/test_ctl_hooks.py` (extend)

- [ ] Test: installing into a temp settings.json produces PermissionRequest + PostToolUse + ambient entries whose command is `<python> -m buddybridge.hook`; re-running is idempotent; removing strips only buddy entries. (Port `install_hooks.py` logic; matcher `is_buddy` keyed on `buddybridge.hook` OR legacy `buddy-hook.py`.)
- [ ] Implement `hooks.install(settings_path, python=sys.executable)` and `hooks.remove(...)`. Baked command: `f'"{python}" -m buddybridge.hook'`.
- [ ] Commit `feat: ctl.hooks installs buddy hooks via -m buddybridge.hook (cross-platform)`

---

### Task 4: services (Linux systemd + Windows Startup .cmd) — pure builders first

**Files:** Create `buddybridge/ctl/services.py`; Test `tests/test_ctl_services.py`

- [ ] Test the **pure text builders** (no I/O): `systemd_unit(name, exec_cmd, description)` returns a `[Unit]/[Service]/[Install]` string with `ExecStart=` and `Restart=always`; `windows_cmd(exec_cmd)` returns a `.cmd` body launching hidden. Test OS dispatch via monkeypatched `sys.platform`.
- [ ] Implement builders + `register(name, exec_cmd, desc)` / `unregister(name)` that, on Linux, write `~/.config/systemd/user/<name>.service` + `systemctl --user daemon-reload && enable --now`; on Windows, write `<Startup>/<name>.cmd`. Subprocess calls isolated behind a `_run()` seam for tests.
- [ ] Commit `feat: ctl.services cross-OS register (systemd --user / Windows Startup)`

---

### Task 5: buddyctl CLI wiring

**Files:** Flesh out `buddybridge/ctl/__init__.py`; add `buddyctl` entry point; Test `tests/test_ctl_cli.py`

- [ ] Test: `buddyctl --help` lists `hub/relay/client/tunnel/status`; `client install --hub URL --name N` writes config + installs hooks (temp HOME); `status` prints role states; `--dry-run` prints actions without applying.
- [ ] Implement argparse subcommands dispatching to `hooks`/`services`/`config`/`tunnel`. `client install`: save_config + hooks.install + ensure `buddy` launcher note. `hub install`/`relay install`: services.register with the right exec_cmd (`python -m buddybridge.hub --transport relay ...` / `python -m buddybridge.relay ...`). `relay pair`: run relay once in foreground.
- [ ] Add to `pyproject.toml`: `buddyctl = "buddybridge.ctl:main"` and `buddybridge.ctl` package. Commit.

---

### Task 6: forward tunnel + retire install_hooks/manage.ps1

- [ ] `client install --tunnel SSH_HOST`: register a service running `ssh -N -L 8787:localhost:8787 SSH_HOST` and set config hub to `http://127.0.0.1:8787`. Test the command builder.
- [ ] Remove `install_hooks.py` and `manage.ps1` (superseded). Keep root shims until Plan 3 docs land. Commit.

---

## Self-Review checklist (run after build)
- env > config > default precedence covered (Task 2). Idempotent hook install (Task 3). OS dispatch tested via monkeypatch, not real systemctl (Task 4). `sys.executable` baked so the right interpreter runs the hook (Task 3/5). No POSIX env-prefix anywhere in baked commands.
