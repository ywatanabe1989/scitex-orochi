---
name: orochi-fleet-health-daemon-deployment-divergence
description: §10A — probe-liveness vs agent-responsiveness divergence (the critical split between daemon-side liveness and agent-layer responsiveness). (Split from 53_fleet-health-daemon-design-deployment-ops.md.)
---

> Sibling: [`53_fleet-health-daemon-design-deployment-anti-patterns.md`](53_fleet-health-daemon-design-deployment-anti-patterns.md) for anti-patterns, open questions, implementation order.
## 10A. Probe-liveness vs agent-responsiveness divergence (critical)

This is a design invariant strong enough to deserve its own
section. Two distinct things can be "alive", and confusing them
produces **silent false-alive** — the worst failure mode of any
monitoring system, because no alarm fires and the operator
trusts the display.

### The two liveness signals are independent

1. **Probe-process-alive**: the fleet-health-daemon bash/python
   subprocess is running and writing fresh NDJSON. This is a
   statement about the **daemon itself**, not about whatever it
   is probing.
2. **Claude-session-responsive**: the Claude Code session on the
   probed host / tmux pane can accept new input and make
   forward progress. This is a statement about the **probed
   agent**, not about its monitoring infrastructure.

These can diverge in either direction. The 2026-04-15 fleet
sweep demonstrated both directions in a single day:

| Agent                  | Probe-process | Claude-session   | Observed symptom                                  |
|------------------------|---------------|------------------|---------------------------------------------------|
| `mamba-healer-mba` (earlier today) | ✗ dead / missing | ✗ wedged on 1M extra-usage prompt | Silent; head-mba sweep caught it manually     |
| `mamba-healer-nas` (msg#11907)     | ✓ fresh NDJSON every 30 s | ✗ 2 pastes stuck in prompt, wedged for ~2.5 h | Dashboard reported "alive" → **silent false-alive** |
| head-spartan (02:44)   | ✓ active       | ✗ permission prompt stuck        | Dashboard metadata stale, pane wedged simultaneously |
| head-mba (normal)      | ✓ fresh        | ✓ responsive     | Truly alive                                       |

The middle row is the critical one. Probe subprocess was happily
streaming NDJSON at the usual cadence; the Claude session was
locked on a paste-buffer-unsent state and had not accepted a new
instruction in 2.5 hours. The dashboard, whose freshness cue
came from the NDJSON stream, showed "alive" for that entire
window.

### Required: AND of both checks, never either one alone

The Layer 2 ledger (§3) must track **both** timestamps per agent:

- `last_ndjson_ts` — latest NDJSON record from the fleet-health-
  daemon probing this agent.
- `last_pane_state_ok_ts` — latest NDJSON tick whose
  `pane_states.<session>` classified as `idle` or `working`
  (not `permission_prompt`, `paste_buffer_unsent`, `stuck`,
  `extra_usage_wedge`, `dev_channels_prompt`, or any other
  wedged class from `pane-state-patterns.md`).

An agent is considered **truly alive** only if **both** of:

1. `now - last_ndjson_ts < T_ndjson` (default: 120 s = 4 × 30 s
   cadence), AND
2. `now - last_pane_state_ok_ts < T_pane` (default: 180 s = 6 ×
   30 s cadence).

Either alone is a false positive. If just `last_ndjson_ts` is
fresh, it only proves the daemon is alive; the probed session
may be wedged (the msg#11907 case). If just `last_pane_state_ok_ts`
is fresh but the NDJSON stream has gone stale, the probe itself
has died (systemd unit stopped, launchd plist unloaded) and the
"pane OK" record is stale.

### 4-quadrant status matrix

Head-mba msg#11909 specified the color mapping; this design
encodes it so the dashboard (head-ywata-note-win lane) renders
it uniformly:

| Probe fresh | Pane responsive | Status           | Color  | Interpretation                             |
|-------------|-----------------|------------------|--------|--------------------------------------------|
| ✓           | ✓               | **truly_alive**  | green  | Safe. Nothing to do.                       |
| ✓           | ✗               | **ghost_alive**  | yellow | Probe data flowing but session wedged. **The 2026-04-15 msg#11907 healer-nas case.** Worker escalates to recovery playbook §7. |
| ✗           | ✓               | **probe_down**   | yellow | Session is fine but probe has stopped. Worker restarts the daemon (systemd reload / launchctl load); does **not** touch the agent session. |
| ✗           | ✗               | **truly_dead**   | red    | Both probe and session are gone. Worker triggers full kill-respawn via §7.4. |

### Detection precedence (for the worker)

When multiple signals are available in a single tick, worker
evaluates in this order and uses the first match:

1. `pane_state == permission_prompt` → §7.1 permission recovery
2. `pane_state == paste_buffer_unsent` → §7.6 paste recovery
3. `pane_state == extra_usage_wedge` → §7.2 session restart
4. `pane_state == stuck` (long silence, no other classification)
   → §7.3 /compact if allowed, else §7.4
5. `last_ndjson_ts` stale → probe_down, restart daemon
6. neither stale nor wedged → truly_alive, no action

This precedence means the worker **always prefers the most
specific actionable signal** over the generic "probe stale"
signal. A ghost_alive agent is handled as a pane-stuck recovery,
not as a probe-down restart, because the restart wouldn't help.

### Implementation note for Phase 1 / Phase 2

Phase 1 (quota scraping) emits NDJSON but **does not yet
classify pane states**. During Phase 1, the divergence is
invisible — the ledger only has `last_ndjson_ts`, no
`last_pane_state_ok_ts`, and the 4-quadrant matrix collapses to
"NDJSON fresh vs stale" (false-alive risk unaddressed). This is
acceptable for Phase 1 because the scope was explicitly scoped
to quota and not pane classification (ywatanabe msg#11775). But
Phase 2 MUST add the `pane_states` field and the
`last_pane_state_ok_ts` timestamp **before** the fleet switches
away from human tmux sweeps as its primary liveness mechanism.
Otherwise Phase 1 ships a dashboard that looks correct but
silently false-alives on the first paste-buffer-unsent event —
which we now know happens on a multi-hour timescale.

**This is the empirical reason §7.7 (periodic resurrection
sweep) runs independently of the breadcrumb path.** It walks the
ledger on a 5 min timer and catches ghost_alive agents the
breadcrumb path would miss because no NDJSON threshold transition
fired (the probe is happily emitting "session wedged" with the
same value every tick, so no transition, so no breadcrumb — but
the sweep sees the sustained-wedged state and acts).

