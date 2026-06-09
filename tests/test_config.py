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
