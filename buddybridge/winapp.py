"""Frozen Windows entry point — dispatch argv to the tray app or the hook.

The packaged `buddy.exe` is built from this module. With no args it launches the
tray app; `buddy.exe hook` runs the per-event hook (so a single file does both).
Running from source, `python -m buddybridge.winapp` behaves the same.
"""
import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "buddy-bridge"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def current_exe():
    """Path to the running exe when frozen, else None (running from source)."""
    return sys.executable if is_frozen() else None


def hook_command(exe=None):
    """The Claude hook command for this install: the exe (frozen) or `python -m`."""
    exe = exe if exe is not None else current_exe()
    if exe:
        return f'"{exe}" hook'
    return f'"{sys.executable}" -m buddybridge.hook'


def relay_argv():
    """Argv list to run the BLE relay: the frozen exe or `python -m`."""
    exe = current_exe()
    if exe:
        return [exe, "relay"]
    return [sys.executable, "-m", "buddybridge.relay"]


def install_dir():
    """Stable per-user home for the bundle (no admin, no installer)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_DIR_NAME


def needs_relocate(exe_dir, target_dir):
    """True when the frozen bundle isn't already running from the stable dir."""
    try:
        return Path(exe_dir).resolve() != Path(target_dir).resolve()
    except OSError:
        return str(exe_dir) != str(target_dir)


def relocate_bundle():
    """Copy the onedir bundle into LOCALAPPDATA so the download folder is
    disposable; return the stable exe path. No-op (returns the current exe) when
    not frozen or already in place."""
    exe = current_exe()
    if not exe:
        return None
    src_dir = Path(exe).parent
    target = install_dir()
    if not needs_relocate(src_dir, target):
        return exe
    target.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
    return str(target / Path(exe).name)


def remove_bundle():
    """Delete the relocated bundle (uninstall, no installer)."""
    target = install_dir()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def _ensure_stdout():
    """A frozen windowed exe can have sys.stdout=None, but the hook writes its
    permission-decision JSON to stdout. Claude spawns the hook with a redirected
    stdout, so fd 1 is valid — reopen it if Python left sys.stdout as None."""
    if sys.stdout is None:
        try:
            sys.stdout = open(1, "w", closefd=False)
        except OSError:
            pass


def dispatch(argv):
    if len(argv) > 1 and argv[1] == "hook":
        _ensure_stdout()
        from buddybridge import hook
        return hook.main()
    if len(argv) > 1 and argv[1] == "relay":
        from buddybridge import relay
        return relay.main(argv[2:])
    from buddybridge import tray
    return tray.main()


def main():
    dispatch(sys.argv)


if __name__ == "__main__":
    main()
