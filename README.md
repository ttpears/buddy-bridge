# buddy-bridge

[![CI](https://github.com/ttpears/buddy-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/ttpears/buddy-bridge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ttpears/buddy-bridge?sort=semver)](https://github.com/ttpears/buddy-bridge/releases/latest)
[![License: MIT](https://img.shields.io/github/license/ttpears/buddy-bridge)](LICENSE)
[![Firmware](https://img.shields.io/badge/firmware-ttpears%2Fclaude--desktop--buddy-orange)](https://github.com/ttpears/claude-desktop-buddy)

See your Claude **CLI** sessions from every machine on one **M5StickC Plus**
"Hardware Buddy" — busy/idle, permission prompts, and **approve/deny tool calls
with the stick's A/B buttons**, including prompts raised on a remote box. A web
dashboard mirrors everything for machines with no stick.

The firmware and BLE wire protocol come from
[`anthropics/claude-desktop-buddy`](https://github.com/anthropics/claude-desktop-buddy);
buddy-bridge speaks the same protocol but sourced from Claude Code hook events
across any number of machines. **Independent, unofficial — not affiliated with,
endorsed by, or supported by Anthropic.**

---

## One mental model: roles

Every machine plays one or more roles; `buddyctl` sets them up:

| Role | What it does | Needs |
| ---- | ------------ | ----- |
| **hub** | aggregates sessions from all machines + serves the dashboard | Python 3 |
| **relay** | drives the stick over Bluetooth | Python 3 + `bleak`, a BT radio |
| **client** | reports this machine's `claude` CLI sessions to the hub | Python 3 |

One box can be all three. Extra machines are just **clients** pointed at the hub —
that's the whole multi-machine story.

```
  server A ─┐
  server B ─┼──HTTP :8787──►  hub  ──BLE──►  🟧 stick
  server C ─┘                 └─ dashboard :8787 (approve/deny in a browser)
```

> **Using the Claude desktop app?** Its built-in Hardware Buddy and the bridge's
> relay both want the stick, and BLE allows only **one** owner — they'll fight over
> it (the stick visibly flaps between states every ~15s). To let the bridge own it:
> in the app, **Developer → Hardware Buddy → Forget**, and leave it forgotten
> (closing the window isn't enough — its bridge auto-reconnects in the background).
> Without the app running this never comes up.

---

## Repositories & releases

Two repos make up the project, plus the upstream they descend from:

| Repo | What lives there | Releases ship |
| ---- | ---------------- | ------------- |
| [**ttpears/buddy-bridge**](https://github.com/ttpears/buddy-bridge) (this repo) | the Python **hub / relay / client** (`buddyctl`) and the **Android bridge app** | the **Android APK** (`vX.Y.Z` → [Releases](https://github.com/ttpears/buddy-bridge/releases)) |
| [**ttpears/claude-desktop-buddy**](https://github.com/ttpears/claude-desktop-buddy) | our **fork of the M5StickC Plus firmware** — the code that runs *on the stick* — plus the BLE wire protocol (`REFERENCE.md`) | a **flashable firmware image** (`firmware.bin`, [Releases](https://github.com/ttpears/claude-desktop-buddy/releases)) |
| [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy) | the original upstream firmware our fork descends from | — |

How they connect: this repo turns **Claude Code hook events** (from any number of
machines) into the same newline-JSON BLE heartbeat protocol that the **firmware**
expects — so buddy-bridge drives the exact stick the firmware fork builds.
Flash the stick from the firmware fork's release, install the hub/relay (or the
Android app) from here, and the two halves meet over Bluetooth.

> **Unofficial & independent** — not affiliated with, endorsed by, or supported
> by Anthropic. The firmware fork tracks `anthropics/claude-desktop-buddy`.

---

## Install

One `pipx` package, one command (`buddyctl`), on every OS. `buddyctl` registers
background services itself — a **Startup shortcut** on Windows, a `systemd --user`
unit on Linux/WSL.

```bash
pipx install "git+https://github.com/ttpears/buddy-bridge"            # hub + client
pipx install "buddy-bridge[relay] @ git+https://github.com/ttpears/buddy-bridge"   # + BLE on the relay box
```

### Recipe 1 — one machine does everything

On the box with the Bluetooth radio:

```bash
buddyctl hub   install        # aggregator + dashboard at http://localhost:8787
buddyctl relay install        # drives the stick (pair once — see below)
buddyctl client install       # report THIS machine's CLI sessions
```

Open `http://localhost:8787` for the dashboard. Launch stick-controlled sessions
with `buddy`; plain `claude` stays ambient-only.

### Recipe 2 — add another server (the fan-in)

On each additional machine:

```bash
buddyctl client install --hub http://HUBHOST:8787 --name workstation
```

It appears on the dashboard and stick immediately. `--name` defaults to the
hostname. Restart any running `claude` session to load the hooks.

### Recipe 3 — tunnels (only if the hub isn't directly reachable)

A tunnel just makes a remote hub look **local** to the client.

- **Forward** (client dials the hub — the usual case):
  ```bash
  buddyctl client install --tunnel HUB_SSH_HOST --name workstation
  ```
- **Reverse** (the hub is in **WSL** / behind NAT, so it dials out). Run on the hub:
  ```bash
  buddyctl tunnel install --to CLIENT_SSH_HOST
  ```
  then on the client use `--hub http://127.0.0.1:8787` with no tunnel of its own.

---

## `buddyctl` reference

```
buddyctl hub     install [--port --transport --owner] | uninstall
buddyctl relay   install [--hub] | uninstall | pair
buddyctl client  install [--hub URL] [--name NAME] [--tunnel SSH_HOST] | uninstall | status
buddyctl tunnel  install --to SSH_HOST | uninstall
buddyctl status
```

- `--hub` defaults to `http://127.0.0.1:8787`; `--name` to the hostname. These are
  saved to a per-machine config (`~/.config/buddybridge/config.json`, or `%APPDATA%`
  on Windows) that the hook reads — so the same install works on every OS.
- `install` is idempotent; `uninstall` removes only what buddyctl added.
- **Optional auth:** set `BUDDY_TOKEN` (env, or `"token"` in the config file) and the
  hook sends it as an `X-Buddy-Token` header. Useful when the hub is reachable over a
  network (e.g. the Android app below) rather than just localhost. It must match the
  token configured on whatever is serving the hub.

---

## Daily use

```bash
buddy                 # a session whose approvals route to the stick (A/B)
claude                # normal session — ambient only (busy/idle), no interception
```

`buddy` is a console command installed with the package (it runs `claude` with
`BUDDY_CONTROL=1`). The **web dashboard** (`http://HUBHOST:8787/`) shows live state
and Approve/Deny buttons — the bridge is fully usable with no stick at all.

---

## Pairing the stick (one-time, relay machine)

1. If the Claude desktop app held the stick: **Developer → Hardware Buddy → Forget**.
2. Wake the stick; confirm Bluetooth is on (hold A → settings → bluetooth).
3. `buddyctl relay pair` — enter the 6-digit passkey the stick shows. The relay
   holds that passkey on screen for 60s while you type it.

---

## Android bridge app (alternative to the relay machine)

Instead of running `buddyhub` + `buddy-relay` on a desk machine, the `android/`
app folds both into a single phone app: it talks BLE to the stick and serves the
same hub HTTP API on port `8787`. This replaces the WSL-hub-plus-Windows-relay
topology when you'd rather the bridge live on a phone that's always with you.

**Install (easiest — prebuilt APK):**

1. Grab `buddy-bridge-<version>-debug.apk` from the
   [**Releases**](https://github.com/ttpears/buddy-bridge/releases/latest) page
   (verify it against the release's `SHA256SUMS` if you like).
2. Copy it to the phone and tap to install — allow "install unknown apps" for
   whatever opens it. The build is debug-signed with a **stable** keystore, so
   later versions install over the top without uninstalling first.
3. First launch: grant **Bluetooth** (and, on Android ≤ 11, **Location**) plus
   **Notifications**, and set the app **Unrestricted** under Battery so its
   foreground service survives. Set an **Owner** name and (optionally) a
   **Buddy Token**, then tap **Start**.
4. Point your machines at the phone: `BUDDY_HUB=http://<phone-ip>:8787` and a
   matching `BUDDY_TOKEN` — typically over **Tailscale/VPN** so the phone is
   reachable from your dev boxes.

> Prefer to build it yourself? `cd android && ./gradlew assembleDebug` (JDK 17 +
> Android SDK) → `android/app/build/outputs/apk/debug/app-debug.apk`. Every push
> to `main` also builds the APK as a CI artifact, and tagging `vX.Y.Z` cuts a
> Release with the APK attached automatically.

## Windows clients

For a Windows machine running `claude`, two `.cmd` wrappers avoid hand-setting
env vars each time:

- `buddy-hook.cmd` — wraps the hook; set `BUDDY_HUB` (and `BUDDY_TOKEN`) at the top.
- `buddy.cmd` — launches Claude Code with `BUDDY_CONTROL=1` (the Windows analog of
  the `buddy` launcher).

If the package is installed via pip/pipx, `buddyctl client install` already wires
hooks and registers a Startup launcher — use the `.cmd` files for the
quick/manual case (e.g. pointing a laptop at the Android hub).

---

## Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| Stick flaps between states / relay connect-disconnect loop | The desktop app is fighting the relay for the stick. **Forget** Hardware Buddy in the app (and leave it forgotten), then `buddyctl relay uninstall && buddyctl relay install`. |
| A machine's activity never shows | Its `claude` session started **before** hooks were installed — restart it. Or check `buddyctl status`. |
| Activity shows but A/B does nothing | Session wasn't launched via `buddy` (no `BUDDY_CONTROL=1`) — ambient works, control doesn't. |
| Remote machine silent | Hub reachable from it? `curl -m5 http://HUBHOST:8787/state`. Tunnel up? `buddyctl status`. |
| Relay never finds the stick | Desktop app still holds it (Forget it), or it isn't paired: `buddyctl relay pair`. |
| `buddy-relay` says it needs Bluetooth | Install the extra: `pipx install "buddy-bridge[relay] @ git+…"`. |

---

## Develop

```bash
git clone https://github.com/ttpears/buddy-bridge && cd buddy-bridge
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,relay]"
pytest
```

Roles run directly as modules too: `python -m buddybridge.hub`,
`python -m buddybridge.relay`, `python -m buddybridge.ctl`. Regenerate the `tty`
character pack with `build-tty terra` (needs the `[tty]` extra).

CI runs `pytest` on every PR (`main` is protected and requires it). Tagging
`vX.Y.Z` builds and publishes the Android APK to Releases.

---

## Credits

- **[@ToxicOrca](https://github.com/ToxicOrca)** — the **Android bridge app**,
  the bridge **battery optimizations** (adaptive heartbeat, heartbeat dedup,
  stale-session/transcript fixes), **token auth** (`BUDDY_TOKEN`), and the
  **Windows wrappers**. Matching battery-life work on the firmware fork too.
- The firmware and BLE wire protocol descend from
  [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy).
