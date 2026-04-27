# fleet tmux unstick — Phase 1 MVP

Phase 1 of the `fleet-health-daemon` (scitex-orochi#146, PR #147). Periodic
detection + automatic recovery of stuck Claude Code sessions inside tmux
panes. Scope-limited to the two wedge patterns that have actually bitten
the fleet today:

1. **paste-buffer-unsent** — prompt shows `[Pasted text #N +M lines]` and
   has not been submitted. Recovery: `tmux send-keys Enter`.
2. **permission-prompt** — numbered menu like `1. Yes / 2. Yes, always
   allow / 3. No` or a `Do you want to …?` text. Recovery:
   `tmux send-keys "2" Enter` (option 2 is usually "Yes, always allow",
   the safest bypass).

Both recoveries are idempotent — sending Enter to a pane that is already
at an empty prompt does nothing harmful — so the periodic sweep can run
forever without coordinating across iterations.

## Why this exists

`ywatanabe msg#11943` (2026-04-15):

> なんかやっぱりこちらからするとみんな数時間止まってるように見えるので、
> 実際止まってた？、定期的なハンドシェイク、ウェイクアップで24時間稼働の
> 仕組みを作って欲しいです

Today the fleet has hit five independent wedge incidents (healer-nas 2.5h
ghost-alive, synchronizer permission prompt, healer-mba 1M-context wedge,
auth-manager permission prompt, head-nas permission prompt). Each needed
a human tmux `send-keys` pass. The fleet-health-daemon design
(scitex-orochi#147) codifies the full 3-layer nonce-handshake orochi_model, but
the *minimum viable* piece that unblocks 24 h operation is just this:
scheduled tmux pane capture + regex match + idempotent recovery. That is
this deployment.

## Canonical locations

- **Script**: `deployment/fleet/tmux-unstick.sh`
  (promoted verbatim from head-mba's POC at
  `~/.scitex/orochi/scripts/tmux-unstick-poc.sh`, msg#11824, MBA live
  verified).
- **Log**: `~/.scitex/orochi/logs/tmux-unstick.ndjson`
  (NDJSON, one record per detection + one summary per sweep).
- **Host-specific wrappers**:
  - macOS (MBA): `deployment/fleet/launchd/com.scitex.orochi.tmux-unstick.plist`
  - Linux with per-user systemd (NAS, WSL):
    `deployment/fleet/systemd/scitex-orochi-tmux-unstick.service` + `.timer`
  - Spartan (no sudo, no per-user systemd):
    `deployment/fleet/tmux-unstick-spartan-loop.sh`

## Installation matrix

### MBA (head-mba lane)

```
ln -sf ~/proj/scitex-orochi/deployment/fleet/launchd/com.scitex.orochi.tmux-unstick.plist \
       ~/Library/LaunchAgents/com.scitex.orochi.tmux-unstick.plist
launchctl load -w ~/Library/LaunchAgents/com.scitex.orochi.tmux-unstick.plist
launchctl list | grep tmux-unstick   # verify loaded
```

### NAS (head-nas lane)

```
# copy (or symlink) unit files into ~/.config/systemd/user/
install -Dm 644 ~/proj/scitex-orochi/deployment/fleet/systemd/scitex-orochi-tmux-unstick.service \
                ~/.config/systemd/user/scitex-orochi-tmux-unstick.service
install -Dm 644 ~/proj/scitex-orochi/deployment/fleet/systemd/scitex-orochi-tmux-unstick.timer \
                ~/.config/systemd/user/scitex-orochi-tmux-unstick.timer

systemctl --user daemon-reload
systemctl --user enable --now scitex-orochi-tmux-unstick.timer
systemctl --user list-timers | grep tmux-unstick   # verify scheduled
```

### WSL / ywata-note-win (head-ywata-note-win lane)

Same pattern as NAS — per-user systemd is available on WSL 2 with
systemd support enabled.

### Spartan (head-spartan lane)

Spartan login1 has **no passwordless sudo and no per-user systemd**
(memory: `feedback_sudo_scope.md`, `hpc-etiquette.md`). Use the
user-space while-loop wrapper:

Add to `~/.bash_profile` after the existing head-spartan tmux launch:

```
if ! pgrep -u "$USER" -f 'tmux-unstick-spartan-loop.sh' >/dev/null; then
  nohup ~/proj/scitex-orochi/deployment/fleet/tmux-unstick-spartan-loop.sh \
    >/dev/null 2>&1 &
fi
```

The loop writes its PID to `~/.scitex/orochi/logs/tmux-unstick-loop.pid`
so an external supervisor (agent-autostart rerun, etc) can cleanly stop
it before restart.

## Verification

After install, watch the NDJSON log for the first sweep-summary record:

```
tail -f ~/.scitex/orochi/logs/tmux-unstick.ndjson | jq -r '
  "\(.ts) \(.event) session=\(.session) recovered=\(.recovered)"
'
```

A healthy deployment looks like one `sweep-summary` event per minute with
`detected: 0, recovered: 0` when nothing is stuck, and ad hoc
`paste-buffer-unsent` or `permission-prompt` events with `recovered: true`
when a wedge is caught and cleared.

## Phase boundaries

- **Phase 1 (this)**: detection + recovery via local scheduled sweeps.
  No cross-host coordination. Each host catches its own wedges. ≥30 min
  from directive msg#11943 to ship-and-running on 4/4 hosts.
- **Phase 2 (follow-up)**: the full `fleet-health-daemon` from
  scitex-orochi#147 — cross-host nonce handshake, Layer 2 ledger with
  `last_ndjson_ts AND last_orochi_pane_state_ok_ts`, worker-layer agentic
  recovery. Supersedes Phase 1 once it lands; Phase 1 stays as the
  fallback unstick runbook.
- **Phase 3 (long-term)**: Claude Code hook-based automation per
  `subagent-reporting-discipline.md` §4, removing even the need for the
  60 s sweep when hooks can intercept wedge patterns at the source.

## Safety stack

Six safety layers compose on every sweep. Each layer was added in
response to a specific hot-fix — see `scitex-orochi#153` for the
post-mortem.

1. **Self-exclusion (`A`)** — never send keys to the pane whose
   `pane_id` matches `$TMUX_PANE`. The script running inside the
   very pane it would otherwise "recover" is the self-suicide
   failure mode that hit head-spartan on 2026-04-15.
2. **Two-sample stability (`B`)** — `[Pasted text #N +M lines]` is a
   **normal live-compose state** in Claude Code, not stuck. A single
   sweep cannot distinguish "user is typing, paused" from "agent is
   wedged". The script requires the **same tail-hash** to appear on
   two consecutive sweeps at least `TMUX_UNSTICK_STABILITY_SEC`
   (default 120 s) apart before firing any recovery key. First
   sighting is recorded-only; second sighting triggers.
3. **Safe-start dry-run window (`C`)** — for the first
   `TMUX_UNSTICK_SAFE_START_SEC` seconds (default 300 = 5 min) after
   the loop boots, the script runs in `--dry-run` mode even if
   `DRY_RUN=0`. Detections are logged with `dry_run=true` so the
   first 5 minutes of production output can be eyeballed for
   false-positives before real keys start firing.
4. **Panic switch (`D`)** — if
   `~/.scitex/orochi/tmux-unstick.PAUSED` exists, the script sleeps
   without scanning. `touch` the file to halt recovery globally
   across all hosts; `rm` to resume.
5. **Per-pane rate limit (`E`)** — after a recovery fires on a pane,
   that pane is skipped for `TMUX_UNSTICK_COOLDOWN_SEC` seconds
   (default 120) so we never spam the same pane repeatedly.
6. **Log-before-act (`F`)** — the detection event is written to
   NDJSON **before** `send-keys` is called, so a post-mortem can
   reconstruct what the script believed even if the send-keys call
   corrupts subsequent state.

## NDJSON schema (v2)

Schema version `scitex-orochi/tmux-unstick/v2`. Each record:

```json
{
  "schema": "scitex-orochi/tmux-unstick/v2",
  "host": "<short>",
  "ts": "<iso8601Z>",
  "event": "loop-start|first-sighting|stable-match|fired|fire-failed|sweep-summary|sweep-paused|heartbeat",
  "session": "<session:window.pane>",
  "pane_id": "<%N or empty>",
  "recovered": true | false | null,
  "dry_run": 0 | 1,
  "detail": { ... }
}
```

Event lifecycle for a genuine wedge:

```
t0     first-sighting    (records state, does nothing)
t0+120 stable-match      (second observation, same hash)
t0+120 fired             (recovery key sent, cooldown begins)
t0+240 <pane is eligible again once cooldown expires>
```

For a user-composing false positive:

```
t0    first-sighting   (records tail hash)
t60   <tail hash changed because user kept typing>  -> no stable-match
```

## Known limitations

- **Only catches two wedge patterns.** Extra-usage wedge (1M context)
  still requires a session restart, which is destructive and out of
  scope for Phase 1. See `permission-prompt-patterns.md` for the
  pattern catalog.
- **No nonce handshake** — if a Claude session is alive but not
  responsive to new hub messages (e.g. crashed WS loop), Phase 1 does
  not catch it. Phase 2 nonce handshake does.
- **No central aggregation in Phase 1** — each host writes its own
  NDJSON locally. Cross-host dashboard view of "last unstick event
  per host" lands in Phase 2 when the hub exposes
  `/api/fleet/unstick/`.
- **Wrapper subshell may lose `$TMUX_PANE`** — when the loop wrapper
  is launched from `.bash_profile` it is not inside a tmux pane, so
  `$TMUX_PANE` is empty and self-exclusion (`A`) is a no-op. In this
  case Safety `B` (two-sample stability) is the primary defense
  against self-hit on a live-typing head pane. When the script is
  invoked directly from inside a pane (the interim deploy pattern)
  `A` takes effect and layers with `B`.

## Related

- Parent design doc: `_skills/scitex-orochi/fleet-health-daemon-design.md`
  (PR #147)
- Recovery pattern catalog: `_skills/scitex-orochi/permission-prompt-patterns.md`
  (PR #150)
- Origin incident log: msg#11794 (silent agents sweep 1),
  msg#11847 (silent agents sweep 2), msg#11943 (24h handshake directive)
- Anti-patterns: §11 of `fleet-health-daemon-design.md`
  (`NDJSON freshness alone is not liveness`)
