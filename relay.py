#!/usr/bin/env python3
"""Backward-compat shim. The relay now lives in buddybridge.relay.
Prefer the `buddy-relay` console script.
"""
from buddybridge.relay import main

if __name__ == "__main__":
    main()
