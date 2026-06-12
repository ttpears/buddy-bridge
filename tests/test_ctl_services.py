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


def test_launchd_plist_has_label_and_program():
    p = services.launchd_plist("com.claudebuddy.buddyhub",
                               "/usr/bin/python3 -m buddybridge.hub --port 8787")
    assert "<string>com.claudebuddy.buddyhub</string>" in p
    assert "buddybridge.hub" in p and "<key>RunAtLoad</key>" in p
    assert "<key>KeepAlive</key>" in p


def test_register_macos_writes_plist_and_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(services.sys, "platform", "darwin")
    monkeypatch.setattr(services, "_launchd_dir", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(services, "_run", lambda cmd: calls.append(cmd))
    services.register("buddyhub", "python3 -m buddybridge.hub", "Buddy Hub")
    plist = (tmp_path / "com.claudebuddy.buddyhub.plist")
    assert plist.exists() and "buddybridge.hub" in plist.read_text()
    assert any("bootstrap" in c or "load" in c for c in (" ".join(map(str, x)) for x in calls))
