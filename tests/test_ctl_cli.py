import json
import subprocess
import sys

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


def test_relay_main_accepts_argv():
    from buddybridge import relay
    with pytest.raises(SystemExit):   # --help exits 0; argv is honored, not sys.argv
        relay.main(["--help"])


def test_ctl_runnable_as_module():
    out = subprocess.run([sys.executable, "-m", "buddybridge.ctl", "--help"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "client" in out.stdout


def test_relay_install_uses_hub_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    reg = []
    monkeypatch.setattr("buddybridge.ctl.services.register",
                        lambda name, cmd, desc: reg.append((name, cmd)))
    ctl.main(["relay", "install", "--hub", "https://buddy.x.com"])
    assert any(name == "buddy-relay" and "--hub https://buddy.x.com" in cmd
               for name, cmd in reg)
