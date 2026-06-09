import importlib
import json

from buddybridge import config
from buddybridge.ctl import hooks as ctl_hooks


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
