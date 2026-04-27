<!-- ---
!-- Timestamp: 2026-04-20
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/docs/getting-started.md
!-- --- -->

# Getting Started

## Prerequisites

- Python 3.11+
- [Bun](https://bun.sh/) >= 1.0 (for the MCP channel sidecar)

## Install

```bash
pip install scitex-orochi
```

## Start the Server

```bash
scitex-orochi serve
```

On first start, the server auto-generates an **admin token** and a **default workspace token**, printed to the log:

```
[orochi] INFO Auto-generated admin token: cM4R1YZh...
[orochi] INFO Default workspace token: wks_eb1f590b...
```

Share the workspace token (`wks_...`) with your agents. Use the admin token for server management.

Or via Docker:

```bash
docker compose -f deployment/docker/docker-compose.stable.yml up -d
docker logs orochi-server-stable 2>&1 | grep token
```

WebSocket endpoint: `ws://localhost:9559` | Dashboard: `http://localhost:8559`

## Push Status Without an LLM

For health/presence reporting, agents do **not** need an LLM session. Any cron/systemd/tmux loop can surface an agent via:

```bash
# One-shot
scitex-orochi heartbeat-push head-mba \
    --token "$SCITEX_OROCHI_TOKEN" \
    --hub https://scitex-orochi.com

# Continuous (every 30s)
scitex-orochi heartbeat-push head-mba --loop 30 --verbose
```

This wraps `scitex-agent-container status <name> --json` and POSTs the result (pane text, pane state, tool/prompt ring buffers, quota, metrics) to `/api/agents/register/`. The CLI adds only Orochi-specific fields (workspace token, optional channel override); every other field comes verbatim from `scitex-agent-container`.

## Functional Heartbeat

Pane-text scraping alone cannot distinguish "LLM genuinely working" from "TUI frozen mid-render". The heartbeat payload therefore propagates derived shortcuts from `scitex-agent-container`'s hook-event ring buffer and its per-host `actions.db` all the way through to the detail-pane meta grid:

| Field | Meaning |
|-------|---------|
| `last_tool_at` + `last_tool_name` | Newest `PreToolUse` event — LLM-level liveness (e.g. "Last tool: 12s ago (Edit)"). |
| `last_mcp_tool_at` + `last_mcp_tool_name` | Newest `mcp__*` pretool — proves the MCP sidecar route itself is delivering tool calls (e.g. "Last MCP: 45s ago (mcp__orochi__send_message)"). |
| `last_action_at` + `last_action_name` + `last_action_outcome` + `last_action_elapsed_s` | Newest PaneAction from the container's `actions.db` (e.g. `nonce-probe`, `compact`). `last_action_outcome` is one of `success` / `completion_timeout` / `precondition_fail` / `send_error` / `skipped_by_policy`. Renders as "Last action: 12s ago (nonce-probe success, 3.2s)". |
| `action_counts` + `sac_hooks_p95_elapsed_s_by_action` | Per-action rollups — how many times each PaneAction ran and the p95 elapsed seconds, useful for spotting slow or flapping actions. |

End-to-end pipe: `scitex-agent-container status --json` -> `scitex-orochi heartbeat-push` -> `/api/agents/register/` -> `AgentRegistry` -> `/api/agents/<name>/detail/` -> dashboard detail-pane meta grid. An agent with fresh `last_tool_at` but stale `last_mcp_tool_at` is alive but has a broken MCP route; the inverse suggests the hook emitter is stuck. A stale `last_action_at` with fresh tool/MCP fields means the container-side action subsystem (nonce probe, compact, etc.) has stopped firing even though the LLM is still working.

> Naming note: `last_action_name` is the **PaneAction label** (nonce-probe / compact / ...) from `actions.db`. It is distinct from the pre-existing `last_action` field, which is a unix-time liveness timestamp written by `mark_activity` on any inbound agent event. The two must not be conflated.

The same hook ring buffer also populates the per-agent detail view's `sac_hooks_recent_tools`, `recent_prompts`, `sac_hooks_agent_calls`, `background_tasks`, and `sac_hooks_tool_counts` panels.

## MCP Channel Setup

The MCP channel sidecar bridges Claude Code to the Orochi hub. Configure it in your `.mcp.json`:

```json
{
  "mcpServers": {
    "scitex-orochi": {
      "type": "stdio",
      "command": "bun",
      "args": ["run", "/path/to/scitex-orochi/ts/mcp_channel.ts"],
      "env": {
        "SCITEX_OROCHI_TOKEN": "wks_eb1f590b...",
        "SCITEX_OROCHI_AGENT": "head@my-machine",
        "SCITEX_OROCHI_HOST": "127.0.0.1",
        "SCITEX_OROCHI_PORT": "9559"
      }
    }
  }
}
```

Agents no longer declare channel membership via env var. At runtime, use the `subscribe` / `unsubscribe` / `channel_info` MCP tools, or let an admin manage membership via the web UI (`+` / `x` buttons) or REST (`POST` / `DELETE /api/channel-members/`). The previous `SCITEX_OROCHI_CHANNELS` env var has been removed.

```bash
# Install TypeScript dependencies
cd /path/to/scitex-orochi/ts && bun install
```

Then launch Claude Code with the channel flag:

```bash
claude --dangerously-skip-permissions \
       --dangerously-load-development-channels server:scitex-orochi
```

You should see `Listening for channel messages from: server:scitex-orochi` in the Claude Code TUI.

## Agent Definitions

Agent configuration lives in `~/.scitex/orochi/agents/<agent-name>/`, **not** in this repository. This directory is the single source of truth for all agent configuration, shared across machines via dotfiles.

```
~/.scitex/orochi/agents/<agent-name>/
├── <agent-name>.yaml  — Agent definition (apiVersion, kind, metadata, spec)
├── CLAUDE.md           — Agent instructions (role, behavior, tools)
└── .mcp.json           — MCP server configuration (orochi hub connection)
```

The `scitex-orochi` CLI is the **dispatcher** that reads these definitions and launches agents:

1. `scitex-orochi launch <agent-name>` reads the agent definition directory
2. Creates a workspace at `~/.scitex/orochi/workspaces/<agent-name>/`
3. Copies `.mcp.json` and `CLAUDE.md` into the workspace
4. Starts Claude Code in a GNU screen session from the workspace directory

### Current Fleet

| Agent | Role | Description |
|-------|------|-------------|
| `head-mba`, `head-nas`, `head-spartan`, `head-ywata-note-win` | head | Per-host Claude Code development workers |
| `mamba-ywata-note-win` | task-manager | Task dispatch, dedup, GitHub-issue mirroring |
| `caduceus-mba` | healer | Fleet health monitoring, stuck-agent remediation |
| `master-ywata-note-win` | master | Orchestrator and delegation |
| `telegrammer-ywata-note-win` | telegram | Telegram bridge relay |

See `~/.scitex/orochi/README.md` for full documentation on agent definitions and how to add new agents.

### Agent Type Taxonomy (Guidelines Only)

`src/scitex_orochi/_skills/scitex-orochi/00-agent-types/` documents recurring agent shapes: `00-fleet-lead`, `01-head`, `02-proj`, `03-expert`, `04-worker`, `05-daemon`. These files are **descriptive, not prescriptive**:

- No server code parses them; they are reference only.
- Channel subscriptions and permissions are not derived from type -- they are per-agent and stored in `ChannelMembership`.
- A fleet may have agents that don't fit any type. That is fine -- just build the agent.

<!-- EOF -->
