"""Cross-OS background-service registration.

Linux/WSL: a `systemd --user` unit. Windows: a `.cmd` in the Startup folder
(pure-Python, no pywin32). Pure text builders are separated from the I/O so they
can be unit-tested; the subprocess calls go through `_run` for the same reason.
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path


_LABEL_PREFIX = "com.claudebuddy."


def _label(name):
    return _LABEL_PREFIX + name


def launchd_plist(label, exec_cmd):
    args = shlex.split(exec_cmd)
    arg_xml = "\n".join(f"    <string>{a}</string>" for a in args)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f'  <key>Label</key>\n  <string>{label}</string>\n'
        f'  <key>ProgramArguments</key>\n  <array>\n{arg_xml}\n  </array>\n'
        '  <key>RunAtLoad</key>\n  <true/>\n'
        '  <key>KeepAlive</key>\n  <true/>\n'
        '</dict>\n</plist>\n'
    )


def _launchd_dir():
    return Path.home() / "Library" / "LaunchAgents"


def systemd_unit(exec_cmd, description):
    return (
        "[Unit]\n"
        f"Description={description}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_cmd}\n"
        "Restart=always\n"
        "RestartSec=3\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def windows_cmd(exec_cmd):
    # Launched minimized/hidden at logon from the Startup folder.
    return f'@echo off\r\nstart "" /min {exec_cmd}\r\n'


def _systemd_dir():
    return Path.home() / ".config" / "systemd" / "user"


def _startup_dir():
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _run(cmd):
    subprocess.run(cmd, check=False)


def register(name, exec_cmd, description):
    if sys.platform == "darwin":
        d = _launchd_dir(); d.mkdir(parents=True, exist_ok=True)
        plist = d / f"{_label(name)}.plist"
        plist.write_text(launchd_plist(_label(name), exec_cmd), encoding="utf-8")
        _run(["launchctl", "unload", str(plist)])           # idempotent reload
        _run(["launchctl", "load", str(plist)])
        return
    if sys.platform == "win32":
        d = _startup_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.cmd").write_text(windows_cmd(exec_cmd), encoding="utf-8")
    else:
        d = _systemd_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.service").write_text(systemd_unit(exec_cmd, description), encoding="utf-8")
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", f"{name}.service"])


def unregister(name):
    if sys.platform == "darwin":
        plist = _launchd_dir() / f"{_label(name)}.plist"
        _run(["launchctl", "unload", str(plist)])
        plist.unlink(missing_ok=True)
        return
    if sys.platform == "win32":
        (_startup_dir() / f"{name}.cmd").unlink(missing_ok=True)
    else:
        _run(["systemctl", "--user", "disable", "--now", f"{name}.service"])
        (_systemd_dir() / f"{name}.service").unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])


def status(name):
    if sys.platform == "darwin":
        out = subprocess.run(["launchctl", "list", _label(name)],
                             capture_output=True, text=True)
        return "active" if out.returncode == 0 else "not installed"
    if sys.platform == "win32":
        return "installed" if (_startup_dir() / f"{name}.cmd").exists() else "not installed"
    out = subprocess.run(["systemctl", "--user", "is-active", f"{name}.service"],
                         capture_output=True, text=True)
    return out.stdout.strip() or "unknown"
