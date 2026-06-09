from buddybridge.ctl import services


def test_systemd_unit_has_execstart_and_restart():
    u = services.systemd_unit("/usr/bin/python -m buddybridge.hub", "Buddy Hub")
    assert "ExecStart=/usr/bin/python -m buddybridge.hub" in u
    assert "Restart=always" in u and "[Install]" in u


def test_windows_cmd_launches_hidden():
    c = services.windows_cmd("pythonw -m buddybridge.relay")
    assert "buddybridge.relay" in c and "/min" in c.lower()


def test_register_linux_writes_unit_and_enables(tmp_path, monkeypatch):
    monkeypatch.setattr(services.sys, "platform", "linux")
    monkeypatch.setattr(services, "_systemd_dir", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(services, "_run", lambda cmd: calls.append(cmd))
    services.register("buddyhub", "python -m buddybridge.hub", "Buddy Hub")
    assert "buddybridge.hub" in (tmp_path / "buddyhub.service").read_text()
    assert ["systemctl", "--user", "enable", "--now", "buddyhub.service"] in calls


def test_register_windows_writes_startup_cmd(tmp_path, monkeypatch):
    monkeypatch.setattr(services.sys, "platform", "win32")
    monkeypatch.setattr(services, "_startup_dir", lambda: tmp_path)
    services.register("buddyhub", "pythonw -m buddybridge.hub", "Buddy Hub")
    assert (tmp_path / "buddyhub.cmd").read_text().count("buddybridge.hub") == 1
