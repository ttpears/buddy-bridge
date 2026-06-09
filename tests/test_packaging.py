import importlib

from importlib.resources import files


def test_package_imports_and_has_version():
    pkg = importlib.import_module("buddybridge")
    assert hasattr(pkg, "__version__")
    assert isinstance(pkg.__version__, str)


def test_hub_module_exposes_main():
    hub = importlib.import_module("buddybridge.hub")
    assert callable(hub.main)
    assert callable(getattr(hub, "make_handler"))


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
