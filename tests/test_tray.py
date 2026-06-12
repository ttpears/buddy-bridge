from buddybridge import config, tray
from buddybridge.ctl import hooks


def test_summarize_state():
    assert tray.summarize_state(None, reachable=False) == ("disconnected", "grey")
    assert tray.summarize_state({"total": 0, "waiting": 0})[0] == "no active sessions"
    assert tray.summarize_state({"total": 1, "waiting": 0}) == ("1 session", "green")
    assert tray.summarize_state({"total": 3, "waiting": 2}) == ("3 sessions · 2 waiting", "green")


def test_valid_hub_url():
    assert tray.valid_hub_url("https://buddy.example.com")
    assert tray.valid_hub_url("http://127.0.0.1:8787")
    assert not tray.valid_hub_url("ftp://x")
    assert not tray.valid_hub_url("not a url")
    assert not tray.valid_hub_url("")


def test_hooks_installed(monkeypatch, tmp_path):
    sp = tmp_path / "settings.json"
    monkeypatch.setattr(tray, "claude_settings_path", lambda: sp)
    assert tray.hooks_installed() is False
    hooks.install(str(sp), command=r'"C:\x\buddy.exe" hook')
    assert tray.hooks_installed() is True


def test_save_settings_and_pause(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    tray.save_settings("https://h.example.com/", "tok", "box")
    cfg = config.load_config()
    assert cfg["hub"] == "https://h.example.com"
    assert cfg["token"] == "tok"
    assert cfg["machine"] == "box"
    assert tray.is_paused() is False
    tray.set_paused(True)
    assert tray.is_paused() is True
