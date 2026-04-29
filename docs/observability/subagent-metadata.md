# Subagent Metadata

Part of [Epic #133 — Fleet Observability](../../issues/133), sub-item #132.

## Overview

Agents that spawn subagents (via Claude Code's `Agent` tool) push a `subagents` list
to the hub on every heartbeat. This list is surfaced in the dashboard detail pane and
in the `GET /api/agents/` response.

## Data flow

```
scitex-agent-container
  └─ status --json (sac_hooks_agent_calls)
       └─ POST /api/agents/subagents/  (hub endpoint)
            └─ hub/registry/_store.py  (_agents[name]["subagents"])
                 └─ GET /api/agents/   → "subagents": [...]
                      └─ dashboard detail pane
```

The `orochi_subagent_count` field is a convenience integer (`len(subagents)` when
`subagents` is populated, or the raw int pushed by older heartbeat clients).

## Field schema

### Agent-level fields

| Field | Type | Description |
|---|---|---|
| `subagents` | `list[SubagentEntry]` | Active subagent list (empty when none) |
| `orochi_subagent_count` | `int` | Count of active subagents |

### SubagentEntry schema

Each entry in the `subagents` list:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Subagent identifier (e.g. `"DebuggerAgent"`, `"Explore"`) |
| `task` | `str` | Task description passed to the subagent (may be long; truncated in UI) |
| `status` | `str` | `"running"` \| `"done"` \| `"failed"` |

### Example payload

```json
{
  "name": "head-nas",
  "orochi_subagent_count": 2,
  "subagents": [
    {
      "name": "Explore",
      "task": "Find all Python files referencing api/agents in the hub directory",
      "status": "running"
    },
    {
      "name": "DebuggerAgent",
      "task": "Debug why /api/agents/?token=... returns 404 on bare domain",
      "status": "done"
    }
  ]
}
```

## Update endpoint

```
POST /api/agents/subagents/
Content-Type: application/json

{
  "token": "wks_...",
  "agent": "head-nas",
  "subagents": [
    {"name": "Explore", "task": "...", "status": "running"}
  ],
  "orochi_subagent_count": 1
}
```

Implemented in `hub/views/api/_agents.py` (`api_subagents_update`). Idempotent — the
entire list is replaced on each push.

## Dashboard rendering

### Agents tab overview table

The **Subagents** column shows `orochi_subagent_count` as a count badge when >0.

### Agent detail pane

When a detail row is expanded, the subagent list is rendered between the header and the
channels section:

```
── Subagents (2 active) ───────────────────────────
● running  Explore          Find all Python files re…
✓ done     DebuggerAgent    Debug why /api/agents/?t…
```

Status badge colors:
- `running` → amber (`#ffd93d`) — in progress
- `done` → dimmed teal (`#888`) — completed
- `failed` → red (`#f87`) — errored

## False positives / stale entries

Subagent entries persist until the parent agent pushes a new list. If an agent crashes
before clearing its subagents, the last-known list remains visible in the detail pane
until the next heartbeat or page refresh. This is by design — stale entries signal that
the parent agent may have wedged mid-task.

## sac hook-event ring-buffer fields (orochi#133)

Since orochi#133, the hub also receives subagent activity signals derived from the
`scitex-agent-container` hook-event ring-buffer (`~/.scitex/agent-container/events/`).
These complement the `subagents` list (which requires the agent to explicitly push via
`POST /api/agents/subagents/`) with passive, event-log-derived signals.

### `sac_hooks_agent_calls`

The last ≤20 `Agent` pretool events recorded by the hook. Each entry:

| Field | Type | Description |
|---|---|---|
| `ts` | ISO-8601 | Timestamp of the pretool event |
| `input_preview` | `str` | Truncated `description` or first 200 chars of `prompt` |

### `sac_hooks_open_agent_calls` (stuck-subagent signal)

Agent pretool events with **no matching posttool** (LIFO matching). An unmatched
pretool = an Agent call that has not yet returned. Fields:

| Field | Type | Description |
|---|---|---|
| `ts` | ISO-8601 | When the Agent call was started |
| `input_preview` | `str` | Task description |
| `age_seconds` | `float \| null` | Seconds since the call was started |

Scalar shortcuts also emitted:

| Field | Type | Description |
|---|---|---|
| `sac_hooks_open_agent_calls_count` | `int` | Number of open calls |
| `sac_hooks_oldest_open_agent_age_s` | `float \| null` | Age of oldest open call |

These fields drive the enriched `subagent_stuck` alert in `GET /api/watchdog/alerts/`.
See [drop-detection.md](./drop-detection.md) for full semantics.

## See also

- `hub/views/api/_agents.py` — `api_subagents_update` endpoint
- `hub/frontend/src/agents-tab/detail.ts` — subagent list rendering in detail pane
- [drop-detection.md](./drop-detection.md) — detecting stuck agents (subagent staleness as a signal)
- `src/scitex_agent_container/event_log.py` — `_compute_open_agent_calls()` LIFO logic
