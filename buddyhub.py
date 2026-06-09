#!/usr/bin/env python3
"""Backward-compat shim. The hub now lives in buddybridge.hub.
Kept so an existing systemd unit pointing at this path keeps working until
`buddyctl hub install` re-registers it. Prefer the `buddyhub` console script.
"""
from buddybridge.hub import main

if __name__ == "__main__":
    main()
