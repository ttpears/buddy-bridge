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

**Contents**

- [Quickstart](#-quickstart)
- [Which setup is mine?](#-which-setup-is-mine)
- [Install](#-install) & [`buddyctl` reference](#-buddyctl-reference)
- [Daily use](#-daily-use) & [pairing the stick](#-pairing-the-stick-one-time-relay-machine)
- [Android bridge app](#-android-bridge-app-alternative-to-the-relay-machine)
- [Linux](#-linux-clients), [macOS](#-macos-clients) & [Windows](#-windows-clients) clients
- [Troubleshooting](#-troubleshooting)
- [Develop](#-develop)

## 🚀 Quickstart

The common case — **one machine that has a Bluetooth radio, plus a stick.** Other
setups (more machines, a phone, a public hub) are in
[Which setup is mine?](#-which-setup-is-mine).

1. **Flash the stick.** Grab the firmware image from
   [claude-desktop-buddy Releases](https://github.com/ttpears/claude-desktop-buddy/releases/latest)
   and flash it (steps in that repo's README).
2. **Install the bridge** on the box with the Bluetooth radio:
   ```bash
   pipx install "buddy-bridge[relay] @ git+https://github.com/ttpears/buddy-bridge"
   buddyctl hub install && buddyctl relay install && buddyctl client install
   buddyctl relay pair      # type the 6-digit code the stick shows
   ```
3. **Use it.** Open the dashboard at `http://localhost:8787`, and start
   stick-controlled sessions with `buddy` (plain `claude` stays ambient-only).

That's the whole loop. Adding more machines is one `buddyctl client install` each —
see [Install](#-install).

## 🧩 One mental model: roles

Every machine plays one or more roles; `buddyctl` sets them up:

| Role | What it does | Needs |
| ---- | ------------ | ----- |
| **hub** | aggregates sessions from all machines + serves the dashboard | Python 3 |
| **relay** | drives the stick over Bluetooth | Python 3 + `bleak`, a BT radio |
| **client** | reports this machine's `claude` CLI sessions to the hub | Python 3 |

One box can be all three. Extra machines are just **clients** pointed at the hub —
that's the whole multi-machine story.

```
  WSL box  ─┐
  Windows  ─┤
  Linux    ─┼──HTTPS one URL──►  🏢 hub  ◄──dials out── 📱 phone (relay+BLE) ──► 🟧 stick
  macOS    ─┘   buddy.<you>.<co>.<tld>   (or a desktop relay — interchangeable)
                └ dashboard, same URL
```

The relay — whether a desktop machine or the phone — dials **out** to the hub, so
nothing but the hub needs to be reachable from the internet.

> **Using the Claude desktop app?** Its built-in Hardware Buddy and the bridge's
> relay both want the stick, and BLE allows only **one** owner — they'll fight over
> it (the stick visibly flaps between states every ~15s). To let the bridge own it:
> in the app, **Developer → Hardware Buddy → Forget**, and leave it forgotten
> (closing the window isn't enough — its bridge auto-reconnects in the background).
> Without the app running this never comes up.

## 📚 Repositories & releases

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

## 🧭 Which setup is mine?

Pick the row that matches you, then jump to the matching section below.

| Your situation | What to set up |
| -------------- | -------------- |
| One machine that has the Bluetooth radio **and** the stick | **Recipe 1** — `hub` + `relay` + `client` on that one box |
| Several machines feeding one stick | **Recipe 2** — stand up a `hub` once, then `client install` on each machine |
| The stick rides on your **phone** (no desktop Bluetooth, or you're mobile) | **[Android app](#-android-bridge-app-alternative-to-the-relay-machine)**, *Relay to remote hub* mode — phone drives BLE and dials out to your hub |
| Your **phone is the whole rig** (hub + stick in one) | **[Android app](#-android-bridge-app-alternative-to-the-relay-machine)**, *Serve hub here* mode — point machines at `http://<phone-ip>:8787` |
| The hub must be reachable **over the internet** | Run a **[public hub](#public-hub-docker--traefik)** (Docker + Traefik, automatic TLS) |
| **No stick at all** | Any hub — drive it from the web **dashboard's** Approve/Deny buttons |

Most people are one of the first two rows. Everything else just changes *where the
relay lives* (a desktop box, or the phone) and *how machines reach the hub*.

## 📦 Install

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
buddyctl client install --hub https://buddy.<you>.<company>.<tld> --token YOUR_TOKEN --name workstation
```

It appears on the dashboard and stick immediately. `--name` defaults to the
hostname. Restart any running `claude` session to load the hooks.

### Public hub (Docker + Traefik)

To run the hub on a public server, use the committed compose file
[`deploy/docker-compose.yml`](deploy/docker-compose.yml). It brings up Traefik
with automatic Let's Encrypt TLS in front of the hub, and the hub is **never
published to the host** — only Traefik reaches it, over the internal network.

> **A public hub must be secured.** The compose **refuses to start without a
> `BUDDY_TOKEN`**, and with a token set the hub gates *every* route — events, the
> relay stream, and the dashboard. Traefik forces HTTPS. Use a long random token
> (`openssl rand -hex 32`), not a guessable one.

1. Point a DNS `A` record at the host and open ports **80** and **443**.
2. Fill in the environment:
   ```bash
   cd deploy
   cp .env.example .env       # set HUB_DOMAIN, ACME_EMAIL, and a strong BUDDY_TOKEN
   ```
3. Bring it up:
   ```bash
   docker compose up -d
   ```
4. Point each machine at it (token required):
   ```bash
   buddyctl client install --hub https://buddy.<you>.<co>.<tld> --token "$BUDDY_TOKEN" --name workstation
   ```
   A desktop relay or the phone connects the same way (it dials the hub's
   `/relay/stream`). Open the dashboard at
   `https://buddy.<you>.<co>.<tld>/?token=YOUR_TOKEN`.

**Already running Traefik?** Use
[`deploy/docker-compose.existing-traefik.yml`](deploy/docker-compose.existing-traefik.yml)
instead — it's just the hub, joined to your Traefik's external network (set
`TRAEFIK_NETWORK` in `.env`). It uses `tls=true` (Traefik's default cert, e.g. a
mounted wildcard); if your Traefik issues certs via ACME, add a
`traefik.http.routers.buddyhub.tls.certresolver=<name>` label.

```bash
docker compose -f docker-compose.existing-traefik.yml up -d
```

For LAN or Tailscale (no public exposure) you don't need any of this — just point
clients at the bare hub:

```bash
buddyctl client install --hub http://HUBHOST:8787 --token YOUR_TOKEN
```

## 📖 `buddyctl` reference

```
buddyctl hub     install [--port --transport --owner] | uninstall
buddyctl relay   install [--hub URL] | uninstall | pair
buddyctl client  install [--hub URL] [--name NAME] | uninstall | status
buddyctl status
```

- `--hub` takes a full URL (e.g. `https://buddy.<you>.<co>.<tld>` or
  `http://127.0.0.1:8787` for localhost). Defaults to `http://127.0.0.1:8787`.
  `--name` defaults to the hostname. Both are saved to a per-machine config
  (`~/.config/buddybridge/config.json`, or `%APPDATA%` on Windows) that the hook
  reads — so the same install works on every OS.
- `install` is idempotent; `uninstall` removes only what buddyctl added.
- **Auth:** set `BUDDY_TOKEN` (env, or `"token"` in the config file) and the hook
  sends it as an `X-Buddy-Token` header. Required when the hub is exposed over a
  network. It must match the token configured on the hub. With a token set every
  route is gated — including the dashboard, so open it as
  `http://HUBHOST:8787/?token=YOUR_TOKEN` (the hub also accepts the token on the
  `?token=` query for browsers and the BLE relay stream).

## 💻 Daily use

```bash
buddy                 # a session whose approvals route to the stick (A/B)
claude                # normal session — ambient only (busy/idle), no interception
```

`buddy` is a console command installed with the package (it runs `claude` with
`BUDDY_CONTROL=1`). The **web dashboard** (`http://HUBHOST:8787/`) shows live state
and Approve/Deny buttons — the bridge is fully usable with no stick at all.

## 🔌 Pairing the stick (one-time, relay machine)

1. If the Claude desktop app held the stick: **Developer → Hardware Buddy → Forget**.
2. Wake the stick; confirm Bluetooth is on (hold A → settings → bluetooth).
3. `buddyctl relay pair` — enter the 6-digit passkey the stick shows. The relay
   holds that passkey on screen for 60s while you type it.

## 📱 Android bridge app (alternative to the relay machine)

The `android/` app has two modes, selectable from a toggle in the UI:

- **Serve hub here** — the phone runs the full hub + BLE relay, exactly as before.
  All-in-one: point your dev machines at `http://<phone-ip>:8787` (works over
  Tailscale/LAN when the phone is reachable).
- **Relay to remote hub** — enter a hub URL and token; the phone drives BLE and
  dials **out** to your hub. Works on cellular or NAT — nothing connects *to* the
  phone. This is the recommended mode when you have a server-side hub.

**Install (easiest — prebuilt APK):**

1. Grab `buddy-bridge-<version>-debug.apk` from the
   [**Releases**](https://github.com/ttpears/buddy-bridge/releases/latest) page
   (verify it against the release's `SHA256SUMS` if you like).
2. Copy it to the phone and tap to install — allow "install unknown apps" for
   whatever opens it. The build is debug-signed with a **stable** keystore, so
   later versions install over the top without uninstalling first.
3. First launch: grant **Bluetooth** (and, on Android ≤ 11, **Location**) plus
   **Notifications**, and set the app **Unrestricted** under Battery so its
   foreground service survives. Set an **Owner** name and a **Buddy Token**, then
   select your mode and tap **Start**.
4. **Relay mode:** enter the hub URL (e.g. `https://buddy.<you>.<co>.<tld>`) and
   token — the phone dials out, no inbound access needed.
   **Hub mode:** point your dev machines at `http://<phone-ip>:8787` with a
   matching token, typically over Tailscale/LAN.

> Prefer to build it yourself? `cd android && ./gradlew assembleDebug` (JDK 17 +
> Android SDK) → `android/app/build/outputs/apk/debug/app-debug.apk`. Every push
> to `main` also builds the APK as a CI artifact, and tagging `vX.Y.Z` cuts a
> Release with the APK attached automatically.

## 🐧 Linux clients

Linux (and WSL) is the baseline the recipes above already use:
`buddyctl client install` registers a **`systemd --user`** unit, so the hook runs
at login — same single command, nothing extra.

```bash
buddyctl client install --hub <URL> --token … --name workstation
```

> **WSL:** the hub usually lives elsewhere (a server, or the Windows side) — point
> `--hub` at it, over Tailscale or a tunnel if it isn't directly reachable. The
> `systemd --user` unit needs systemd enabled in WSL (`/etc/wsl.conf` →
> `[boot]` `systemd=true`).

## 🍎 macOS clients

`buddyctl client install --hub <URL> --token …` registers a **launchd LaunchAgent**
on macOS — the same single command as Linux, WSL, and Windows. No extra steps.

## 🪟 Windows clients

No Python, no pip, no CLI — just a small app.

1. Download **`buddy-bridge-win64.zip`** from the
   [Releases](https://github.com/ttpears/buddy-bridge/releases/latest) page and
   unzip it anywhere.
2. Run **`buddy.exe`**. A setup window asks for your **hub URL**, **token**, and
   this machine's **name**; click **Connect**.

That's it. It wires the Claude Code hooks, installs itself to a stable per-user
spot so the download folder is disposable, and lives in the **system tray** —
showing connection status, with **Settings**, **Pause reporting**, and
**Remove** (uninstall) in its menu. It starts automatically at login.

The tray app is monitor + config only; approvals stay on the stick or the web
dashboard. The exe is also the hook (`buddy.exe hook`), which posts straight to
the hub — so reporting keeps working even if you close the tray app. Settings
live in `%APPDATA%\buddybridge\config.json`, the same config the other roles use.

> Prefer the CLI? `pipx install` + `buddyctl client install` still works on
> Windows exactly like the other platforms — the tray app is just the
> no-Python path.

## 🩺 Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| Stick flaps between states / relay connect-disconnect loop | The desktop app is fighting the relay for the stick. **Forget** Hardware Buddy in the app (and leave it forgotten), then `buddyctl relay uninstall && buddyctl relay install`. |
| A machine's activity never shows | Its `claude` session started **before** hooks were installed — restart it. Or check `buddyctl status`. |
| Activity shows but A/B does nothing | Session wasn't launched via `buddy` (no `BUDDY_CONTROL=1`) — ambient works, control doesn't. |
| Remote machine silent | Hub reachable from it? `curl -m5 https://HUBHOST/state`. Check `buddyctl status` and verify `--hub` URL and token are set. |
| Relay never finds the stick | Desktop app still holds it (Forget it), or it isn't paired: `buddyctl relay pair`. |
| `buddy-relay` says it needs Bluetooth | Install the extra: `pipx install "buddy-bridge[relay] @ git+…"`. |

## 🔧 Develop

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

## 🙌 Credits

- **[@ToxicOrca](https://github.com/ToxicOrca)** — the **Android bridge app**,
  the bridge **battery optimizations** (adaptive heartbeat, heartbeat dedup,
  stale-session/transcript fixes), **token auth** (`BUDDY_TOKEN`), and the
  **Windows wrappers**. Matching battery-life work on the firmware fork too.
- The firmware and BLE wire protocol descend from
  [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy).
