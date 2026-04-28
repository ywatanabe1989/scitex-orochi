---
name: orochi-agent-pane-state-patterns-detection
description: Pane-state detection — session-existence preflight + scrollback false-positive guard + classification algorithm + auto-actions. (Split from 57_agent-pane-state-patterns-extras.md.)
---

> Sibling: [`57_agent-pane-state-patterns-consumers.md`](57_agent-pane-state-patterns-consumers.md) for upstream single-source-of-truth + consumers + scope + related.
## Session-existence preflight — `tmux ls`, not `screen -ls`

Added 2026-04-15 after `worker-healer-<host>` msg #12799 false-alarmed
"fleet down — all 12 agents + screen sessions gone" while all 12
tmux sessions were in fact alive.

Before any pane-state classification, a healer must first confirm
the session exists. The session-existence check must use the same
multiplexer the agents are actually running in:

- scitex-agent-container defaults to `multiplexer: tmux` since v0.7.
  Session-existence check: **`tmux ls`**.
- `screen -ls` is only valid on hosts where an agent's YAML explicitly
  sets `multiplexer: screen`. On all other hosts (primary workstation included) the
  screen socket is empty and `screen -ls` reports "No Sockets found",
  which is **not** evidence that the agents are dead.

Contract for any liveness probe:

1. **Primary signal**: `tmux ls` (or `screen -ls` iff the agent's
   configured multiplexer is screen). If the expected session name is
   present, the session exists. Classify pane state from here.
2. **Secondary signal only**: `scitex-agent-container list` output.
   Treat an empty list as a **hypothesis** to cross-check with the
   primary signal, never as ground truth. A stale / crashed
   scitex-agent-container list command can return an empty list while
   the underlying sessions are fine.
3. **Never escalate** a "fleet down" classification on the secondary
   signal alone. If `tmux ls` shows the session, the session is alive;
   post-fix the probe code instead of the fleet.
4. If the probe cannot reach the multiplexer at all (e.g. SSH is
   down), classify the **host** as unreachable — not the individual
   sessions as dead. The agents inside an unreachable host cannot be
   probed, and "can't probe" is distinct from "confirmed dead"
   (rule #11 absence-of-response still applies for DM-based probes,
   but the host layer is a separate question).

A healer that short-circuits this preflight will false-alarm the operator
and the heads, waste fleet attention on a non-incident, and risk
triggering a destructive "restart everything" response. Always two
signals, primary-before-secondary, before classifying a host as down.

## Scrollback false-positive guard — strict last-N-lines window

Added 2026-04-14 after `worker-healer-<host>` msg #10865. Regexes must match against the **last 5 lines** of `tmux capture-pane -p -S -5`, not the full scrollback buffer.

Why: scrollback accumulates every prompt the session has ever seen — a "Press Enter to continue" from 6 hours ago, now scrolled off but still in the buffer, will match a full-buffer regex and trigger a false-positive unblock action. The strict last-5-lines window ensures only the **currently-displayed** prompt is considered.

Implementation contract:

- Capture: `tmux capture-pane -p -S -5 -t <session>` (last 5 lines, joined).
- All regex matches run against that slice, not against `capture-pane -p` (full scrollback) or `capture-pane -pS -` (entire buffer).
- The only exception is `:mulling` detection which checks for an `*` animation row — that can appear anywhere in the visible region, so last-10-lines is acceptable for `:mulling` specifically.
- When a classifier needs to distinguish "live prompt" from "scrollback residue", the rule is **"if it's not in the last 5 lines, it's not a current prompt"**.

Classifiers that ignore this guard will produce spurious `:paste_pending` / `:dev_channels_prompt` / `:permission_prompt` hits on agents that are actually idle at `❯`, and will then send `Enter` or `1` into a live idle prompt — which is a **destructive action** (it submits whatever the agent had been drafting).

Add the last-5-lines check to every new classifier implementation *before* shipping, not as a follow-up fix.

## Classification algorithm

Priority order (highest wins — exit on first match):

1. `:mulling` — animation active → busy
2. `:paste_pending`
3. `:auth_needed`
4. `:quota_exhausted`
5. `:dev_channels_prompt`
6. `:permission_prompt` (numbered, then y/n)
7. `:quota_warning`
8. `:stuck_error`
9. `:mcp_broken` — requires external heartbeat check
10. `:dead` — requires shell-prompt match
11. `:running` — if active output seen in the last 5 seconds
12. `:waiting` — default when nothing above matches and pane tail ends with `❯`
13. `:unknown` — any other case

## Auto-actions

Healers call this module read-only to **classify**, then consult a per-state action table before acting. Action table is **per-agent** (healers may disable auto-unblock on production agents) and **per-host** (spartan must not `systemctl --user restart` anything).

| State | Default action | Confirmation needed? |
|---|---|---|
| `:mulling` | none | no |
| `:paste_pending` | `Enter` | no |
| `:permission_prompt` (safe) | `n` / `2` | no |
| `:dev_channels_prompt` | `1` + Enter | no |
| `:auth_needed` | post URL to `#operator` | no |
| `:quota_exhausted` | credential swap | no, if alternate < 70% |
| `:quota_warning` | pre-swap | yes (log warn first) |
| `:mcp_broken` | `scitex-agent-container restart` | yes, escalate if repeated |
| `:stuck_error` | post to `#escalation` | no (informational) |
| `:dead` | autostart unit | no |
| `:unknown` | escalate once, do not act | no |

