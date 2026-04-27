# LaunchAgents

macOS LaunchAgent templates installed per-user to protect host disk /
run client-side maintenance without interfering with the container.

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
  orochi_alive agents, missing, unexpected, and actions taken.
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
