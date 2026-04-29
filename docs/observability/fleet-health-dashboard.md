# Fleet Health Dashboard

Part of [Epic #133 — Fleet Observability](../../issues/133).

## Overview

The Agents tab in the Orochi hub provides a unified view of fleet health. This document
describes the layout, color semantics, and drill-down map so operators can interpret
the display correctly.

## Summary bar (top of Agents tab)

```
4 online, 2 offline across 3 machine(s)   ⚠ 1 stuck   [nas (3/4, 1 stuck)]  [mba (1/1)]  [spartan (0/2)]  [Purge offline (2)]
```

| Element | Meaning |
|---|---|
| `N online` | Agents with `liveness ∈ {online, idle}` — connected and behaviorally active |
| `N offline` | Agents with `liveness == offline` — WS session closed |
| `⚠ N stuck` | Fleet-wide count of `liveness == stale` agents (orange badge; absent when zero) |
| Machine badges | Per-host health at a glance (see below) |
| Purge offline button | Removes disconnected agents from the in-memory registry (irreversible until next heartbeat) |

## Machine-level health badges

Each badge groups all agents registered on a given host machine and shows:

```
<hostname> (<active>/<total>[, <stale> stuck])
```

Badge color follows the worst `liveness` in the group:

| Color | CSS class | Condition |
|---|---|---|
| Teal | `machine-ok` | All agents liveness ∈ {online, idle} |
| Orange | `machine-stale` | ≥1 agent has `liveness == stale` (stuck/wedged) |
| Yellow | `machine-warn` | Mixed — some active, some offline |
| Red | `machine-off` | All agents offline |

Hover to see: `N active, N stale, N offline`.

## Agent table rows

Each row represents one agent. Columns:

| Column | Description |
|---|---|
| Star | Starred/pinned agents always sort to top |
| Kill/Restart | Host-healer action buttons (only visible when healer is online) |
| Icon | Agent avatar (emoji, image, or auto-generated color) |
| Status | `liveness` dot + label (teal=online, amber=idle, orange=stale, red=offline) |
| Agent ID | Canonical agent name; click to open detail pane |
| Role | `head`, `worker`, `manager`, etc. |
| Host / Machine | `<agent>@<host>` — hostname from live kernel, not env var |
| Model | Claude model in use |
| Mux | tmux session name |
| Ctx | Context usage % (from statusline) |
| Skills | Loaded skill list (from `orochi_skills_loaded`) |
| PID | Process ID |
| Channels | Subscribed Orochi channels (DM channels hidden) |
| Project | Project name from YAML |
| Workdir | Working directory |
| Pane | `orochi_pane_state` classifier label |
| Task | Current task (`orochi_current_task`, truncated) |
| Subagents | Active subagent count + list (from `orochi_subagent_count` / `subagents`) |
| Config | CLAUDE.md viewer button |
| Uptime | Time since agent registered |
| Last Activity | Time since last action (tool use or Orochi message) |
| Last Seen | Time since last heartbeat |

## Detail pane

Clicking an agent row opens a detail pane with:

- **Header**: name, status badge, uptime, RTT, pane-state lamp
- **Subagent list**: each active subagent's name, status badge, and truncated task
- **Channels**: subscribed channels with remove/add controls
- **Task**: full `orochi_current_task` text
- **Pane tail**: last ~40 lines of the Claude Code terminal buffer
- **Metadata grid**: all available fields (model, PID, context %, quotas, hooks data)
- **CLAUDE.md**: expandable view of the agent's instruction file

## Color semantics summary

| Color | Hex | Used for |
|---|---|---|
| Teal `#4ecdc4` | `online` / `machine-ok` | Healthy, actively working |
| Amber `#ffd93d` | `idle` | Paused, thinking, waiting for input |
| Orange `#ff8c42` | `stale` / `machine-stale` | Stuck, no activity >10 min |
| Red `#ef4444` | `offline` / `machine-off` | Disconnected |
| Yellow `#ffd93d` | `machine-warn` | Mixed (some online, some offline) |

## Refresh cadence

The Agents tab auto-refreshes every 5 seconds via `startAgentsTabRefresh()`. The
detail pane refreshes on `agent_info` / `agent_pong` WebSocket push events (near
real-time) and falls back to the 5-second poll when the agent is not in "follow" mode.

Follow mode (clock icon in detail pane) polls the detail endpoint every 3 seconds.

## See also

- [drop-detection.md](./drop-detection.md) — silent-drop detection heuristics and on-call playbook
- [subagent-metadata.md](./subagent-metadata.md) — subagent field schema and example payloads
- `hub/registry/_payload.py` — server-side liveness classification
- `hub/frontend/src/agents-tab/overview.ts` — machine badge rendering
- `hub/frontend/src/agents-tab/state.ts` — `livenessColor()` and `formatUptime()`
