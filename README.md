# buddy-bridge

Drives an **M5StickC Plus** "Hardware Buddy" from **Claude Code** activity across
multiple machines — showing busy/idle, surfacing permission prompts, and letting
you **approve or deny tool calls with the stick's A/B buttons**, including prompts
raised on a remote box.

The firmware and BLE wire protocol come from
[`anthropics/claude-desktop-buddy`](https://github.com/anthropics/claude-desktop-buddy):
the Claude **desktop apps** drive a paired device over Bluetooth LE (Nordic UART,
newline-delimited JSON — see that repo's `REFERENCE.md`). The desktop app only
feeds the device from itself, though — it can't see the `claude` **CLI**, let alone
CLI sessions running in WSL or on a remote machine. `buddy-bridge` fills that gap:
it speaks the *same* BLE protocol, sourced instead from Claude Code hook events
across any number of machines.

> This is an independent, unofficial project built on the public BLE protocol. It
> is not affiliated with, endorsed by, or supported by Anthropic.

### What you need
- An **M5StickC Plus** flashed with the
  [`claude-desktop-buddy`](https://github.com/anthropics/claude-desktop-buddy)
  firmware — a one-time flash over USB (PlatformIO; see that repo). buddy-bridge
  ships no firmware and only talks to a device already running it.
- A host with a Bluetooth radio to run `relay.py` (here, the Windows laptop),
  with **Python 3 + `bleak`**.
- **Python 3** on each machine running Claude Code (the hooks are stdlib-only).

`relay.py` is its own BLE central and connects to the stick directly, so the
desktop app is not a *dependency*. **But you must make sure the desktop app isn't
holding the stick:** only one central can connect at a time, and the app's
Hardware Buddy bridge **auto-reconnects in the background** (per `REFERENCE.md`) —
so closing its window is not enough. If the stick is bonded to the app, the app's
service will grab it out from under the relay. **Forget** the device in the app
(Developer → Hardware Buddy → Forget) — or quit the app entirely — to release the
stick to the relay. See *Pairing the stick*.

The one desktop-app feature buddy-bridge doesn't replicate is the *wireless*
character drop — load characters over USB instead (see *The `tty` character*).

---

## Architecture

```
  desk (WSL)                                            Windows laptop
  ┌───────────────────────────┐                        ┌────────────────────────┐
  │ claude sessions ─ hooks ─┐ │                        │ relay.py (bleak)       │
  │ remote sessions ─hooks───┼─┼─► buddyhub (systemd)   │   ▲ TCP 127.0.0.1:8790  │
  │   (via SSH reverse tunnel)│ │   :8787 http API      │   │ (WSL localhost-fwd) │
  │                           │ │   :8790 relay socket ─┼───┘                     │
  └───────────────────────────┘ │        │             │        │ BLE (NUS)       │
                                 └────────┼─────────────┘        ▼                 │
                                          │              🟧 M5StickC Plus          │
                                          └──── A/B button presses ◄───────────────┘
```

- **Hub** (`buddyhub.py`) runs in WSL as a systemd service. It aggregates session
  state from every machine, owns the permission queue, and speaks the Hardware
  Buddy protocol through a pluggable transport.
- **BLE radio** lives on the Windows laptop (its Bluetooth; only on when you work).
  A thin relay (`relay.py`) bridges the hub's TCP socket to the stick's BLE.
- **Remote machine** `remote` reaches the hub over an **SSH reverse tunnel**, so
  no inbound ports are exposed.

### Machines
| Name       | What                  | Reaches hub via            |
| ---------- | --------------------- | -------------------------- |
| `desk`     | local WSL (Arch) | `127.0.0.1:8787` directly |
| `remote`   | `remote.example.com` (Arch), SSH alias `workpc` | reverse tunnel `127.0.0.1:8787` |

---

## Components

| File                         | Where it runs | Role |
| ---------------------------- | ------------- | ---- |
| `buddyhub.py`                | WSL (hub)     | Brain: HTTP API, session aggregation, permission queue, transports (`mock` / `relay`) |
| `buddy-hook.py`              | every machine | Claude Code hook agent — reports session events, runs the control round-trip |
| `install_hooks.py`           | every machine | Idempotently merges buddy hooks into `~/.claude/settings.json` |
| `relay.py`                   | Windows       | bleak ↔ stick (Nordic UART) ↔ hub TCP; self-supervising, single-instance, rotating log |
| `manage.ps1`                 | Windows       | relay control: `-Install/-Restart/-Stop/-Status/-Logs/-Uninstall` |
| `build_tty.py`               | WSL           | Generates the `tty` character pack → `characters/tty/` |
| `buddy`                      | every machine | `BUDDY_CONTROL=1 claude` launcher (opt-in stick control); symlink onto your PATH |
| `C:\Users\<you>\buddy\`      | Windows       | `relay.py`, `manage.ps1`, `relay.log` |

---

## How it's wired

### Hooks (in each machine's `~/.claude/settings.json`)
Installed with `install_hooks.py`; loaded by Claude Code **at session start**
(restart any pre-existing session to pick them up).

| Hook event | Purpose | Timeout |
| ---------- | ------- | ------- |
| `SessionStart` / `SessionEnd` | register / drop a session | 5s |
| `UserPromptSubmit` | session → running; sends your **prompt snippet** to the feed | 5s |
| `PostToolUse` (matcher `*`) | sends a **tool-action snippet** (`$ cmd`, `Edit file`, …) to the feed | 5s |
| `Stop` | session → idle | 5s |
| `PermissionRequest` (matcher `Bash\|Edit\|Write\|NotebookEdit`) | **control path** — fires only on genuine prompts | 60s |

- **Ambient** events fire for *every* session, so the stick always reflects activity.
- **Control** (`PermissionRequest`) is gated by env **`BUDDY_CONTROL=1`** — only
  sessions launched via `buddy` route approvals to the stick. Normal `claude`
  sessions are never intercepted.
- Chosen over `PreToolUse` deliberately: `PermissionRequest` fires *only when
  Claude would actually prompt*, so auto-approved tools aren't needlessly routed.
- **Safety:** if the hub is unreachable or no one answers in 30s, the hook stays
  silent and Claude Code shows its normal in-terminal prompt. A dead bridge never
  blocks you.

### Control round-trip (A/B approval)
```
claude hits a tool needing approval
  → PermissionRequest hook POSTs {tool,hint} to hub, then long-polls /decision
  → hub puts the prompt in the heartbeat → stick: attention + LED
  → you press A → stick sends {"cmd":"permission","id","once"} → relay → hub
  → hub resolves the long-poll → hook emits decision.behavior=allow → tool runs
```

---

## Setup

On **each machine** that runs Claude Code:

1. **Install the hooks** into that machine's Claude Code settings (idempotent —
   preserves any non-buddy hooks; re-run to update):
   ```bash
   python3 install_hooks.py ~/.claude/settings.json "$(hostname -s)" \
       http://127.0.0.1:8787 "$PWD/buddy-hook.py"
   ```
   The machine name and hub URL are baked into the installed hook command. On
   `remote` the hub URL is still `http://127.0.0.1:8787` (the SSH reverse tunnel
   lands there); pass whatever name you want shown on the device.

2. **Install the `buddy` launcher** (shipped in this repo) onto your PATH so
   opt-in sessions route approvals to the stick — it just sets `BUDDY_CONTROL=1`
   before `claude`:
   ```bash
   ln -s "$PWD/buddy" ~/.local/bin/buddy
   ```
   Plain `claude` stays ambient-only and is never intercepted.

On the **hub machine** (WSL), run the hub:
```bash
python3 buddyhub.py --port 8787 --transport relay --owner you
```
Use `--transport mock` to drive it from the keyboard with no hardware at all —
type `a`/`d` to approve/deny, `s` for state, `q` to quit. For always-on, wire the
hub into systemd and set up the Windows BLE relay (both under *Operations*).

---

## Daily use

```bash
buddy                 # a session whose approvals route to the stick (A/B)
claude                # normal session — ambient only (busy/idle), no interception
```
On `remote` it's the same `buddy` launcher (its hook injects `BUDDY_MACHINE=remote`
and the tunneled hub URL).

**Web dashboard:** open `http://<hub-host>:8787/` in any browser for live session
state and Approve/Deny buttons — the bridge is fully usable on a fleet with no
hardware at all (the stick is just one optional output).

---

## Operations

### Hub + tunnel (WSL, systemd --user, linger enabled)
```bash
systemctl --user status  buddyhub.service buddy-tunnel.service
systemctl --user restart buddyhub.service
journalctl --user -u buddyhub.service -f
```
- `buddyhub.service` → `buddyhub.py --port 8787 --transport relay --owner you`
  (listens `:8787` HTTP, `:8790` relay).
- `buddy-tunnel.service` → `ssh -N -R 8787:localhost:8787 workpc`.

### BLE relay (Windows, Startup shortcut at logon)
The relay runs as a per-user **Startup shortcut**, not a SYSTEM service — BLE bonds
are per-user, so it must live in your logged-in session.

**First-time setup:**
1. Install **Python 3.12** for your user (`manage.ps1` expects it at
   `%LOCALAPPDATA%\Programs\Python\Python312\`), then `pip install bleak`.
2. Copy `relay.py` and `manage.ps1` into a folder (e.g. `C:\Users\<you>\buddy\`).
3. From that folder, run `.\manage.ps1 -Install` in PowerShell.

`manage.ps1 -Install` drops a Startup shortcut (`ClaudeBuddyRelay.lnk`) that runs
`pythonw relay.py` hidden in your user session and starts it now. `relay.py`
self-supervises (reconnects on drop) and is **single-instance guarded** (loopback-port
lock 8791; a second copy logs and exits), so it can't pile up. Logs rotate at 512 KB.
```powershell
.\manage.ps1 -Install     # logon shortcut + start now
.\manage.ps1 -Status      # PID(s) + hub reachability
.\manage.ps1 -Restart     # stop all + start one
.\manage.ps1 -Logs        # tail relay.log
.\manage.ps1 -Uninstall   # remove shortcut + stop
```

### Pairing the stick (one-time)
1. Claude desktop app → Hardware Buddy → **Forget** (releases its BLE bond; only one
   central can hold the stick).
2. Wake the stick; confirm Bluetooth on (hold A → settings → bluetooth).
3. Run the relay; enter the 6-digit passkey the stick shows. The relay holds that
   passkey on screen while it waits for you to bond — **60s** by default
   (`--pair-timeout`); the same code stays valid the whole time. `python relay.py
   --console --no-pair` tries an unencrypted link if bonding is fussy.

---

### Durability
- Hub auto-restarts (`Restart=always`), tunnel auto-reconnects, both linger across
  logout. Hub runs `python3 -u`, so relay connect/disconnect and device decisions
  show live in `journalctl --user -u buddyhub.service -f`.
- **Clean reconnects:** when the stick power-cycles, the relay reconnects with a
  fresh socket that *takes over* from the stale one; the hub re-sends the full state
  (time, owner, heartbeat) on every relay connect.
- **Idle sessions** persist 30 min (`STALE_SESSION_SEC`) before being reaped. A
  session counts as alive only while it emits events (start/prompt/stop) or until
  `SessionEnd`; sessions idle longer drop from the count until their next activity.
  (Exact long-idle tracking would need a per-machine liveness reporter — not built.)
- Hub state is in-memory: restarting `buddyhub.service` clears sessions; they
  re-register on their next event.

## Hub HTTP API (`:8787`)

| Method + path | Body | Purpose |
| ------------- | ---- | ------- |
| `GET /` , `GET /dashboard` | — | **Web dashboard** — live state + browser approve/deny (no stick needed) |
| `GET /detail` | — | richer JSON: per-machine + per-session breakdown (what the dashboard polls) |
| `POST /event` | `{machine,session,kind,msg?,tokens?}` (`kind`: session_start/session_end/running/idle/tool_done) | session state |
| `POST /permission` | `{machine,session,tool,hint}` → `{id}` | register a prompt |
| `GET /decision?id=&wait=` | — → `{decision: once\|deny\|timeout}` | long-poll for the device answer |
| `POST /button` | `{decision: once\|deny}` | manual A/B (transport-independent; works without the stick) |
| `GET /state` | — | debug snapshot (current heartbeat) |

### Heartbeat / device states
`total`, `running`, `waiting`, `tokens`, `entries[]` (machine-tagged), `msg`,
optional `prompt{id,tool,hint}`. Device states: `sleep` (disconnected),
`idle`, `busy` (running>0), `attention` (waiting>0, LED blinks), plus the
firmware's `celebrate`/`dizzy`/`heart`.

### Relay TCP protocol (`:8790`)
Newline-delimited JSON. On connect the hub sends `{"time":[epoch,offset]}`,
`{"cmd":"owner","name":...}`, then heartbeats. The relay forwards the stick's
lines back; `{"cmd":"permission","id","decision"}` resolves a prompt.

---

## The `tty` character

A minimalist living-terminal GIF pack (the cursor *is* the pet), generated in code:
```bash
python3 build_tty.py terra      # or: amber   → characters/tty/
```
Seven states map to CLI primitives: `sleep` (dim `$_`), `idle` (`$` blink + self-types
`ls`), `busy` (`$` spinner), `attention` (`allow? [y/n]` urgent), `celebrate`
(`lvl up` bar + sparkles), `dizzy` (glyph scramble), `heart` (pulsing ♥).

Loading it needs a **USB flash** (the wireless folder-drop is a desktop-app feature
this relay doesn't implement). The `flash_character.py` tool lives in the
[`claude-desktop-buddy`](https://github.com/anthropics/claude-desktop-buddy) repo:
```bash
usbipd attach --wsl --busid 4-3        # FTDI 0403:6001; bind persists
python3 path/to/claude-desktop-buddy/tools/flash_character.py characters/tty
# then on the stick: hold A → settings → species → GIF
```

---

## Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| A machine's activity never shows; its prompts hit the **terminal** not the stick | That session started **before** the hooks were installed. Restart it (hooks load at session start). |
| Activity shows but A/B does nothing | Session wasn't launched via `buddy` (no `BUDDY_CONTROL=1`) — ambient works, control doesn't. |
| `remote` silent | Check the tunnel: `systemctl --user status buddy-tunnel.service`; from remote `curl -m5 localhost:8787/state`. |
| Relay won't connect to hub | Hub up? `curl localhost:8787/state`. From Windows the hub is `127.0.0.1:8790` via WSL2 localhost-forwarding; if WSL switches to **mirrored networking** the address changes. |
| Stick stuck on `sleep` | Relay not connected / not paired. Check `C:\Users\<you>\buddy\relay.log`; re-pair (Forget in desktop app first). |
| Relay never finds / connects the stick (scan times out) | The **desktop app's background bridge is holding it** — it auto-reconnects even with its window closed. **Forget** the device in the app (or quit the app), then restart the relay. Only one central can connect at a time. |
| Firewall / interactive login (`gcloud`, passkey) | The relay's BLE pairing prompt appears on the Windows desktop — must be done in your user session. |

### Key facts
- The WSL host IP is **dynamic** (changes on WSL restart); the relay uses
  `127.0.0.1` so it doesn't care.
- Windows Python: `C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe` + `bleak`.
- Stick: M5StickC Plus, M5Stack **K016-P**, USB-serial FTDI `0403:6001` (usbipd busid `4-3`).
