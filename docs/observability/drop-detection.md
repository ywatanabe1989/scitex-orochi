# Silent-Drop Detection

Part of [Epic #133 — Fleet Observability](../../issues/133).

## Problem

An agent can appear "online" in the hub registry (its WebSocket session is alive) while
being behaviorally dead — stuck on a blocking tool call, waiting at a Y/N prompt, or
simply idle with no work being done. The raw `status: online` field does not distinguish
these cases, leading to false-positive "all-green" readings in the dashboard.

## Solution: derived `liveness` field

The hub registry (`hub/registry/_payload.py`) computes a `liveness` field on every
`GET /api/agents/` response. It uses pane-state and activity timestamps to classify
each agent:

| `liveness` | Meaning | Trigger |
|---|---|---|
| `online` | Actively running | `orochi_pane_state == "running"` OR recent activity |
| `idle` | Paused / waiting for input | pane at prompt, or 2–10 min since last action |
| `stale` | Likely stuck | `orochi_pane_state == "stale"/"auth_error"` OR >10 min silent |
| `offline` | Disconnected | WS session closed |

### Classification logic

```python
# hub/registry/_payload.py  (simplified)
if pane == "running":
    liveness = "online"
elif pane in ("stale", "auth_error"):
    liveness = "stale"
elif pane == "idle":
    liveness = "idle"
elif pane in ("y_n_prompt", "compose_pending_unsent", ...):
    liveness = "idle"          # waiting — not stuck
elif idle_seconds > 600:       # >10 min no action
    liveness = "stale"
elif idle_seconds > 120:       # >2 min
    liveness = "idle"
```

`idle_seconds` is derived from the later of:
- `last_action` (last Orochi chat message sent by the agent)
- `sac_hooks_last_tool_at` (last PreToolUse/PostToolUse hook event from scitex-agent-container)

## Dashboard surface

### Agent table row
Each row's status dot and label use `liveness` color:
- `online` → teal (`#4ecdc4`)
- `idle` → amber (`#ffd93d`)
- `stale` → orange (`#ff8c42`)
- `offline` → red (`#ef4444`)

### Machine-level badges (Agents tab summary bar)

Badges group agents by host machine. Since [commit 5c0d803](../../commit/5c0d803), badge
class is determined by the worst `liveness` within the machine group:

| Condition | Badge class | Color | Example |
|---|---|---|---|
| All agents liveness ∈ {online, idle} | `machine-ok` | teal | `nas (4/4)` |
| Any agent has `liveness == "stale"` | `machine-stale` | orange | `mba (3/4, 1 stuck)` |
| Some online, some offline | `machine-warn` | yellow | `nas (2/4)` |
| All agents offline | `machine-off` | red | `spartan (0/3)` |

A fleet-wide `⚠ N stuck` warning badge appears in the summary line when any agent is
stale across any machine.

### Tooltip

Hovering a machine badge shows:
```
3 active, 1 stale, 0 offline
```

## False-positive rate

Known false-positive scenarios:

1. **Long single tool call** — a bash command or test run taking >10 min will trigger
   `stale` even though the agent is working. Mitigated by the `sac_hooks_last_tool_at`
   field: if the PreToolUse hook fired recently, `idle_seconds` resets. Agents on older
   scitex-agent-container (<0.11) may not push this field.

2. **Freshly booted agent** — if `orochi_pane_state` hasn't been pushed yet (first
   heartbeat race), the agent may briefly appear `stale` for up to 2 heartbeat cycles.
   This is cosmetic and self-resolves.

3. **Quiet workers** — passive relay agents (e.g. `worker-progress`) are deliberately
   silent. They push `orochi_pane_state` to distinguish "idle waiting" from "stuck".
   If the agent doesn't push pane state, the 10-min timer applies.

## On-call playbook

When `machine-stale` appears:

1. Click the machine badge to sort agents by machine. Stale agents will have an orange
   status dot.
2. Click the stale agent's row to open the detail pane. Check:
   - `orochi_pane_tail` — last lines of the Claude Code terminal; look for Y/N prompts,
     error tracebacks, or long-running tool output.
   - `orochi_pane_state` — classifier label (`stale`, `auth_error`, `y_n_prompt`, etc.)
   - `Last Activity` column — timestamp of the last known action.
3. If stuck at Y/N prompt: DM the agent with the answer, or ask the host healer to
   respond (`sac send-input <agent> <input>`).
4. If crashed / no pane output: ask the host healer to restart (`sac restart <agent>`).
5. If the agent has been stale for >30 min with no apparent cause, file a report in
   `#heads` and DM `lead` with the agent name and last known task.

## Stuck-subagent detection (orochi#133, sac-side LIFO)

Since sac 0.x and orochi#133, the hub gains a second stuck-subagent signal from the
agent-container event ring-buffer, complementing the hub-side `subagent_active_since`
timer.

### How it works

scitex-agent-container records every `PreToolUse` / `PostToolUse` hook event in a
per-agent JSONL ring-buffer (`~/.scitex/agent-container/events/<agent>.jsonl`).
`event_log.summarize()` performs LIFO matching on `Agent` tool events:

- `Agent` pretool: push to stack.
- `Agent` posttool: pop from stack (matched = completed).
- Remaining entries after full scan = **open (potentially stuck) Agent calls**.

The three derived fields emitted by `summarize()` and forwarded to the hub:

| Field | Type | Meaning |
|---|---|---|
| `sac_hooks_open_agent_calls` | `list[{ts, input_preview, age_seconds}]` | Unmatched Agent pretool events |
| `sac_hooks_open_agent_calls_count` | `int` | Number of open calls |
| `sac_hooks_oldest_open_agent_age_s` | `float \| null` | Age of the oldest open call in seconds |

### Hub integration

The `subagent_stuck` alert payload (`GET /api/watchdog/alerts/`) now includes
`open_agent_calls_count` and `oldest_open_agent_age_s` alongside the hub-side
`subagent_active_since` timer:

```json
{
  "agent": "head-mba",
  "kind": "subagent_stuck",
  "subagent_count": 2,
  "subagent_stuck_seconds": 720,
  "open_agent_calls_count": 1,
  "oldest_open_agent_age_s": 680.3,
  "suggested_action": "escalate"
}
```

Cross-checking both signals reduces false positives: `subagent_count > 0` alone can lag
if the count hasn't been updated yet; `open_agent_calls_count > 0` confirms the
agent-container's own ring-buffer also sees an unresolved call.

### Limitations

- The ring-buffer has a 500-line cap; very busy agents that fill the buffer before
  the posttool event arrives will appear to have open calls that have actually resolved.
- The LIFO matching assumes Agent calls complete in LIFO order (nested subagent model).
  Concurrent independent Agent calls will match out-of-order, potentially leaving false
  open entries. This is a known approximation; the `age_seconds` field lets callers
  apply an age threshold to filter stale false-positives.
- `sac_hooks_open_agent_calls_count` is only populated for agents running
  scitex-agent-container ≥ 0.x with hooks wired. Legacy agents show 0.

## Future improvements

- **Threshold tuning**: 10-min stale threshold may need per-role adjustment (long
  research agents legitimately think for >10 min).
- **Push notification**: When a stale badge first appears, send a DM to `lead` or post
  to `#heads`. Currently passive (poll-only).
- **Recovery automation**: Healers could auto-respond to known-safe Y/N prompts.
