"""SSH tunnel command builders for reaching a hub that isn't directly routable.

Forward (client dials the hub) is the default and what `--tunnel` sets up: the
client runs `ssh -L`, making the hub appear at 127.0.0.1 locally. Reverse (the
WSL-hub case, hub dials out) is documented for the hub side.
"""

_KEEPALIVE = ("-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
              "-o", "ExitOnForwardFailure=yes")


def forward_tunnel_cmd(ssh_host, port=8787):
    """Client-side: forward local :port to the hub's :port over SSH."""
    opts = " ".join(_KEEPALIVE)
    return f"ssh -N {opts} -L {port}:localhost:{port} {ssh_host}"


def reverse_tunnel_cmd(ssh_host, port=8787):
    """Hub-side (e.g. WSL hub): expose the hub's :port on the remote's localhost."""
    opts = " ".join(_KEEPALIVE)
    return f"ssh -N {opts} -R {port}:localhost:{port} {ssh_host}"
