"""buddyctl — install/manage the hub, relay, and client roles on this machine."""
import argparse
import socket
import sys
from pathlib import Path

from buddybridge import config
from buddybridge.ctl import hooks, services, tunnel


def _claude_settings_path():
    return Path.home() / ".claude" / "settings.json"


def _python_for_service():
    """The interpreter to bake into a service ExecStart (pythonw hides the console on Windows)."""
    exe = sys.executable
    if sys.platform == "win32":
        exe = exe.replace("python.exe", "pythonw.exe")
    return exe


# ---- client ------------------------------------------------------------- #
def _client_install(args):
    cfg = config.load_config()
    if args.tunnel:
        # A forward tunnel makes the hub local; point the hub at 127.0.0.1 and
        # register the ssh service that keeps it up.
        services.register("buddy-tunnel", tunnel.forward_tunnel_cmd(args.tunnel),
                          f"Claude Buddy forward tunnel to {args.tunnel}")
        cfg["hub"] = "http://127.0.0.1:8787"
    elif args.hub:
        cfg["hub"] = args.hub.rstrip("/")
    cfg.setdefault("hub", "http://127.0.0.1:8787")
    cfg["machine"] = args.name or cfg.get("machine") or socket.gethostname().split(".")[0]
    config.save_config(cfg)
    cmd = hooks.install(str(_claude_settings_path()))
    print(f"client installed: machine={cfg['machine']}  hub={cfg['hub']}")
    if args.tunnel:
        print(f"  forward tunnel -> {args.tunnel} (hub reachable at 127.0.0.1:8787)")
    print(f"  hook command: {cmd}")
    print("  restart any running `claude` session to load the hooks.")


def _client_uninstall(args):
    hooks.remove(str(_claude_settings_path()))
    print("client hooks removed (config left in place).")


# ---- hub ---------------------------------------------------------------- #
def _hub_install(args):
    exec_cmd = (f'"{_python_for_service()}" -m buddybridge.hub '
                f'--port {args.port} --transport {args.transport} --owner {args.owner}')
    services.register("buddyhub", exec_cmd, "Claude Buddy hub")
    print(f"hub installed (transport={args.transport}, port={args.port}, owner={args.owner}).")


def _hub_uninstall(args):
    services.unregister("buddyhub")
    print("hub removed.")


# ---- relay -------------------------------------------------------------- #
def _relay_install(args):
    exec_cmd = f'"{_python_for_service()}" -m buddybridge.relay --hub {args.hub}'
    services.register("buddy-relay", exec_cmd, "Claude Buddy BLE relay")
    print("relay installed.")


def _relay_uninstall(args):
    services.unregister("buddy-relay")
    print("relay removed.")


def _relay_pair(args):
    """Run the relay in the foreground so you can enter the BLE passkey."""
    from buddybridge import relay
    relay.main(["--console", "--hub", args.hub])


# ---- status ------------------------------------------------------------- #
def _status(args):
    cfg = config.load_config()
    print(f"machine: {cfg.get('machine', '(unset)')}   hub: {cfg.get('hub', '(unset)')}")
    for name in ("buddyhub", "buddy-relay"):
        print(f"  {name}: {services.status(name)}")
    sp = _claude_settings_path()
    try:
        installed = "buddybridge.hook" in sp.read_text(encoding="utf-8")
    except OSError:
        installed = False
    print(f"  client hooks: {'installed' if installed else 'not installed'}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="buddyctl",
                                description="Install/manage buddy-bridge roles on this machine.")
    sub = p.add_subparsers(dest="role", required=True)

    pc = sub.add_parser("client", help="report this machine's Claude CLI sessions to a hub")
    pcs = pc.add_subparsers(dest="action", required=True)
    pci = pcs.add_parser("install")
    pci.add_argument("--hub", help="hub URL (default http://127.0.0.1:8787)")
    pci.add_argument("--name", help="display name (default: hostname)")
    pci.add_argument("--tunnel", help="SSH host to forward-tunnel the hub through (Task 6)")
    pci.set_defaults(func=_client_install)
    pcs.add_parser("uninstall").set_defaults(func=_client_uninstall)
    pcs.add_parser("status").set_defaults(func=_status)

    ph = sub.add_parser("hub", help="aggregate sessions + serve the dashboard")
    phs = ph.add_subparsers(dest="action", required=True)
    phi = phs.add_parser("install")
    phi.add_argument("--port", type=int, default=8787)
    phi.add_argument("--transport", default="relay", choices=["relay", "mock"])
    phi.add_argument("--owner", default="you", help="name shown on the device/dashboard")
    phi.set_defaults(func=_hub_install)
    phs.add_parser("uninstall").set_defaults(func=_hub_uninstall)

    pr = sub.add_parser("relay", help="drive the stick over Bluetooth")
    prs = pr.add_subparsers(dest="action", required=True)
    pri = prs.add_parser("install")
    pri.add_argument("--hub", default="127.0.0.1:8790")
    pri.set_defaults(func=_relay_install)
    prs.add_parser("uninstall").set_defaults(func=_relay_uninstall)
    prp = prs.add_parser("pair")
    prp.add_argument("--hub", default="127.0.0.1:8790")
    prp.set_defaults(func=_relay_pair)

    sub.add_parser("status", help="show what this machine runs").set_defaults(func=_status)

    args = p.parse_args(argv)
    args.func(args)
