# Single-URL Hub + Relay-Only Phone — Design

**Date:** 2026-06-10
**Status:** Approved (brainstorm), pending implementation plan
**Repo:** `ttpears/buddy-bridge` (no firmware changes — `claude-desktop-buddy`
speaks the same BLE newline-JSON protocol unchanged)

## Problem

Two pains, one root cause.

1. **The Android app can't be reached by remote machines.** The phone app folds
   *hub* + *relay* into one process and serves the hub HTTP API on `:8787`. That
   makes the phone the thing-that-must-be-reachable, but a phone on cellular /
   CGNAT / a changing IP is exactly the thing you *can't* reliably reach. Clients
   can't poll it.

2. **WSL is a second-class client.** Because the hub hides behind NAT, WSL needs
   the `buddyctl tunnel` reverse-tunnel dance. macOS has no documented client
   path at all.

Root cause: **the architecture assumes the hub is directly reachable.** Every
other component already dials *out* — clients POST `/event` and long-poll
`/decision`; `relay.py` opens an *outbound* TCP connection to the hub. The hub
never dials anyone. So the only component that must be reachable is the hub, and
the Android app broke that by making a phone play hub.

## Core principle

**Make the hub a real, deployable server on infrastructure you control. Every
other component — clients on all four OSes *and* the phone — is an outbound
client of one URL.** Nothing listens except the hub.

```
TODAY (phone-as-hub — broken)
  WSL box ──reverse tunnel──┐
  laptop  ──can't reach─────┼──►  📱 phone (hub+relay+BLE)  ──►  🟧 stick
  mac     ──can't reach─────┘         must be reachable ✗

PROPOSED (hub on company box behind Traefik — everything dials out)
  WSL box  ─┐
  Windows  ─┤
  Linux    ─┼──HTTPS one URL──►  🏢 hub  ◄──dials out── 📱 phone (relay+BLE) ──► 🟧 stick
  macOS    ─┘   buddy.<you>.<co>.<tld>   (or a desktop relay — interchangeable)
                └ dashboard, same URL
```

Deployment target: `https://buddy.<you>.<company>.<tld>` fronted by **Traefik**
(TLS terminated at the edge; app stays plain HTTP behind it). Bare
`http://host:8787` + token (LAN / Tailscale / no proxy) stays fully supported.

## Components & changes

### 1. Single-port hub — fold the relay stream into HTTP

The relay's raw TCP `:8790` socket is removed. Two new HTTP endpoints carry the
relay traffic over the same URL/port/token, so Traefik routes them as ordinary
HTTP (no TCP entrypoint, no SNI gymnastics):

| Endpoint | Direction | Shape |
| --- | --- | --- |
| `GET /relay/stream` | hub → relay | Long-lived chunked response; one newline-JSON heartbeat per line. The relay forwards each line to BLE **verbatim** (the stick protocol already *is* newline-JSON). |
| `POST /button` | relay → hub | `{ "decision": "once" \| "deny", ... }` — an A/B press. Resolves the current pending permission (existing `resolve_current`). |

- No WebSocket dependency — stays in stdlib `http.server`, consistent with the
  existing long-poll model.
- `relay.py`'s inner loop changes from `reader.readline()` on a socket to reading
  lines off the `/relay/stream` HTTP response; button notifications POST to
  `/button` instead of writing up the socket. The BLE half is untouched.
- The hub keeps exactly one relay-stream consumer "current" the way the TCP
  relay socket is today (last connection wins; heartbeats broadcast to it).

### 2. Auth hardening for an exposed URL

Today `BUDDY_TOKEN` gates only writes (`/event`, `/permission`, `/button`). Once
the hub lives at a public-ish hostname, the token gates **everything**:
`/relay/stream`, `/decision`, the dashboard, and all writes. Token travels as
`X-Buddy-Token` (existing) or `?token=` for stream GETs that can't set headers
easily. TLS is Traefik's job; the app-level token is the portable baseline that
also protects bare `host:port` deployments.

Docs ship two recipes: (a) the Traefik label/router snippet, (b) bare
`host:port + token`.

### 3. Android app — keep both modes, add relay-only

A mode toggle in the app:

- **Serve hub here** *(existing, kept)* — all-in-one phone: serves the hub HTTP
  API and drives BLE. Unchanged for the single-phone case.
- **Relay to remote hub** *(new — the fix)* — enter hub URL + token; the phone
  opens `GET /relay/stream`, drives the stick over BLE, and POSTs A/B presses to
  `/button`. Pure outbound client; identical contract to `relay.py`. Remote
  machines never address the phone, so cellular/CGNAT/changing-IP stop mattering.

App UX improvements (scope to confirm in plan): clearer mode switch, connection
status for the remote-hub case, token entry, reconnect/backoff on the
`/relay/stream` consumer mirroring `relay.py`'s supervise loop.

### 4. First-class install on all four platforms

One recipe everywhere:

```
buddyctl client install --hub https://buddy.<you>.<company>.<tld> --token …
```

- **WSL** — just a client; the reverse-tunnel path is gone.
- **Linux** — `systemd --user` (exists).
- **Windows** — Startup shortcut (exists). Fold `buddy.cmd` / `buddy-hook.cmd`
  env-var juggling into the config file so the wrappers read the same config the
  hook does.
- **macOS** — **new:** a `launchd` LaunchAgent install/uninstall path in
  `buddyctl` (today's gap).

### 5. Deletions

- `buddyctl tunnel` subcommand + `buddybridge/ctl/tunnel.py`.
- Forward/reverse SSH-tunnel recipes in the README.
- The `:8790` relay TCP server in `hub.py` and the socket client in `relay.py`.

Deleted outright (not deprecated), per decision.

## Data flow (unchanged in spirit)

1. Client hook fires → `POST /event` (busy/idle/tokens) and, on `PreToolUse`,
   `POST /permission` then long-poll `GET /decision?id=`.
2. Hub aggregates state → emits newline-JSON heartbeats on `GET /relay/stream`.
3. Relay (desktop `relay.py` **or** phone in relay-only mode) reads the stream →
   BLE → stick. A/B press → `POST /button` → hub resolves the pending
   permission → the waiting `/decision` long-poll returns the decision → hook
   emits the permission-decision JSON.
4. Dashboard (same URL) mirrors state and offers Approve/Deny for stickless use.

## Error handling

- Hub unreachable / no decision in time → hook stays silent, Claude Code falls
  back to its normal interactive prompt (existing "dead bridge never blocks"
  guarantee — preserved).
- `/relay/stream` drop → relay (both impls) reconnects with backoff; the stick
  shows `sleep` (bridge-not-connected) until the stream resumes.
- Bad/missing token → `401`; relay surfaces it instead of silently spinning.

## Testing

- Hub: token now required on `/relay/stream` and `/decision` (extend
  `test_hub_dashboard.py` / handler auth tests).
- Relay contract: a fake hub emitting `/relay/stream` lines + asserting `/button`
  POSTs, shared by the relay-loop test (Python side).
- `buddyctl` install/uninstall: macOS `launchd` path added to `test_ctl_*`;
  removal of `tunnel` reflected in `test_ctl_tunnel.py` (delete/replace).
- Packaging: ensure the `[relay]` extra and console entry points unchanged.

## Out of scope

- No cloud broker / rendezvous service (ruled out — company resources only).
- No firmware changes.
- No multi-tenant hub (single owner/deployment).
- E2E encryption of session hints beyond TLS-in-transit + token.

## Open questions for the plan

- Exact Android UI for the mode toggle + status (may warrant the visual
  companion when planning the app screen).
- Whether `buddy.cmd`/`buddy-hook.cmd` can be replaced by a `buddyctl`-generated
  shim rather than hand-edited wrappers.
