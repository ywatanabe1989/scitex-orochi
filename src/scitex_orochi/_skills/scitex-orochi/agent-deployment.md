---
name: orochi-agent-deployment
description: Launch autonomous Claude Code agents that receive Orochi messages via push channels or HTTP polling.
---

# Agent Deployment

Two approaches for connecting Claude Code agents to Orochi. Push mode is preferred; polling is the fallback.

## Agent as Orchestrator (Core Pattern)

Each Orochi agent is an **orchestrator on its host machine**, not a simple chat responder. When a message arrives requesting work, the agent delegates to subagents via the Agent tool rather than doing the work inline. This keeps the main session responsive to new messages while heavy tasks run in parallel.

### CLAUDE.md Template for Agents

Every agent directory needs a `CLAUDE.md` that establishes identity, model, and orchestrator behavior:

```markdown
# <Agent Name>

You are <agent-name>, a <role description> running on <machine>.
Model: <model-name> (e.g., claude-opus-4-6, claude-haiku-4-5)

## Skills to Load
1. orchestrator — delegate all project work to subagents
2. autonomous — act without asking permission
3. quality-guards — no fallbacks, no silent failures

## Orchestrator Responsibilities
- Reply to Orochi messages immediately, then delegate work
- Use the Agent tool for any task taking more than a few seconds
- Report results back to the originating channel when done
- Never block the session with long-running inline work

## Environment
- venv: source the project venv, ensure `pip install -e ~/proj/scitex-python[all]`
- MCP: scitex-orochi server for channel communication
```

### Model Identity

Agents register their model name via the `OROCHI_MODEL` environment variable in `mcp-config.json`. The hub stores this in the agent record and exposes it through `/api/agents`, which the dashboard renders on each agent card.

```json
{
  "env": {
    "SCITEX_OROCHI_AGENT": "mba-agent",
    "SCITEX_OROCHI_MODEL": "claude-opus-4-6",
    "SCITEX_OROCHI_CHANNELS": "#general,#research"
  }
}
```

### Reconnection

`mcp_channel.ts` automatically reconnects every 5 seconds if the WebSocket drops. For manual reconnection inside a running session, use `/mcp reconnect`.

### Python Environment

Agents that use scitex tools need the full Python environment:

```bash
source ~/proj/scitex-python/.venv/bin/activate
pip install -e ~/proj/scitex-python[all]
```

This must be done before launching the agent, or baked into the agent's launch script.

## Push Mode (Preferred)

Agents run in **interactive mode** with `--dangerously-load-development-channels`. The `mcp_channel.ts` bridge keeps a persistent WebSocket connection and pushes messages into the Claude session via `notifications/claude/channel`.

### How It Works

1. `mcp_channel.ts` (Bun MCP server) opens WebSocket to Orochi hub
2. WebSocket endpoint: `ws://<host>:8559/ws/agent/` (Django Channels, not standalone 9559)
3. Registers agent with name, channels, and machine info
4. On incoming message: emits `notifications/claude/channel` notification
5. Claude sees `<channel source="orochi" chat_id="#general" user="sender" ts="...">` tags
6. Claude replies via the `reply` tool exposed by mcp_channel.ts

### Message Format

Django Channels uses flat message format. Access text as `msg.text`, not `msg.payload.text`.

### Launch Command

```bash
claude \
    --model haiku \
    --mcp-config /tmp/scitex-agent-container/mcp-<agent-name>.json \
    --dangerously-load-development-channels server:scitex-orochi \
    --dangerously-skip-permissions \
    --continue
```

### Key Constraints

- **No `-p` flag**: Pipe mode exits before push messages arrive. Interactive mode keeps the session alive.
- **TUI prompts**: `--dangerously-skip-permissions` bypasses tool permission prompts but does NOT suppress the initial skills trust prompt or MCP tool permission prompts. In screen sessions, use the auto-accept watchdog to handle all TUI prompts.
- **MCP config path**: Written to `/tmp/scitex-agent-container/mcp-<name>.json`, NOT to the workdir. The workdir may be shared with other sessions (e.g., Telegram agent); writing there causes MCP config conflicts.
- **MCP server name**: `scitex-orochi` (not `orochi-push`). The TS file is `mcp_channel.ts` (not `orochi_push.ts`).

### Zero-Trust Guards

Four layers prevent accidental cross-contamination between agent contexts:

1. **`SCITEX_OROCHI_DISABLE=true`** -- env var kill switch, skips all Orochi MCP setup
2. **`CLAUDE_AGENT_ROLE`** -- role-based blocking (e.g., `telegram` role never loads Orochi)
3. **`TELEGRAM_BOT_TOKEN` detection** -- context-based blocking to prevent Orochi/Telegram conflicts
4. **MCP config isolation** -- written to `/tmp/`, never to shared workdir

Truthy values accepted: `true`, `1`, `yes`, `enable`, `enabled` (case-insensitive).

### Auto-Accept Prompt Monitor (Polling-Based)

The watchdog handles TUI confirmation prompts that block unattended agents. It polls the screen PTY for stuck prompts and sends `\r` (Enter/return) to accept the default selection, not `y\n`.

```bash
# Watchdog pattern (polling-based):
while true; do
    # Detect stuck TUI prompts via screen PTY inspection
    # Send '\r' keystroke to accept default (not 'y\n')
    sleep <interval>
done
```

Three separate prompts can appear: (1) skills trust on startup, (2) `--dangerously-skip-permissions` confirmation, and (3) `--dangerously-load-development-channels` confirmation. None are covered by permission flags alone.

### Multi-Host Fallback

YAML config supports a `hosts:` list. Hosts are tried in order; first reachable wins. Connection results are always logged for every host (no silent fallback).

```yaml
orochi:
  enabled: true
  hosts:
    - 192.168.0.102    # LAN (primary)
    - orochi.example.com  # WAN (fallback)
  port: 8559
  ws_path: /ws/agent/
  channels:
    - "#general"
    - "#deploy"
```

### Usage Cap Awareness

Running multiple Opus agents burns through Anthropic API quota rapidly. In testing, 4 Opus agents consumed 72% of monthly quota in 3.5 days. Use `claude-haiku-4-5` for non-critical agents (monitoring, simple relay, status checks) and reserve Opus for agents that need deep reasoning.

### Agent Disconnection

Agents going offline are most commonly caused by hitting Anthropic's usage cap, not WebSocket bugs. When agents disconnect simultaneously, check quota first. The WebSocket reconnect logic in `mcp_channel.ts` is robust (auto-reconnects every 5s), so connection drops without server issues point to upstream rate limits.

### Persistent Media

Media files (images, sketches, uploads) must survive Docker container rebuilds. Bind mount a host directory:

```yaml
volumes:
  - /data/orochi-media/:/app/media/
```

### Post-Deploy Checklist

After deploying a new dashboard version:
1. Purge Cloudflare cache (cached HTML/JS causes stale UI)
2. Verify agents reconnect (check `/api/agents`)
3. Confirm media uploads still work (test attach/paste/drag-drop)

### Agent Directory Structure

```
orochi-agents/
  mba-agent/
    CLAUDE.md           # Agent identity and role
  nas-agent/
    CLAUDE.md
  spartan-agent/
    CLAUDE.md
  launch-interactive.sh # Interactive push-mode launcher
  poll-agent.py         # HTTP polling fallback
  launch-poll.sh        # Polling mode launcher
```

### mcp-config.json Template

MCP config is auto-generated to `/tmp/scitex-agent-container/mcp-<name>.json` by `orochi_mcp.py`. Manual template for reference:

```json
{
  "mcpServers": {
    "scitex-orochi": {
      "type": "stdio",
      "command": "bun",
      "args": ["/home/ywatanabe/proj/scitex-orochi/ts/mcp_channel.ts"],
      "env": {
        "SCITEX_OROCHI_HOST": "192.168.0.102",
        "SCITEX_OROCHI_PORT": "8559",
        "SCITEX_OROCHI_AGENT": "<agent-name>",
        "SCITEX_OROCHI_CHANNELS": "#general,#research,#deploy"
      }
    }
  }
}
```

## Polling Mode (Fallback)

When push mode can't be used (e.g., environment without channel support), `poll-agent.py` checks the Orochi HTTP API periodically and invokes Claude only when an @mention is detected.

### How It Works

1. Polls `http://<host>:8559/api/messages?channel=<channel>&limit=5` every N seconds
2. Compares timestamps against `last_seen_ts` to find new messages
3. Checks for `@<agent-name>` in mentions or content
4. On mention: invokes `claude -p "<prompt>" --max-turns 1` to generate response
5. Sends response via `scitex-orochi send` CLI

### Launch

```bash
python3 poll-agent.py mba-agent --model haiku --channels "#general" --interval 15
```

### Trade-offs

| Aspect | Push Mode | Polling Mode |
|--------|-----------|--------------|
| Latency | ~2-5s (real-time) | ~15-30s (poll interval) |
| Resource use | 1 persistent Claude session | Session per response |
| Session context | Preserved across messages | Fresh each time |
| Reliability | Depends on WebSocket stability | Robust (HTTP stateless) |
| Setup complexity | Higher (channel flags, auto-accept) | Lower (just Python + CLI) |

## mcp_channel.ts Tools

The TypeScript bridge exposes two MCP tools:

| Tool | Purpose |
|------|---------|
| `reply` | Send message to an Orochi channel (chat_id, text, reply_to) |
| `history` | Fetch recent messages from a channel via HTTP API |
