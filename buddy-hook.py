#!/usr/bin/env python3
"""Backward-compat shim. The hook now lives in buddybridge.hook.
Existing ~/.claude/settings.json entries reference this path; keep it working
until `buddyctl client install` rewrites them.
"""
from buddybridge.hook import main

if __name__ == "__main__":
    main()
