import importlib
import json

import pytest

from buddybridge import config
from buddybridge.ctl import hooks as ctl_hooks


def test_hook_paused_stays_silent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.json")
    config.save_config({"hub": "http://x:8787", "paused": True})
    hook = importlib.reload(importlib.import_module("buddybridge.hook"))
    assert hook.is_paused() is True
    called = []
    monkeypatch.setattr(hook, "post", lambda *a, **k: called.append(a))
    with pytest.raises(SystemExit) as e:
        hook.main()                      # exits before reading stdin or posting
    assert e.value.code == 0
    assert called == []
    config.save_config({"hub": "http://x:8787"})            # unpaused
    assert importlib.reload(hook).is_paused() is False


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


def test_install_idempotent_and_module_command(tmp_path):
    sp = tmp_path / "settings.json"
    cmd = ctl_hooks.install(str(sp), python="/usr/bin/python3")
    assert cmd == '"/usr/bin/python3" -m buddybridge.hook'
    data = json.loads(sp.read_text())
    assert set(data["hooks"]) == {"PermissionRequest", "PostToolUse",
                                  "SessionStart", "SessionEnd", "UserPromptSubmit", "Stop"}
    assert data["hooks"]["PermissionRequest"][0]["matcher"] == "Bash|Edit|Write|NotebookEdit"
    ctl_hooks.install(str(sp), python="/usr/bin/python3")  # re-run
    data2 = json.loads(sp.read_text())
    assert len(data2["hooks"]["PostToolUse"]) == 1          # no duplication
    assert "-m buddybridge.hook" in data2["hooks"]["PostToolUse"][0]["hooks"][0]["command"]


def test_install_exe_command_override_detected_and_idempotent(tmp_path):
    sp = tmp_path / "settings.json"
    exe_cmd = r'"C:\Users\me\AppData\Local\buddy-bridge\buddy.exe" hook'
    cmd = ctl_hooks.install(str(sp), command=exe_cmd)
    assert cmd == exe_cmd
    data = json.loads(sp.read_text())
    assert data["hooks"]["PostToolUse"][0]["hooks"][0]["command"] == exe_cmd
    # re-running with the exe command must not duplicate (detector recognizes it)
    ctl_hooks.install(str(sp), command=exe_cmd)
    assert len(json.loads(sp.read_text())["hooks"]["PostToolUse"]) == 1
    # a later switch back to the module form also de-dupes the exe entry
    ctl_hooks.install(str(sp), python="/usr/bin/python3")
    post = json.loads(sp.read_text())["hooks"]["PostToolUse"]
    assert len(post) == 1 and "buddybridge.hook" in post[0]["hooks"][0]["command"]
    ctl_hooks.remove(str(sp))
    assert "hooks" not in json.loads(sp.read_text())


def test_is_buddy_recognizes_all_three_forms():
    forms = [
        '"/usr/bin/python3" -m buddybridge.hook',
        r'python "%~dp0buddy-hook.py"',
        r'"C:\x\buddy.exe" hook',
        r'C:\x\BUDDY.EXE hook',
    ]
    for c in forms:
        assert ctl_hooks._is_buddy({"hooks": [{"command": c}]}), c
    assert not ctl_hooks._is_buddy({"hooks": [{"command": "other.py"}]})


def test_install_preserves_non_buddy_and_remove_strips(tmp_path):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "*", "hooks": [{"type": "command", "command": "other.py"}]}]}}))
    ctl_hooks.install(str(sp))
    cmds = [h["command"] for e in json.loads(sp.read_text())["hooks"]["PostToolUse"]
            for h in e["hooks"]]
    assert any("other.py" in c for c in cmds) and any("buddybridge.hook" in c for c in cmds)
    ctl_hooks.remove(str(sp))
    post = json.loads(sp.read_text())["hooks"].get("PostToolUse", [])
    cmds = [h["command"] for e in post for h in e["hooks"]]
    assert any("other.py" in c for c in cmds) and not any("buddybridge.hook" in c for c in cmds)
