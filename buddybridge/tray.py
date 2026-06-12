"""buddy-bridge tray app — a Windows system-tray client (monitor + config).

A thin pystray/tkinter shell over the existing config + hooks logic:

  * shows live hub status (polls GET /state),
  * edits hub URL / token / machine name,
  * installs/removes the Claude hooks (pointing at this exe),
  * pauses reporting, opens the dashboard.

It does NOT approve/deny (that stays on the stick or the web dashboard) and is
not in the data path — Claude's hook posts straight to the hub, so reporting
keeps working even when this app is closed.

pystray/tkinter/PIL are imported lazily inside the UI functions so the pure
logic here imports fine on a headless box (and under pytest).
"""
import json
import socket
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from buddybridge import config as _config
from buddybridge.ctl import hooks as _hooks, services as _services

POLL_SECONDS = 5
STARTUP_NAME = "buddy-tray"


# ---- pure logic (unit-tested) ------------------------------------------- #

def resolve_hub():
    return (_config.load_config().get("hub") or "http://127.0.0.1:8787").rstrip("/")


def resolve_token():
    return _config.load_config().get("token") or ""


def resolve_machine():
    return (_config.load_config().get("machine")
            or socket.gethostname().split(".")[0])


def valid_hub_url(url):
    u = urlparse((url or "").strip())
    return u.scheme in ("http", "https") and bool(u.netloc)


def fetch_state(hub, token, timeout=3):
    """GET /state. Returns (state_dict_or_None, reachable_bool)."""
    headers = {"X-Buddy-Token": token} if token else {}
    try:
        req = urllib.request.Request(hub.rstrip("/") + "/state", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}"), True
    except Exception:
        return None, False


def summarize_state(state, reachable=True):
    """(label, color) for the tray icon/menu from a /state dict."""
    if not reachable or state is None:
        return ("disconnected", "grey")
    total = int(state.get("total", 0) or 0)
    waiting = int(state.get("waiting", 0) or 0)
    if total == 0:
        return ("no active sessions", "green")
    label = f"{total} session" + ("s" if total != 1 else "")
    if waiting:
        label += f" · {waiting} waiting"
    return (label, "green")


def claude_settings_path():
    return Path.home() / ".claude" / "settings.json"


def hooks_installed():
    try:
        data = json.loads(claude_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(_hooks._is_buddy(e)
               for entries in data.get("hooks", {}).values() for e in entries)


def is_paused():
    return bool(_config.load_config().get("paused"))


def set_paused(value):
    cfg = _config.load_config()
    cfg["paused"] = bool(value)
    _config.save_config(cfg)


def save_settings(hub, token, machine):
    cfg = _config.load_config()
    cfg["hub"] = (hub or "").rstrip("/")
    cfg["token"] = token or ""
    cfg["machine"] = machine or cfg.get("machine") or socket.gethostname().split(".")[0]
    _config.save_config(cfg)


# ---- actions (compose pure logic + reused ctl) -------------------------- #

def install_hooks():
    from buddybridge import winapp
    _hooks.install(str(claude_settings_path()), command=winapp.hook_command())


def remove_hooks():
    _hooks.remove(str(claude_settings_path()))


def register_autostart():
    from buddybridge import winapp
    exe = winapp.current_exe()
    if exe:
        _services.register(STARTUP_NAME, f'"{exe}"', "Claude Buddy tray")


def unregister_autostart():
    _services.unregister(STARTUP_NAME)


def connect(hub, token, machine):
    """First-run / Settings 'Connect': relocate, save, wire hooks + autostart."""
    from buddybridge import winapp
    winapp.relocate_bundle()          # no-op when not frozen / already in place
    save_settings(hub, token, machine)
    set_paused(False)
    install_hooks()
    register_autostart()


def uninstall():
    """'Remove': strip hooks + autostart, drop the relocated bundle."""
    from buddybridge import winapp
    remove_hooks()
    unregister_autostart()
    winapp.remove_bundle()


def open_dashboard():
    import webbrowser
    hub, token = resolve_hub(), resolve_token()
    url = hub + (f"/?token={token}" if token else "/")
    webbrowser.open(url)


# ---- GUI shell (lazy imports; manual-smoke on Windows) ------------------ #

def _icon_image(color):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = {"green": (76, 175, 80, 255), "grey": (140, 140, 140, 255)}.get(color, (140, 140, 140, 255))
    d.ellipse((8, 8, 56, 56), fill=fill)
    return img


def _single_instance_lock(port=49677):
    """Hold a localhost socket so a second launch (login autostart + a manual
    double-click) detects the first and exits. Returns the socket — keep a
    reference for the process lifetime — or None if another instance owns it."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def _settings_window(root, on_done=None, first_run=False):
    """Build the hub/token/name form as a Toplevel on the Tk main thread."""
    import tkinter as tk
    from tkinter import messagebox

    cfg = _config.load_config()
    win = tk.Toplevel(root)
    win.title("buddy-bridge — setup" if first_run else "buddy-bridge — settings")
    win.resizable(False, False)
    fields = {}
    rows = [
        ("hub", "Hub URL", cfg.get("hub", "http://127.0.0.1:8787"), None),
        ("token", "Token", cfg.get("token", ""), "*"),
        ("machine", "This machine's name", cfg.get("machine", resolve_machine()), None),
    ]
    for i, (key, label, default, show) in enumerate(rows):
        tk.Label(win, text=label).grid(row=i, column=0, sticky="e", padx=8, pady=6)
        var = tk.StringVar(value=default)
        tk.Entry(win, textvariable=var, width=44, show=show).grid(row=i, column=1, padx=8, pady=6)
        fields[key] = var

    def do_connect():
        hub = fields["hub"].get().strip()
        if not valid_hub_url(hub):
            messagebox.showerror("buddy-bridge", "Enter a valid http(s) hub URL.", parent=win)
            return
        try:
            connect(hub, fields["token"].get().strip(), fields["machine"].get().strip())
        except Exception as e:                       # surface failures, don't freeze
            messagebox.showerror("buddy-bridge", f"Setup failed: {e}", parent=win)
            return
        if on_done:
            on_done()
        win.destroy()

    tk.Button(win, text="Connect" if first_run else "Save",
              command=do_connect).grid(row=len(rows), column=0, columnspan=2, pady=10)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.lift()
    win.focus_force()
    return win


def main():
    import queue
    import tkinter as tk
    import pystray

    lock = _single_instance_lock()
    if lock is None:
        return                                       # another tray instance is running

    # tkinter MUST own the main thread; pystray runs on a background thread and
    # marshals clicks back here through ui_q (tkinter isn't thread-safe).
    root = tk.Tk()
    root.withdraw()                                  # hidden root; UI is Toplevels
    ui_q = queue.Queue()
    win_ref = {"settings": None}
    status = {"label": "starting…", "color": "grey", "hooks": hooks_installed()}

    def pump():
        try:
            while True:
                ui_q.get_nowait()()
        except queue.Empty:
            pass
        root.after(100, pump)

    def on_main(fn, *a):
        ui_q.put(lambda: fn(*a))

    def show_settings(first_run=False):
        w = win_ref["settings"]
        if w is not None and w.winfo_exists():
            w.lift(); w.focus_force(); return
        win_ref["settings"] = _settings_window(
            root, on_done=lambda: status.update(hooks=hooks_installed()), first_run=first_run)

    def _act(fn):
        # run an action, refresh cached hook status, redraw the menu
        try:
            fn()
        finally:
            status["hooks"] = hooks_installed()
            try:
                icon.update_menu()
            except Exception:
                pass

    menu = pystray.Menu(
        pystray.MenuItem(lambda *a: status["label"], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open dashboard…", lambda *a: open_dashboard()),
        pystray.MenuItem("Settings…", lambda *a: on_main(show_settings, False)),
        pystray.MenuItem(lambda *a: "Hooks: installed ✓" if status["hooks"] else "Hooks: not installed",
                         None, enabled=False),
        pystray.MenuItem("Reinstall hooks", lambda *a: _act(install_hooks)),
        pystray.MenuItem("Remove (uninstall)", lambda *a: _act(uninstall)),
        pystray.MenuItem("Pause reporting",
                         lambda *a: _act(lambda: set_paused(not is_paused())),
                         checked=lambda *a: is_paused()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda *a: (icon.stop(), on_main(root.destroy))),
    )
    icon = pystray.Icon("buddy-bridge", _icon_image("grey"), "buddy-bridge", menu=menu)

    def poll():
        while True:
            st, reachable = fetch_state(resolve_hub(), resolve_token())
            label, color = summarize_state(st, reachable)
            status["label"], status["hooks"] = label, hooks_installed()
            icon.title = f"buddy-bridge — {label}"
            if color != status["color"]:
                status["color"] = color
                try:
                    icon.icon = _icon_image(color)
                except Exception:
                    pass
            try:
                icon.update_menu()
            except Exception:
                pass
            time.sleep(POLL_SECONDS)

    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=icon.run, daemon=True).start()
    root.after(100, pump)
    if not _config.load_config():
        on_main(show_settings, True)                 # first run: open setup

    try:
        root.mainloop()
    finally:
        try:
            icon.stop()
        except Exception:
            pass
        lock.close()


if __name__ == "__main__":
    main()
