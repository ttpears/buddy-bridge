# buddy-bridge (DRAFT — becomes README.md when buddyctl ships)

> **Status:** This documents the *target* `pipx` + `buddyctl` experience (Plans 2–3).
> It is the spec the CLI is built against. The live `README.md` describes the
> current relay/`manage.ps1` system until the package lands, then this replaces it.

See your Claude **CLI** sessions from every machine on one **M5StickC Plus** — busy/idle,
permission prompts, and **approve/deny tool calls with the stick's A/B buttons**,
including prompts raised on a remote box. A web dashboard mirrors it for machines
with no stick.

The firmware and BLE protocol come from
[`anthropics/claude-desktop-buddy`](https://github.com/anthropics/claude-desktop-buddy);
buddy-bridge speaks the same protocol but sourced from Claude Code hook events
across any number of machines. Independent, unofficial; not affiliated with Anthropic.

---

## One mental model

Every machine plays one or more **roles**:

| Role | What it does | Needs |
| ---- | ------------ | ----- |
| **hub** | aggregates sessions from all machines + serves the dashboard | Python 3 |
| **relay** | drives the stick over Bluetooth | Python 3 + `bleak`, a BT radio |
| **client** | reports this machine's `claude` CLI sessions to the hub | Python 3 |

One box can be all three. Extra machines are just **clients** pointed at the hub.
**"Send another server to the hub" = install the client role on it.** The hub
aggregates everyone; the dashboard and stick show them all.

```
  server A ─┐
  server B ─┼──HTTP :8787──►  hub  ──BLE──►  🟧 stick
  server C ─┘                 └─ dashboard :8787 (approve/deny in a browser)
```

> **Using the Claude desktop app?** Its built-in Hardware Buddy and the bridge's
> relay both want the stick, and BLE allows only **one** owner — they'll fight over
> it (the stick visibly flaps). Pick one. To let the bridge own it: in the app,
> **Developer → Hardware Buddy → Forget**, and leave it forgotten. Without the app
> running this never comes up.

---

## Install

Everything is one `pipx` package and one command, `buddyctl`, on every OS.

```bash
pipx install buddy-bridge            # hub + client roles
pipx install "buddy-bridge[relay]"   # add this on the Bluetooth machine (pulls bleak)
```

`buddyctl` registers background services for you — a **Startup shortcut** on
Windows, a **`systemd --user`** unit on Linux/WSL.

### Recipe 1 — one machine does everything

On the box with the Bluetooth radio:

```bash
pipx install "buddy-bridge[relay]"
buddyctl hub install        # aggregator + dashboard at http://localhost:8787
buddyctl relay install      # drives the stick (pair once — see Pairing)
buddyctl client install     # report THIS machine's CLI sessions
```

Open `http://localhost:8787` for the dashboard. Launch stick-controlled sessions
with `buddy` (plain `claude` stays ambient-only).

### Recipe 2 — add another server (the fan-in)

On each additional machine, one command:

```bash
pipx install buddy-bridge
buddyctl client install --hub http://HUBHOST:8787 --name workstation
```

It shows up on the dashboard and stick immediately. `--name` is what's displayed;
defaults to the hostname. That's the whole multi-machine story.

### Recipe 3 — tunnels (only if the hub isn't directly reachable)

A tunnel just makes a remote hub look **local** to the client. You only need one
when the hub is behind a firewall/NAT or in WSL.

- **Forward (default, client dials the hub):**
  ```bash
  buddyctl client install --tunnel HUB_SSH_HOST --name workstation
  ```
  `buddyctl` opens an SSH forward tunnel (`ssh -L 8787:localhost:8787 HUB_SSH_HOST`)
  as a background service and points the hooks at `127.0.0.1:8787`.

- **Reverse (hub in WSL, hub dials out):** when the hub lives in WSL it's hard to
  reach inbound, so the *hub* pushes the tunnel to the client instead. Set this up
  on the hub:
  ```bash
  buddyctl tunnel install --to CLIENT_SSH_HOST   # ssh -R 8787:localhost:8787 CLIENT
  ```
  The client then uses `--hub http://127.0.0.1:8787` with no tunnel of its own.

---

## `buddyctl` reference

```
buddyctl hub     install | status | uninstall
buddyctl relay   install | status | uninstall | pair
buddyctl client  install [--hub URL] [--name NAME] [--tunnel SSH_HOST] | status | uninstall
buddyctl tunnel  install --to SSH_HOST | uninstall      # reverse tunnel (hub side)
buddyctl status                                          # everything this machine runs
```

- `--hub` defaults to `http://127.0.0.1:8787`; `--name` defaults to the hostname.
- `install` is idempotent and re-runnable; `uninstall` removes only what buddyctl added.
- Services: Windows Startup shortcut (`%APPDATA%\…\Startup`), Linux `systemd --user`
  unit (`~/.config/systemd/user/`). `buddyctl ... uninstall` removes them.

---

## Daily use

```bash
buddy                 # a session whose approvals route to the stick (A/B)
claude                # normal session — ambient only (busy/idle), no interception
```

`buddy` is a console command installed with the package; it just runs `claude`
with `BUDDY_CONTROL=1`. The **web dashboard** (`http://HUBHOST:8787/`) shows live
state and Approve/Deny buttons, so the bridge is fully usable with no stick at all.

---

## Pairing the stick (one-time, relay machine)

1. If the Claude desktop app held the stick: **Developer → Hardware Buddy → Forget**.
2. Wake the stick; confirm Bluetooth is on (hold A → settings → bluetooth).
3. `buddyctl relay pair` — enter the 6-digit passkey the stick shows. The relay
   keeps that passkey on screen for 60s while you type it (`--pair-timeout`).

---

## Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| Stick flaps between states / relay connect-disconnect loop | The desktop app is fighting the relay for the stick. **Forget** Hardware Buddy in the app (and leave it forgotten), then `buddyctl relay restart`. |
| A machine's activity never shows | Its `claude` session started **before** hooks were installed — restart it. Or hooks aren't installed: `buddyctl client status`. |
| Activity shows but A/B does nothing | Session wasn't launched via `buddy` (no `BUDDY_CONTROL=1`) — ambient works, control doesn't. |
| Remote machine silent | Hub reachable from it? `curl -m5 http://HUBHOST:8787/state`. If using a tunnel, `buddyctl client status` shows whether it's up. |
| Relay never finds the stick | Desktop app still holds it (Forget it), or it's not paired: `buddyctl relay pair`. |

---

## Drive the stick from Linux

The relay runs on any machine with a Bluetooth radio, not just Windows:
`pipx install "buddy-bridge[relay]"` then `buddyctl relay install` works on Linux
(BlueZ) and Windows alike. Put it wherever the stick physically lives.
