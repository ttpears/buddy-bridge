@echo off
rem buddy-hook.cmd — Windows wrapper for buddy-hook.py
rem Sets env vars and forwards stdin to the Python hook.
rem Set BUDDY_HUB to your hub's address:
rem   Local:   http://127.0.0.1:8787  (buddyhub on same machine / WSL)
rem   Android: http://<phone-ip>:8787 (buddy-bridge-android via Tailscale)
if not defined BUDDY_HUB set "BUDDY_HUB=http://127.0.0.1:8787"
if not defined BUDDY_MACHINE set "BUDDY_MACHINE=%COMPUTERNAME%"
python "%~dp0buddy-hook.py" %*
