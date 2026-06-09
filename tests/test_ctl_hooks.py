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
