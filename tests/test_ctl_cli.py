import json

import pytest

from buddybridge import config, ctl


def test_help_lists_roles(capsys):
    with pytest.raises(SystemExit):
        ctl.main(["--help"])
    out = capsys.readouterr().out
    for word in ("client", "hub", "relay", "status"):
        assert word in out


def test_client_install_writes_config_and_hooks(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    sp = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(ctl, "_claude_settings_path", lambda: sp)
    ctl.main(["client", "install", "--hub", "http://hub:8787", "--name", "wk"])
    assert config.load_config() == {"hub": "http://hub:8787", "machine": "wk"}
    data = json.loads(sp.read_text())
    cmd = data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert "-m buddybridge.hook" in cmd and "BUDDY_HUB=" not in cmd  # no POSIX env-prefix


def test_status_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(ctl, "_claude_settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr("buddybridge.ctl.services.status", lambda name: "active")
    ctl.main(["status"])
    out = capsys.readouterr().out
    assert "buddyhub" in out and "buddy-relay" in out and "client hooks" in out
