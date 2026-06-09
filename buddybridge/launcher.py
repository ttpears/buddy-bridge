#!/usr/bin/env python3
"""buddy launcher — run Claude Code with Hardware Buddy stick control enabled.

Sets BUDDY_CONTROL=1 so this session's permission prompts route to the stick
(and the web dashboard) for A/B approval. Plain `claude` stays ambient-only.
Cross-platform replacement for the buddy / buddy.cmd shell shims.
"""
import os
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ)
    env["BUDDY_CONTROL"] = "1"
    os.execvpe("claude", ["claude", *argv], env)


if __name__ == "__main__":
    main()
