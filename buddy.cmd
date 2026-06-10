@echo off
rem buddy.cmd — launch Claude Code with Hardware Buddy control enabled.
rem Use this instead of `claude` when you want permission prompts routed to the stick.
rem Set BUDDY_HUB before running to point at your Android bridge, e.g.:
rem   set BUDDY_HUB=http://<phone-tailscale-ip>:8787
set "BUDDY_CONTROL=1"
claude %*
