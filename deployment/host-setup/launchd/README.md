# LaunchAgents and LaunchDaemons

macOS launchd templates. Most are **LaunchAgents** (`gui/<uid>` scope,
per-user, runs after login). One is a **LaunchDaemon**
(`com.ywatanabe.colima-caffeinate`, system scope, root-owned, runs at
boot without login).

Each `*.plist` here pairs with an `install-*.sh` under
`scripts/client/` that copies the template into the right system path
and bootstraps it via `launchctl`.

## `com.scitex.fleet-host-liveness-probe.plist`

scitex-orochi#271. Runs the fleet host-liveness probe every 5 minutes
to detect tmux-server death and missing expected agents across the
fleet, then auto-revives via healer delegation or direct SSH.

Authored after the 2026-04-20 incident where both `ywata-note-win`
and `spartan` lost their tmux servers and nobody noticed for hours.
The memory / discipline layer did not save us; this is an
implementation lever that actually runs every ~5 min.

Install (default: auto-revive enabled):

```bash
./scripts/client/install-fleet-host-liveness-probe.sh
```

Install in observation-only mode (no revive):

```bash
./scripts/client/install-fleet-host-liveness-probe.sh --dry-run-only
```

Uninstall:

```bash
./scripts/client/install-fleet-host-liveness-probe.sh --uninstall
```

Status / logs:

```bash
launchctl list | grep com.scitex.fleet-host-liveness-probe
tail -n 200 ~/Library/Logs/scitex/fleet-host-liveness-probe.log
```

Output:
- `stdout` — one NDJSON line per fleet host (schema
  `scitex-orochi/host-liveness-probe/v1`) with severity, expected vs.
  alive agents, missing, unexpected, and actions taken.
- `stderr` — human-readable advisories for non-OK hosts.
- Exit code follows the disk-pressure-probe convention: 0 ok,
  1 advisory, 2 warn, 3 critical. LaunchAgent ignores exit code; the
  signal is in the NDJSON and the revive actions.

Source of truth for "expected agents" per host: the
`expected_tmux_sessions:` key in `orochi-machines.yaml` at the repo
root. Keep that file in sync with live fleet naming to avoid false
"missing"/"unexpected" drift.

## `com.scitex.chrome-codesign-watchdog.plist`

scitex-orochi#286 item 2. Periodically reaps the Chrome
`code_sign_clone` cache leak that contributed to the 2026-04-21
full-disk outage.

Install:

```bash
./scripts/client/install-chrome-codesign-watchdog.sh
```

Uninstall:

```bash
./scripts/client/install-chrome-codesign-watchdog.sh --uninstall
```

Status / logs:

```bash
launchctl list | grep com.scitex.chrome-codesign-watchdog
tail -n 50 ~/Library/Logs/scitex/chrome-codesign-watchdog.log
```

Thresholds (tune per host by editing the `EnvironmentVariables` block
in the installed plist and re-running the install helper):

- `ADVISE_GIB` (default 2) — log an advisory at this size
- `REAP_GIB` (default 5) — `rm -rf` the cache at this size

See `skills/infra-hub-docker-disk-full.md` for why this cache is
reaper-safe.

## `com.ywatanabe.colima-caffeinate.plist` (LaunchDaemon)

scitex-orochi 2026-04-27 incident — Cloudflare 502 bursts on the mba
hub recurring roughly every minute. Lima HostAgent log showed
`Time sync: guest clock adjusted (was -18668ms off)` events: macOS App
Nap / Virtualization.framework was suspending the colima VM, which
killed the SSH-MUX port-forward that bridges the container's :8559 to
the mac host. Daphne stayed healthy; the host-side bridge died.

This template runs `caffeinate -dimsu -w <limactl-hostagent-pid>` in a
re-attaching loop so macOS cannot suspend the VM. Installed as a
LaunchDaemon (root, system scope) so it survives reboot without
needing the user to be logged in.

Install:

```bash
./scripts/client/install-colima-caffeinate.sh
```

Uninstall:

```bash
./scripts/client/install-colima-caffeinate.sh --uninstall
```

Status / logs:

```bash
launchctl print system/com.ywatanabe.colima-caffeinate | head -20
tail -n 50 ~/Library/Logs/colima-caffeinate.log
```

Verification (before fix saw 9-in-a-row 502 bursts; after fix should
be 30/30 success):

```bash
for i in $(seq 1 30); do
  curl -s -o /dev/null -w "%{http_code}\n" https://scitex-lab.scitex-orochi.com/
  sleep 2
done
```

See `~/.scitex/orochi/shared/skills/scitex-orochi-private/infra-hub-stability.md`
§"2026-04-27 Incident Post-Mortem — Colima VM Suspension" for the
full diagnostic chain.
