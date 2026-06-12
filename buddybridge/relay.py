#!/usr/bin/env python3
"""
relay.py — M5Stick BLE relay (runs on the machine with the Bluetooth radio).
Bridges a buddyhub's HTTP relay stream <-> the stick's BLE Nordic UART.

Outbound only: opens GET {hub}/relay/stream (chunked newline-JSON heartbeats),
writes each line to the stick verbatim, and POSTs the stick's button presses to
{hub}/button. No inbound port — so it works behind NAT, on a laptop, anywhere.

  buddy-relay                   # background run (logs to relay.log)
  buddy-relay --console         # foreground + console logging (debugging)
  buddy-relay --hub https://buddy.example.com   # remote hub over TLS
"""
import argparse
import asyncio
import json
import logging
import logging.handlers
import socket
import sys
import urllib.request
from pathlib import Path

from buddybridge import config as _config

NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write   host -> device
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify  device -> host

LOCK_PORT = 8791
# In the config dir (writable on every OS) — NOT next to the module, which is
# read-only / non-existent inside a frozen PyInstaller bundle.
LOGFILE = _config.config_dir() / "relay.log"
_lock = None

HEARTBEAT_TIMEOUT = 45.0   # no hub line for this long -> reconnect (stream watchdog)
BLE_WRITE_TIMEOUT = 5.0    # a single BLE write blocking this long -> reconnect


def single_instance():
    global _lock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
    except OSError:
        return False
    _lock = s
    return True


def setup_logging(console):
    LOGFILE.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(
        LOGFILE, maxBytes=512 * 1024, backupCount=1, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)


def resolve_hub(arg):
    return (arg or _config.load_config().get("hub") or "http://127.0.0.1:8787").rstrip("/")


def resolve_token():
    import os
    return os.environ.get("BUDDY_TOKEN") or _config.load_config().get("token") or ""


def post_button(hub, token, payload):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Buddy-Token"] = token
    req = urllib.request.Request(hub + "/button", data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        logging.info("button POST failed: %s", e)


def open_stream(hub, token):
    url = hub + "/relay/stream"
    headers = {}
    if token:
        headers["X-Buddy-Token"] = token
    req = urllib.request.Request(url, headers=headers, method="GET")
    return urllib.request.urlopen(req, timeout=None)


async def relay_once(hub, token, name_prefix, scan_timeout, do_pair, pair_timeout):
    from bleak import BleakScanner, BleakClient
    logging.info("scanning for the stick")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or "").startswith(name_prefix), timeout=scan_timeout)
    if not dev:
        logging.info("no BLE device advertising '%s*' found", name_prefix)
        return
    logging.info("found %s [%s]; connecting BLE", dev.name, dev.address)
    loop = asyncio.get_running_loop()
    lines = asyncio.Queue()

    def reader_thread(resp):
        """Blocking HTTP stream reader -> asyncio queue (runs in a thread)."""
        try:
            for raw in resp:
                line = raw.decode(errors="ignore").strip()
                if line:
                    loop.call_soon_threadsafe(lines.put_nowait, line)
        except Exception as e:
            logging.info("stream read ended: %s", e)
        finally:
            loop.call_soon_threadsafe(lines.put_nowait, None)   # EOF sentinel

    async with BleakClient(dev) as client:
        if do_pair:
            try:
                await client.pair()
            except Exception as e:
                logging.info("pair() note: %s", e)
        logging.info("BLE connected")

        def on_notify(_s, data: bytearray):
            # Device -> host: button-press permission lines. Parse and POST.
            for piece in bytes(data).decode(errors="ignore").splitlines():
                piece = piece.strip()
                if not piece:
                    continue
                try:
                    msg = json.loads(piece)
                except json.JSONDecodeError:
                    continue
                if msg.get("cmd") == "permission":
                    payload = {"id": msg.get("id", ""),
                               "decision": msg.get("decision", "deny")}
                    loop.call_soon_threadsafe(
                        loop.run_in_executor, None, post_button, hub, token, payload)

        deadline = loop.time() + pair_timeout
        while True:
            try:
                await client.start_notify(NUS_TX, on_notify)
                break
            except Exception as e:
                if loop.time() >= deadline:
                    raise
                logging.info("waiting for pairing — enter the passkey on the desktop (%s)", e)
                await asyncio.sleep(2.0)

        logging.info("connecting hub stream %s", hub)
        resp = await loop.run_in_executor(None, open_stream, hub, token)
        loop.run_in_executor(None, reader_thread, resp)
        logging.info("subscribed; relaying")
        mtu = (client.mtu_size - 3) if getattr(client, "mtu_size", 0) else 20
        delivered = 0
        try:
            while True:
                try:
                    line = await asyncio.wait_for(lines.get(), timeout=HEARTBEAT_TIMEOUT)
                except asyncio.TimeoutError:
                    logging.info("no hub data in %ss — reconnecting", HEARTBEAT_TIMEOUT)
                    break
                if line is None:
                    logging.info("hub stream closed")
                    break
                payload = (line + "\n").encode()
                chunks = [payload[i:i + mtu] for i in range(0, len(payload), mtu)]
                # Acknowledged writes (response=True): WinRT write-without-response
                # silently flow-control-hangs after the first packet, which left the
                # firmware with only the clock set and an otherwise-asleep pet.
                for idx, chunk in enumerate(chunks):
                    await asyncio.wait_for(
                        client.write_gatt_char(NUS_RX, chunk, response=True),
                        timeout=BLE_WRITE_TIMEOUT)
                    if idx < len(chunks) - 1:
                        await asyncio.sleep(0.005)
                delivered += 1
                if delivered == 1:
                    logging.info("first heartbeat delivered to the stick")
        finally:
            try:
                resp.close()
            except Exception:
                pass


async def supervise(args):
    hub = resolve_hub(args.hub)
    token = resolve_token()
    while True:
        try:
            await relay_once(hub, token, args.name, args.scan_timeout,
                             not args.no_pair, args.pair_timeout)
        except Exception as e:
            logging.info("relay error: %s", e)
        await asyncio.sleep(args.retry)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=None,
                    help="hub base URL (default: config hub or http://127.0.0.1:8787)")
    ap.add_argument("--name", default="Claude")
    ap.add_argument("--scan-timeout", type=float, default=15.0)
    ap.add_argument("--no-pair", action="store_true")
    ap.add_argument("--pair-timeout", type=float, default=60.0,
                    help="seconds to keep one passkey on screen while you enter it")
    ap.add_argument("--retry", type=float, default=5.0)
    ap.add_argument("--console", action="store_true")
    args = ap.parse_args(argv)

    try:
        import bleak  # noqa: F401
    except ModuleNotFoundError:
        print("buddy-relay needs Bluetooth support. Install it with:\n"
              "    pipx install 'buddy-bridge[relay]'   (or: pip install bleak)",
              file=sys.stderr)
        sys.exit(1)

    setup_logging(args.console)
    if not single_instance():
        logging.info("another relay instance already running (lock %d held); exiting", LOCK_PORT)
        return
    logging.info("relay starting (hub %s)", resolve_hub(args.hub))
    try:
        asyncio.run(supervise(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
