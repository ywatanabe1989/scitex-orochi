---
name: orochi-fleet-health-daemon-recovery-permission-extra-context
description: Phase 4 recovery playbook — motivating incident + permission-prompt + extra-usage-wedge + context-window-full recovery. (Split from 64_fleet-health-daemon-design-recovery-extras.md.)
---

> Sibling: [`80_fleet-health-daemon-design-recovery-tmux-mcp-resurrection.md`](80_fleet-health-daemon-design-recovery-tmux-mcp-resurrection.md) for tmux-stuck, MCP zombie, paste-buffer, periodic resurrection.
## 7. Phase 4 — Recovery action playbook

### Motivating incident (2026-04-15 02:44 UTC)

`head-nas` was reported as a silent agent in the 02:44 MBA sweep.
Investigation (head-ywata-note-win msg#11854, head-mba msg#11855)
found that head-nas was in a **compound failure state**:

1. **False-negative on the dashboard** — the NAS side of
   `agent_meta.py` had not been pulled to the latest version with
   the statusline parsing fix (head-ywata-note-win 576ba08f), so
   the `Agents` tab displayed stale / missing metadata for head-nas
   regardless of actual liveness.
2. **True-stuck underneath** — the live tmux pane on NAS was
   blocked on a Claude Code permission prompt (`Esc to cancel ·
   Tab to amend`, typical `1. Yes / 2. Yes, always allow / 3. No`
   menu). Forward motion was genuinely blocked until someone sent
   `2` + Enter.

Neither symptom alone tells you "this agent is wedged":

- The false-negative alone looks like an agent_meta.py bug
  (cosmetic, not lethal).
- The permission prompt alone, without the metadata staleness,
  would have been immediately obvious in the dashboard and would
  have been caught by the existing per-host tmux-unstick-poc
  (head-mba msg#11824).

**The compound of the two is what made head-nas appear "silently
dead" for long enough to require a manual MBA sweep.** This is
exactly the failure mode the fleet-health-daemon is meant to
catch: the Layer 1 daemon on NAS would have emitted per-tick
`pane_states` showing the permission-prompt match even when its
own `agent_meta.py` was stale (the daemon is host-local, not
dashboard-routed), and the Layer 2 ledger on any peer host would
have seen the missed handshake within one tick. The Phase 4
recovery playbook below (§7.1) has the exact `tmux send-keys "2"
Enter` action already specified.

Credit: this incident is the empirical reason §7.1 is scoped
tightly on the permission-prompt pattern catalog and why §7.7
(periodic resurrection sweep) reads the Layer 2 ledger rather
than trusting dashboard-level "inactive" displays. The dashboard
can lie; the daemon's NDJSON cannot, because it is written
host-locally with no routing layer between the probe and the
disk.

### Playbook

Per head-mba msg#11791, this is the canonical recovery playbook
that the worker layer executes when breadcrumbs fire. It
integrates the systematic + periodic resurrection that ywatanabe
asked for on todo#142 (msg#11789). Patterns accumulate here as
the fleet's operational knowledge matures, but the playbook is
executable automation, not a static document.

Every recovery action specifies: **trigger pattern** (what
breadcrumb + what snapshot match fires it), **action script**
(the concrete sequence of `tmux send-keys` / process ops / etc.),
**rollback path** (how to undo if the recovery makes things
worse), and **escalation path** (when to stop retrying and post
to `#escalation`).

### 7.1 Permission-prompt recovery

- **Trigger**: `fleet-health.pane-stuck.<session>` breadcrumb +
  pane capture matches one of the permission-prompt patterns
  (`Do you want to create...`, `Do you want to make this edit`,
  `Press 1/2/3`, `[y/N]`). Patterns accumulate over time per
  ywatanabe's "pattern-accumulation" directive (msg#11779) in a
  local `permission-prompt-patterns.md` skill doc, loaded at
  worker boot.
- **Action**: `tmux send-keys -t <session> "2" Enter` (bypass
  permissions default) for pre-approved prompts. LLM inspection
  for ambiguous ones.
- **Rollback**: none — the injected keystroke is a user input,
  not a mutation of state. If the session misread and "2" is the
  wrong choice, the agent sees the follow-up screen and decides
  its own next action.
- **Escalation**: DM the dispatcher (or post to `#heads` for cross-head
  visibility) if the same session hits the same prompt pattern 3 times
  within 5 min (pattern needs to be added to the allowlist or the
  permission scope needs widening). (`#agent` was abolished 2026-04-21.)
- **Rate limit**: max 1 recovery attempt per session per 30 s.

### 7.2 Extra-usage wedge recovery

- **Trigger**: pane capture matches `Extra usage is required for
  1M context` (or related wedge markers) **and**
  `extra_usage_enabled=false` in the agent's NDJSON quota field,
  **or** `last_quota_error` contains a quota-related error.
- **Action**: send `/exit` via `screen -X stuff` or `tmux
  send-keys`, wait for session to die, relaunch via
  `scitex-agent-container start <agent>.yaml` with the default
  (non-1M) model as the quick-restore path. Enabling the 1M
  context is ywatanabe's decision, not the healer's — the
  healer's goal is to get the agent back to a responding state,
  not to expand the quota envelope unilaterally.
- **Rollback**: if the relaunched session also wedges, keep it
  dead and escalate.
- **Escalation**: post to `#escalation` with context_pct at
  wedge time + last quota state so ywatanabe has the context
  needed to decide on extra-usage enable.
- **Rate limit**: max 1 restart per agent per 10 min.

### 7.3 Context-window-full recovery

- **Trigger**: `fleet-health.context.high.<agent>` breadcrumb
  (`context_pct >= 90%` sustained 3 samples) and the agent is
  still responsive.
- **Action**: send `/compact` slash command via `tmux send-keys
  -t <session> "/compact" Enter`, wait 15 s, verify `context_pct`
  drops to < 70%.
- **Rollback**: `/compact` is lossy (loses recent context). No
  undo. Only trigger at very high confidence and only on sessions
  where the recent loss is acceptable — not mid-PR-review, not
  mid-typed-message.
- **Escalation**: if `context_pct` does not drop post-compact,
  the agent is wedged on context ingest; escalate as tmux-stuck.
- **Rate limit**: max 1 compact per agent per 60 min.
- **Gating**: this action is **disabled by default**. Enable
  per-agent via a `~/.scitex/orochi/agents/<agent>/allow-auto-compact`
  marker file. ywatanabe can enable it globally later once the
  playbook has a track record.

