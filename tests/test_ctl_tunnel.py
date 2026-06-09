from buddybridge import config, ctl
from buddybridge.ctl import tunnel


def test_forward_tunnel_cmd():
    c = tunnel.forward_tunnel_cmd("myhub", 8787)
    assert c.startswith("ssh -N ") and "-L 8787:localhost:8787" in c and c.endswith("myhub")


def test_reverse_tunnel_cmd():
    assert "-R 8787:localhost:8787" in tunnel.reverse_tunnel_cmd("client")


def test_tunnel_install_registers_reverse(monkeypatch):
    reg = []
    monkeypatch.setattr("buddybridge.ctl.services.register",
                        lambda name, cmd, desc: reg.append((name, cmd)))
    ctl.main(["tunnel", "install", "--to", "workpc"])
    assert any(name == "buddy-tunnel" and "-R 8787:localhost:8787" in cmd for name, cmd in reg)


def test_client_install_with_tunnel_registers_service_and_localhost_hub(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(ctl, "_claude_settings_path", lambda: tmp_path / "settings.json")
    reg = []
    monkeypatch.setattr("buddybridge.ctl.services.register",
                        lambda name, cmd, desc: reg.append((name, cmd)))
    ctl.main(["client", "install", "--tunnel", "myhub", "--name", "wk"])
    assert config.load_config()["hub"] == "http://127.0.0.1:8787"
    assert any(name == "buddy-tunnel" and "-L 8787:localhost:8787" in cmd for name, cmd in reg)
