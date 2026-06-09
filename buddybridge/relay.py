#!/usr/bin/env python3
"""
relay.py — M5Stick BLE relay (runs on the machine with the Bluetooth radio).
Bridges buddyhub's TCP relay socket <-> the stick's BLE Nordic UART.

Self-contained: a supervising loop (restarts its own connections), a
single-instance guard (a loopback-port lock — a second copy exits immediately,
so it can't pile up), and a size-capped rotating log. Run hidden via pythonw;
managed by manage.ps1.

  pythonw relay.py             # hidden background run (logs to relay.log)
  python  relay.py --console   # foreground + console logging (debugging)
"""
import argparse
import asyncio
import logging
import logging.handlers
import socket
import sys
from pathlib import Path

# bleak is the optional [relay] extra — imported lazily so `buddy-relay --help`
# and importing this module work without it; main() checks for it up front.

NUS_SVC = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write   host -> device
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify  device -> host

LOCK_PORT = 8791                                   # loopback single-instance lock
LOGFILE = Path(__file__).resolve().parent / "relay.log"
_lock = None                                        # keep the lock socket alive


def single_instance():
    """Bind a loopback port as a lock. False if another relay already holds it."""
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
    handlers = [logging.handlers.RotatingFileHandler(
        LOGFILE, maxBytes=512 * 1024, backupCount=1, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)


async def _drain(writer):
    try:
        await writer.drain()
    except Exception:
        pass


async def relay_once(host, port, name_prefix, scan_timeout, do_pair, pair_timeout):
    from bleak import BleakScanner, BleakClient
    logging.info("connecting to hub %s:%d", host, port)
    reader, writer = await asyncio.open_connection(host, port)
    logging.info("hub connected; scanning for the stick")
    try:
        dev = await BleakScanner.find_device_by_filter(
            lambda d, ad: (d.name or "").startswith(name_prefix), timeout=scan_timeout)
        if not dev:
            logging.info("no BLE device advertising '%s*' found", name_prefix)
            return
        logging.info("found %s [%s]; connecting BLE", dev.name, dev.address)
        loop = asyncio.get_running_loop()
        async with BleakClient(dev) as client:
            if do_pair:
                try:
                    await client.pair()
                except Exception as e:
                    logging.info("pair() note: %s", e)
            logging.info("BLE connected")

            def on_notify(_s, data: bytearray):
                writer.write(bytes(data))
                loop.create_task(_drain(writer))

            # The NUS characteristics are encrypted-only: until bonding finishes
            # (you type the stick's passkey on the desktop) start_notify fails.
            # Retry on the SAME link so one passkey stays on screen for the whole
            # window, instead of dropping the link and forcing a fresh code every
            # reconnect. Succeeds on the first try once already bonded.
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
            logging.info("subscribed; relaying")
            mtu = (client.mtu_size - 3) if getattr(client, "mtu_size", 0) else 20
            while True:
                line = await reader.readline()
                if not line:
                    logging.info("hub closed the connection")
                    break
                for i in range(0, len(line), mtu):
                    await client.write_gatt_char(NUS_RX, line[i:i + mtu], response=False)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def supervise(args):
    while True:
        try:
            await relay_once(args.host, args.port, args.name, args.scan_timeout,
                             not args.no_pair, args.pair_timeout)
        except Exception as e:
            logging.info("relay error: %s", e)
        await asyncio.sleep(args.retry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default="127.0.0.1:8790")
    ap.add_argument("--name", default="Claude")
    ap.add_argument("--scan-timeout", type=float, default=15.0)
    ap.add_argument("--no-pair", action="store_true")
    ap.add_argument("--pair-timeout", type=float, default=60.0,
                    help="seconds to keep one passkey on screen while you enter it")
    ap.add_argument("--retry", type=float, default=5.0)
    ap.add_argument("--console", action="store_true")
    args = ap.parse_args()
    args.host, _, port = args.hub.partition(":")
    args.port = int(port or 8790)

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
    logging.info("relay starting (hub %s:%d)", args.host, args.port)
    try:
        asyncio.run(supervise(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
