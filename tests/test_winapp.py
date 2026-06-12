from pathlib import Path

from buddybridge import winapp


def test_hook_command_exe_form():
    assert winapp.hook_command(exe=r"C:\x\buddy.exe") == r'"C:\x\buddy.exe" hook'


def test_hook_command_source_form(monkeypatch):
    monkeypatch.setattr(winapp, "current_exe", lambda: None)
    assert "-m buddybridge.hook" in winapp.hook_command()


def test_needs_relocate(tmp_path):
    assert winapp.needs_relocate(tmp_path, tmp_path / "other") is True
    assert winapp.needs_relocate(tmp_path, tmp_path) is False


def test_install_dir_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert winapp.install_dir() == tmp_path / "buddy-bridge"


def test_dispatch_routes_hook(monkeypatch):
    import buddybridge.hook as hook
    calls = []
    monkeypatch.setattr(hook, "main", lambda: calls.append("hook"))
    winapp.dispatch(["buddy.exe", "hook"])
    assert calls == ["hook"]


def test_dispatch_routes_tray(monkeypatch):
    import buddybridge.tray as tray
    calls = []
    monkeypatch.setattr(tray, "main", lambda: calls.append("tray"))
    winapp.dispatch(["buddy.exe"])
    assert calls == ["tray"]


def test_relocate_bundle_copies_then_noops(monkeypatch, tmp_path):
    src = tmp_path / "download"
    (src / "_internal").mkdir(parents=True)
    (src / "buddy.exe").write_text("exe")
    (src / "_internal" / "lib.dll").write_text("dll")
    target = tmp_path / "Local" / "buddy-bridge"
    monkeypatch.setattr(winapp, "current_exe", lambda: str(src / "buddy.exe"))
    monkeypatch.setattr(winapp, "install_dir", lambda: target)

    out = winapp.relocate_bundle()
    assert Path(out) == target / "buddy.exe"
    assert (target / "buddy.exe").read_text() == "exe"
    assert (target / "_internal" / "lib.dll").read_text() == "dll"

    monkeypatch.setattr(winapp, "current_exe", lambda: str(target / "buddy.exe"))
    assert winapp.relocate_bundle() == str(target / "buddy.exe")   # already in place


def test_relocate_noop_when_not_frozen(monkeypatch):
    monkeypatch.setattr(winapp, "current_exe", lambda: None)
    assert winapp.relocate_bundle() is None
