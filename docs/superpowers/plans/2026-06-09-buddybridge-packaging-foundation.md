# buddybridge Packaging Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the flat buddy-bridge scripts into a pip/pipx-installable `buddybridge` Python package with console entry points, without breaking the live WSL hub.

**Architecture:** Move the runnable scripts into a `buddybridge/` package, each exposing a `main()`. Bundle `dashboard.html` and `characters/` as package data loaded via `importlib.resources`. Add a `pyproject.toml` with entry points (`buddyhub`, `buddy-relay`, `buddy`, `build-tty`) and a `[relay]` extra for `bleak`. Keep thin root-level shims (`buddyhub.py`, `relay.py`, etc.) that import the package, so the currently-running `buddyhub.service` (which references the root path) keeps working until `buddyctl` re-registers it in Plan 2.

**Tech Stack:** Python 3.9+ stdlib, `importlib.resources`, `pyproject.toml` (setuptools build backend), `bleak` (relay extra only), `pytest` for tests, `pipx` for install verification.

---

## File Structure

Created:
- `buddybridge/__init__.py` — package marker + version
- `buddybridge/hub.py` — moved from `buddyhub.py` (the `Hub`, transports, HTTP server, `main()`)
- `buddybridge/hook.py` — moved from `buddy-hook.py`
- `buddybridge/relay.py` — moved from `relay.py`
- `buddybridge/launcher.py` — the `buddy` launcher as a Python entry point
- `buddybridge/build_tty.py` — moved from `build_tty.py`
- `buddybridge/resources/__init__.py` — marks the resources subpackage
- `buddybridge/resources/dashboard.html` — moved from `dashboard.html`
- `buddybridge/resources/characters/tty/*` — moved from `characters/tty/`
- `pyproject.toml` — package metadata + entry points + `[relay]` extra
- `tests/test_packaging.py` — import + entry-point + resource-loading tests
- `tests/test_hub_dashboard.py` — hub serves the bundled dashboard

Modified / replaced with shims (kept at repo root for backward-compat):
- `buddyhub.py` → shim: `from buddybridge.hub import main; main()`
- `relay.py` → shim: `from buddybridge.relay import main; main()`
- `buddy-hook.py` → shim: `from buddybridge.hook import main; main()`
- `requirements.txt` → note it now mirrors `pyproject` extras

Untouched in this plan: `install_hooks.py`, `manage.ps1`, `systemd/`, `buddy` (shell), `dashboard.html` reference in README (Plan 3 rewrites docs).

---

### Task 1: Scaffold the package and move the hub module

**Files:**
- Create: `buddybridge/__init__.py`
- Create: `buddybridge/hub.py` (content moved verbatim from `buddyhub.py`)
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packaging.py
import importlib


def test_package_imports_and_has_version():
    pkg = importlib.import_module("buddybridge")
    assert hasattr(pkg, "__version__")
    assert isinstance(pkg.__version__, str)


def test_hub_module_exposes_main():
    hub = importlib.import_module("buddybridge.hub")
    assert callable(hub.main)
    assert callable(getattr(hub, "make_handler"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'buddybridge'`

- [ ] **Step 3: Create the package and move the hub**

Create `buddybridge/__init__.py`:

```python
"""buddybridge — Claude Code session bridge to the Hardware Buddy stick."""
__version__ = "0.1.0"
```

Move the hub: `git mv buddyhub.py buddybridge/hub.py`

Then edit the dashboard-loading block in `buddybridge/hub.py` to load packaged data (the `__file__`-relative path no longer points at `dashboard.html`). Replace:

```python
import os
_DASH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
try:
    with open(_DASH, encoding="utf-8") as _f:
        DASHBOARD_HTML = _f.read()
except OSError:
    DASHBOARD_HTML = "<!doctype html><title>Claude Buddy</title><body>dashboard.html missing</body>"
```

with:

```python
from importlib.resources import files
try:
    DASHBOARD_HTML = (files("buddybridge.resources") / "dashboard.html").read_text(encoding="utf-8")
except (OSError, ModuleNotFoundError):
    DASHBOARD_HTML = "<!doctype html><title>Claude Buddy</title><body>dashboard.html missing</body>"
```

(The resource file itself is added in Task 2; until then the fallback string is used, which is fine for this task's tests.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add buddybridge/__init__.py buddybridge/hub.py tests/test_packaging.py
git commit -m "refactor: move hub into buddybridge package; load dashboard as package data"
```

---

### Task 2: Bundle dashboard.html as package data and serve it

**Files:**
- Create: `buddybridge/resources/__init__.py`
- Create: `buddybridge/resources/dashboard.html` (moved from `dashboard.html`)
- Test: `tests/test_hub_dashboard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hub_dashboard.py
import importlib
from importlib.resources import files


def test_dashboard_resource_present_and_loaded():
    html = (files("buddybridge.resources") / "dashboard.html").read_text(encoding="utf-8")
    assert "CLAUDE" in html and "buddy" in html.lower()


def test_hub_module_uses_real_dashboard_not_fallback():
    hub = importlib.import_module("buddybridge.hub")
    importlib.reload(hub)
    assert "dashboard.html missing" not in hub.DASHBOARD_HTML
    assert "<!doctype html>" in hub.DASHBOARD_HTML.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hub_dashboard.py -v`
Expected: FAIL — resource not found / `DASHBOARD_HTML` is the fallback string

- [ ] **Step 3: Move the resource into the package**

```bash
mkdir -p buddybridge/resources
printf '"""Packaged static resources (dashboard, character GIFs)."""\n' > buddybridge/resources/__init__.py
git mv dashboard.html buddybridge/resources/dashboard.html
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_hub_dashboard.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add buddybridge/resources/__init__.py buddybridge/resources/dashboard.html tests/test_hub_dashboard.py
git commit -m "refactor: bundle dashboard.html as buddybridge package data"
```

---

### Task 3: Move relay, hook, launcher, and build_tty into the package

**Files:**
- Create: `buddybridge/relay.py` (moved from `relay.py`)
- Create: `buddybridge/hook.py` (moved from `buddy-hook.py`)
- Create: `buddybridge/build_tty.py` (moved from `build_tty.py`)
- Create: `buddybridge/launcher.py` (new)
- Modify: `buddybridge/build_tty.py` output path → package resources
- Test: `tests/test_packaging.py` (extend)

- [ ] **Step 1: Write the failing test (extend the packaging test)**

Append to `tests/test_packaging.py`:

```python
def test_runnable_modules_expose_main():
    for name in ("buddybridge.relay", "buddybridge.hook", "buddybridge.launcher"):
        mod = importlib.import_module(name)
        assert callable(mod.main), f"{name}.main missing"


def test_launcher_sets_control_env(monkeypatch):
    import buddybridge.launcher as launcher
    captured = {}
    monkeypatch.setattr(launcher.os, "execvpe",
                        lambda file, args, env: captured.update(file=file, args=args, env=env))
    launcher.main(["--model", "opus"])
    assert captured["env"].get("BUDDY_CONTROL") == "1"
    assert captured["args"][0] == "claude"
    assert captured["args"][-2:] == ["--model", "opus"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: FAIL — `buddybridge.relay` / `buddybridge.hook` / `buddybridge.launcher` not found

- [ ] **Step 3: Move modules and write the launcher**

```bash
git mv relay.py buddybridge/relay.py
git mv buddy-hook.py buddybridge/hook.py
git mv build_tty.py buddybridge/build_tty.py
```

`buddy-hook.py`'s `main()` already exists — no change. `relay.py`'s `main()` already exists — no change.

Edit `buddybridge/build_tty.py`: its `OUT` path used `__file__`-relative `characters/tty`. Change

```python
OUT = Path(__file__).resolve().parent / "characters" / "tty"
```

to write into the packaged resources dir:

```python
OUT = Path(__file__).resolve().parent / "resources" / "characters" / "tty"
```

Create `buddybridge/launcher.py`:

```python
#!/usr/bin/env python3
"""buddy launcher — run Claude Code with Hardware Buddy stick control enabled.

Sets BUDDY_CONTROL=1 so this session's permission prompts route to the stick
(and the web dashboard) for A/B approval. Plain `claude` stays ambient-only.
Cross-platform replacement for the buddy / buddy.cmd shell shims.
"""
import os
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ)
    env["BUDDY_CONTROL"] = "1"
    os.execvpe("claude", ["claude", *argv], env)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: PASS (all packaging tests)

- [ ] **Step 5: Commit**

```bash
git add buddybridge/relay.py buddybridge/hook.py buddybridge/build_tty.py buddybridge/launcher.py tests/test_packaging.py
git commit -m "refactor: move relay/hook/build_tty into package; add cross-platform buddy launcher"
```

---

### Task 4: Move character assets into package resources

**Files:**
- Move: `characters/tty/*` → `buddybridge/resources/characters/tty/*`
- Test: `tests/test_packaging.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
def test_character_assets_packaged():
    base = files("buddybridge.resources") / "characters" / "tty"
    assert (base / "manifest.json").is_file()
    assert (base / "sleep.gif").is_file()
```

Add the import at the top of `tests/test_packaging.py` if missing:

```python
from importlib.resources import files
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py::test_character_assets_packaged -v`
Expected: FAIL — manifest.json not under package resources

- [ ] **Step 3: Move the assets**

```bash
mkdir -p buddybridge/resources/characters
git mv characters/tty buddybridge/resources/characters/tty
rmdir characters 2>/dev/null || true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_packaging.py::test_character_assets_packaged -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move tty character assets into package resources"
```

---

### Task 5: Add pyproject.toml with entry points and the relay extra

**Files:**
- Create: `pyproject.toml`
- Test: `tests/test_packaging.py` (extend with an editable-install entry-point check)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
import shutil
import subprocess


def test_entry_point_scripts_resolve():
    # After `pip install -e .` these console scripts must exist on PATH.
    for script in ("buddyhub", "buddy-relay", "buddy", "build-tty"):
        assert shutil.which(script), f"{script} not on PATH (did `pip install -e .` run?)"


def test_buddyhub_help_runs():
    out = subprocess.run(["buddyhub", "--help"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert "--transport" in out.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py::test_entry_point_scripts_resolve -v`
Expected: FAIL — scripts not on PATH (no pyproject yet)

- [ ] **Step 3: Write pyproject.toml**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=64"]
build-backend = "setuptools.build_meta"

[project]
name = "buddy-bridge"
version = "0.1.0"
description = "Bridge Claude Code CLI sessions across machines to an M5Stick Hardware Buddy."
readme = "README.md"
requires-python = ">=3.9"
license = { text = "MIT" }
authors = [{ name = "ttpears" }]
dependencies = []

[project.optional-dependencies]
relay = ["bleak>=0.21"]
tty = ["Pillow>=10.0"]
dev = ["pytest>=7.0"]

[project.scripts]
buddyhub = "buddybridge.hub:main"
buddy-relay = "buddybridge.relay:main"
buddy = "buddybridge.launcher:main"
build-tty = "buddybridge.build_tty:main"

[tool.setuptools]
packages = ["buddybridge", "buddybridge.resources"]

[tool.setuptools.package-data]
"buddybridge.resources" = ["dashboard.html", "characters/tty/*"]
```

- [ ] **Step 4: Install editable and run the test**

Run:
```bash
pip install -e ".[dev]"
python -m pytest tests/test_packaging.py -v
```
Expected: PASS — all scripts resolve, `buddyhub --help` prints usage including `--transport`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "build: add pyproject with console entry points and [relay]/[tty]/[dev] extras"
```

---

### Task 6: Add backward-compat root shims so the live hub keeps working

**Files:**
- Create: `buddyhub.py` (shim)
- Create: `relay.py` (shim)
- Create: `buddy-hook.py` (shim)
- Test: `tests/test_shims.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shims.py
import subprocess
import sys


def test_root_buddyhub_shim_runs_help():
    out = subprocess.run([sys.executable, "buddyhub.py", "--help"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert "--transport" in out.stdout


def test_root_relay_shim_imports():
    # --help triggers argparse before any bleak BLE work; import must resolve.
    out = subprocess.run([sys.executable, "relay.py", "--help"],
                         capture_output=True, text=True, timeout=30)
    # Exit 0 if bleak present; non-zero ImportError is acceptable ONLY if it
    # names bleak, since bleak is an optional [relay] extra.
    assert out.returncode == 0 or "bleak" in (out.stderr + out.stdout)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_shims.py -v`
Expected: FAIL — root `buddyhub.py` was moved in Task 1; `python buddyhub.py` errors (file absent)

- [ ] **Step 3: Write the shims**

Create `buddyhub.py`:

```python
#!/usr/bin/env python3
"""Backward-compat shim. The hub now lives in buddybridge.hub.
Kept so an existing systemd unit pointing at this path keeps working until
`buddyctl hub install` re-registers it. Prefer the `buddyhub` console script.
"""
from buddybridge.hub import main

if __name__ == "__main__":
    main()
```

Create `relay.py`:

```python
#!/usr/bin/env python3
"""Backward-compat shim. The relay now lives in buddybridge.relay.
Prefer the `buddy-relay` console script.
"""
from buddybridge.relay import main

if __name__ == "__main__":
    main()
```

Create `buddy-hook.py`:

```python
#!/usr/bin/env python3
"""Backward-compat shim. The hook now lives in buddybridge.hook.
Existing ~/.claude/settings.json entries reference this path; keep it working
until `buddyctl client install` rewrites them.
"""
from buddybridge.hook import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_shims.py -v`
Expected: PASS

- [ ] **Step 5: Verify the live hub path still launches (manual smoke test)**

Run:
```bash
python buddyhub.py --help
```
Expected: usage text with `--port`, `--transport`, `--owner`. (The running `buddyhub.service` invokes this same path; the shim preserves it.)

- [ ] **Step 6: Commit**

```bash
git add buddyhub.py relay.py buddy-hook.py tests/test_shims.py
git commit -m "compat: root shims for buddyhub/relay/buddy-hook so live deployment keeps working"
```

---

### Task 7: Verify a clean pipx install end-to-end

**Files:**
- Test: manual verification (no new files)

- [ ] **Step 1: Build and install into an isolated pipx env**

Run:
```bash
pipx install --force ".[relay]"
```
Expected: installs `buddy-bridge` with `bleak`; reports the 4 entry-point scripts (`buddyhub`, `buddy-relay`, `buddy`, `build-tty`).

- [ ] **Step 2: Smoke-test the installed entry points**

Run:
```bash
buddyhub --help
build-tty --help || true
```
Expected: `buddyhub --help` prints usage. (Do NOT start a second hub on :8787 while the systemd one runs.)

- [ ] **Step 3: Confirm the running service is untouched**

Run:
```bash
systemctl --user is-active buddyhub.service
curl -s -m 3 http://127.0.0.1:8787/state | head -c 80
```
Expected: `active`, and a JSON `/state` snapshot — the live hub never went down during the refactor.

- [ ] **Step 4: Commit any final cleanup**

```bash
git add -A
git commit -m "build: verify pipx install + entry points; live hub unaffected" --allow-empty
```

---

## Self-Review

**Spec coverage (Plan 1 slice = packaging foundation):**
- Package restructure → Tasks 1–4. ✓
- `pyproject.toml` + entry points (`buddyhub`/`buddy-relay`/`buddy`/`build-tty`) → Task 5. ✓
- `bleak` as `[relay]` extra → Task 5. ✓
- Cross-platform `buddy` launcher (replaces shell `.cmd` juggling) → Task 3. ✓
- Live-hub safety (don't break `buddyhub.service`) → Task 6 shims + Task 7 verification. ✓
- `buddyctl` CLI, OS service registration, hook-install rewrite, `--tunnel`, docs rewrite → **deferred to Plans 2 and 3** (out of this slice by design).

**Placeholder scan:** No TBD/TODO; every code step has complete content. The only conditional is the relay shim test tolerating a `bleak`-named ImportError, which is intentional (optional extra) and explained inline.

**Type/name consistency:** `main()` is the entry symbol across `hub`, `relay`, `hook`, `launcher`, `build_tty`. Entry-point names (`buddyhub`, `buddy-relay`, `buddy`, `build-tty`) match between `pyproject.toml` (Task 5) and the tests (Tasks 5, 6). Resource package name `buddybridge.resources` is consistent across `hub.py` loader (Task 1), tests (Tasks 2, 4), and `package-data` (Task 5).

**Carry-forward note for Plan 2:** `install_hooks.py` still bakes `python3 <path>/buddy-hook.py`. Plan 2's `buddyctl client install` replaces that with an OS-correct invocation of the installed `buddybridge.hook` (entry point or `python -m buddybridge.hook`) and removes the root shims once nothing references them.
