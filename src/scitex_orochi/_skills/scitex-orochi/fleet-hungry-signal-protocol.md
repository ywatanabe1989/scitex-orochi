---
name: orochi-fleet-hungry-signal-protocol
description: Layer 2 coordinated dispatch — idle heads DM lead ("ready for dispatch"), lead responds with a chosen high-priority todo + brief. Companion to the auto-dispatch-probe Layer 1 (PR #320) which handles "grab-anything-local"; this layer routes with context.
---

# Fleet Hungry-Signal Protocol (Layer 2 coordinated dispatch)

> **Status**: canonical, landed with PR feat/hungry-signal-layer2 (lead
> msg#16310).
>
> Layer 1 is `scripts/client/auto-dispatch-probe.sh` (PR #320): idle heads
> auto-claim any local-lane high-priority todo. That fixes "idle =
> forbidden" but routes blindly. Layer 2 adds a coordinated path so lead
> can pick a better-matched todo with context.

## Why

Layer 1 grabs whatever matches the head's lane label. That's fast but
can fork subagents onto low-relevance todos while a higher-relevance
todo (out of lane, or mis-labelled) waits. Layer 2 adds an "intentional
pickup" path: an idle head tells lead it's ready; lead picks with full
fleet context (claimed PRs, audit-review flags, cross-lane priorities)
and replies with a todo number + one-line brief.

## Wire format

### Head → lead DM

Sent by `scripts/client/hungry-signal.sh` on a 10-min cadence when the
head has seen `subagent_count == 0` for `HUNGRY_THRESHOLD=2` consecutive
cycles (≈ 20 min of real idleness).

Canonical DM channel: `dm:agent:<sorted-pair>` (matches the hub's
`_openAgentDmSimple` helper in `hub/static/hub/app/agent-actions.js`).

Text format (exact, so lead can parse):

    head-<hostname>: hungry — 0 subagents × <N> cycles, ready for dispatch. lane: <label>, alive: <comma-sep-agent-list>

Example (verbatim from a real run):

    head-mba: hungry — 0 subagents × 2 cycles, ready for dispatch. lane: infrastructure, alive: head-mba,healer-mba

### Lead → head reply

One-line DM in the same channel. Format:

    dispatch: todo#<N> — <title> — <brief>

…or, when nothing matches:

    dispatch: none matching lane=<label> — no open high-priority todo fits <head>. Stand by; I'll route when one appears.

## Lead-side responsibilities

When lead sees a DM whose text matches
`^head-[\w.-]+: hungry .* lane: <label>` in any of its DM channels:

1. **Parse** the sender (`head-<hostname>`) and lane (label).
2. **Fetch context**:

       gh issue list --repo ywatanabe1989/todo --state open \
           --label high-priority --json number,title,labels,assignees
       gh pr list --repo ywatanabe1989/todo --state open \
           --json title,body

3. **Filter** — in this order:
   - Skip any issue whose number appears in an open PR title/body
     (already claimed).
   - Skip any issue carrying the `audit-review-2026-04-22` label
     (stale-under-review).
   - Skip any issue already assigned to a human (explicit ownership).
4. **Pick**:
   - Prefer the first issue with the sender's lane label.
   - Fall back to the first unlabelled high-priority issue (no lane
     tag at all). Do **not** pick an issue carrying a *different*
     lane's label — that's someone else's lane.
5. **Reply** in the same DM channel with the `dispatch: todo#<N> …`
   format above.

The canonical implementation of steps 2–5 is
`scripts/server/hungry-signal-handler.py` — it can be imported as a
library (`handle_hungry_message(text, issues, open_prs)`) or shelled
out as a CLI. Reuse it rather than reimplementing in-context to avoid
drift.

## Spam guard

The head-side probe writes a "fired" marker into
`~/.local/state/scitex/hungry-signal.state` once a DM is posted, and
only clears it on the next non-zero `subagent_count` reading. This
means lead receives at most **one hungry DM per idle stretch** per
head. If lead is slow to reply (or unavailable), the head does not
re-DM until it's had at least one non-zero cycle.

## Related

- Layer 1: `scripts/client/auto-dispatch-probe.sh` (PR #320) —
  "idle = forbidden" via local auto-claim.
- Install: `scripts/client/install-hungry-signal.sh` — LaunchAgent /
  systemd timer / cron, 10-min cadence.
- Kill switch: `SCITEX_HUNGRY_DISABLED=1` on the head's env.
- State file: `~/.local/state/scitex/hungry-signal.state` (single line
  per head — cycles, fired flag, last-update epoch).
- Tests: `tests/test_hungry_signal_handler.py` (pure-function picker)
  and `tests/test_hungry_signal_counter.py` (state-machine integration
  via a stubbed sac).
