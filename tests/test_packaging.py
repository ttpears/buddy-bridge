import importlib
import shutil
import subprocess

from importlib.resources import files


def test_package_imports_and_has_version():
    pkg = importlib.import_module("buddybridge")
    assert hasattr(pkg, "__version__")
    assert isinstance(pkg.__version__, str)


def test_hub_module_exposes_main():
    hub = importlib.import_module("buddybridge.hub")
    assert callable(hub.main)
    assert callable(getattr(hub, "make_handler"))


def test_character_assets_packaged():
    base = files("buddybridge.resources") / "characters" / "tty"
    assert (base / "manifest.json").is_file()
    assert (base / "sleep.gif").is_file()


def test_runnable_modules_expose_main():
    for name in ("buddybridge.relay", "buddybridge.hook", "buddybridge.launcher",
                 "buddybridge.winapp", "buddybridge.tray"):
        mod = importlib.import_module(name)
        assert callable(mod.main), f"{name}.main missing"


def test_relay_module_imports_without_bleak(monkeypatch):
    # bleak is the optional [relay] extra; importing the module must not require it.
    import sys
    monkeypatch.setitem(sys.modules, "bleak", None)  # makes `import bleak` raise
    mod = importlib.reload(importlib.import_module("buddybridge.relay"))
    assert callable(mod.main)


def test_launcher_sets_control_env(monkeypatch):
    import buddybridge.launcher as launcher
    captured = {}
    monkeypatch.setattr(launcher.os, "execvpe",
                        lambda file, args, env: captured.update(file=file, args=args, env=env))
    launcher.main(["--model", "opus"])
    assert captured["env"].get("BUDDY_CONTROL") == "1"
    assert captured["args"][0] == "claude"
    assert captured["args"][-2:] == ["--model", "opus"]


def test_entry_point_scripts_resolve():
    # After `pip install -e .` these console scripts must exist on PATH.
    for script in ("buddyctl", "buddyhub", "buddy-relay", "buddy", "buddy-tray", "build-tty"):
        assert shutil.which(script), f"{script} not on PATH (did `pip install -e .` run?)"


def test_buddyhub_help_runs():
    out = subprocess.run(["buddyhub", "--help"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert "--transport" in out.stdout
