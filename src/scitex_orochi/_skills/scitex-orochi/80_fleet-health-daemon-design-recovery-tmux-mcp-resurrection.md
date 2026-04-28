---
name: orochi-fleet-health-daemon-recovery-tmux-mcp-resurrection
description: Phase 4 recovery playbook — tmux-stuck + MCP zombie + paste-buffer-unsent + periodic resurrection sweep. (Split from 64_fleet-health-daemon-design-recovery-extras.md.)
---

> Sibling: [`64_fleet-health-daemon-design-recovery-permission-extra-context.md`](64_fleet-health-daemon-design-recovery-permission-extra-context.md) for permission/extra-usage/context recovery.

### 7.4 Tmux-stuck recovery

- **Trigger**: session exists (`tmux has-session -t <agent>`) but
  pane output is static for > 2 min AND the agent has not
  DM-acked a probe for > 5 min AND no legitimate long-running
  command is expected. Last-resort recovery.
- **Action**: `tmux kill-session -t <agent>`, then respawn from
  the agent yaml via `scitex-agent-container start <agent>.yaml`.
- **Rollback**: impossible — the session is gone. If respawn
  fails, the agent stays dead; escalate.
- **Escalation**: post to `#escalation` with the pre-kill pane
  capture (final 50 lines) for post-mortem.
- **Rate limit**: max 1 kill-respawn per agent per 30 min.
- **Gating**: disabled on hosts where `tmux kill-session` would
  take down something else (Spartan login-node has only the one
  tmux session, so killing `head-spartan` is acceptable but
  killing `head-spartan` from `mamba-healer-spartan` which lives
  *inside* the same tmux server would commit suicide — the
  healer must be in a separate tmux server, or not attempt the
  kill on its own host).

### 7.5 MCP zombie recovery

- **Trigger**: `fleet-health.mcp-dup.<agent>` breadcrumb
  (`mcp_duplicates` has more than one PID for the same agent
  name).
- **Action**: inspect both PIDs' process trees (`pstree -p
  <pid>`). Kill the older one (oldest `stime`) unless it has
  active child processes doing recent work. Verify the agent
  still responds.
- **Rollback**: re-launch the agent's MCP subprocess if the kill
  took the wrong one.
- **Escalation**: DM the dispatcher (or post to `#heads`) if the kill
  did not reduce the duplicate count, or if the agent becomes
  unresponsive after the kill.
- **Rate limit**: max 1 dedup per agent per 10 min.

### 7.6 Paste-buffer-unsent recovery

- **Trigger**: pane capture shows `[Pasted text #N +M lines]`
  marker in the prompt area **and** the pane has been static
  (no new output lines) for > 30 s **and** the agent has not
  DM-acked a recent probe. ywatanabe observation from 2026-04-15
  MBA sweep: 5 agent panes had queued paste-buffer content that
  was never Enter-submitted, silently blocking forward motion.
- **Action**: `tmux send-keys -t <session> Enter` once, then wait
  10 s, re-check pane state. If the prompt is now cleared and
  output is flowing, recovery complete. If the prompt still
  shows the paste marker, escalate.
- **Critical constraint** (todo-manager msg#11809): **never
  blanket-Enter a pane that has queued text** — it races with
  the agent's own composition (the agent might be mid-typing).
  Only fire this recovery when the pane has been *static* for
  > 30 s AND matches the specific `[Pasted text #N ...]` prompt-
  level marker. If the prompt is in a different state (editing,
  mid-command), leave it alone.
- **Rollback**: none — the injected Enter is a user input, not a
  mutation. If the wrong Enter submits garbage, the agent will
  see the follow-up and correct.
- **Escalation**: if the same session hits paste-buffer-unsent 3
  times in 10 min, something is systematically broken upstream
  (agent not consuming its own composed message); escalate via DM
  to the dispatcher (or post to `#heads`) with the pane capture.
- **Rate limit**: max 1 Enter per session per 60 s.
- **Relationship to §7.1 permission prompt**: if the pane matches
  *both* the paste-buffer marker and a permission prompt pattern,
  §7.1 (send "2") takes precedence — the permission prompt is
  the actual blocker, not the paste buffer.

### 7.7 Periodic resurrection loop

Separate from the breadcrumb-driven recoveries above: a **periodic
resurrection sweep** runs every 5 min (worker-side clock,
independent of the daemon's 30 s tick). It walks the fleet's
expected-agent list, checks which are expected-alive, and for any
agent that has:

- no DM-ack in the last 5 min AND
- no NDJSON sample in the last 2 min AND
- no recent tmux pane motion

it attempts recovery in the order: §7.1 (permission prompt) →
§7.6 (paste-buffer-unsent, only if the marker is present) → §7.3
(compact) → §7.4 (kill-respawn). Each attempt respects the rate
limit. If the full chain fails, escalate.

This is the "systematic + periodic resurrection" integration
ywatanabe asked for on todo#142 (msg#11789). The breadcrumb-driven
recoveries handle immediate incidents; the 5 min sweep catches
slow-failures that didn't trip a breadcrumb. The MBA sweep
observed 2026-04-15 by head-mba (5 paste-buffer-unsent agents)
is the canonical motivating incident; this loop would have
caught them automatically.
