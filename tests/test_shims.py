import subprocess
import sys


def test_root_buddyhub_shim_runs_help():
    out = subprocess.run([sys.executable, "buddyhub.py", "--help"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    assert "--transport" in out.stdout


def test_root_relay_shim_imports():
    # --help triggers argparse before any bleak BLE work; import must resolve.
    out = subprocess.run([sys.executable, "relay.py", "--help"],
                         capture_output=True, text=True, timeout=30)
    # Exit 0 if bleak present; non-zero ImportError is acceptable ONLY if it
    # names bleak, since bleak is an optional [relay] extra.
    assert out.returncode == 0 or "bleak" in (out.stderr + out.stdout)
