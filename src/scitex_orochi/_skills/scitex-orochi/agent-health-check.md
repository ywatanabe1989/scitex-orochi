---
name: orochi-agent-health-check
description: Step-by-step health checklist for verifying an Orochi agent is fully operational.
---

# Agent Health Check

Verify each agent in order. A failure at any step means later steps will also fail.

## Checklist

### 1. SSH Connection

The host machine is reachable.

```bash
ssh <host> hostname
```

### 2. Screen Session

The agent's screen session exists and is detached (running).

```bash
ssh <host> screen -ls | grep <agent-name>
```

Expected: line containing `<agent-name>` with status `(Detached)`.

### 3. Claude Code Process

The Claude Code CLI is running inside the screen session.

```bash
ssh <host> pgrep -la claude
```

Expected: at least one process matching the agent's session.

### 4. Bun MCP Sidecar

The `mcp_channel.ts` TypeScript bridge is running alongside Claude.

```bash
ssh <host> 'pgrep -la bun | grep mcp_channel'
```

Expected: a bun process with `mcp_channel` in its arguments.

### 5. WS Connected to Hub

The agent appears in the hub's live registry.

```bash
curl -s https://scitex-orochi.com/api/agents/ | python3 -m json.tool | grep <agent-name>
```

Or from the dashboard Agents tab — the agent should show as connected.

### 6. Dev Channel Dialog Cleared

The agent is not stuck on the "Do you want to proceed?" TUI prompt for `--dangerously-load-development-channels`. This prompt blocks all message processing.

**Diagnosis**: Attach to the screen session and check visually:

```bash
ssh <host> -t screen -r <agent-name>
```

If stuck, send Enter via screen:

```bash
ssh <host> screen -S <agent-name> -X stuff $'\n'
```

### 7. MCP Tools Functional

The agent can send messages via its MCP tools (reply, history, etc.).

**Test**: Send a message from the agent's session or trigger a reply via @mention. The message should appear in the Orochi chat.

### 8. @mention Responsive

The agent responds to direct mentions.

**Test**: In the dashboard or via CLI, send:

```bash
scitex-orochi send '#general' "@<agent-name> hello"
```

Expected: the agent replies within a few seconds (push mode) or within the poll interval (polling mode).

## Quick Full-Fleet Check

Run the CLI status command to check all agents at once:

```bash
scitex-orochi show-status
```

Or query the API directly:

```bash
curl -s https://scitex-orochi.com/api/agents/ | python3 -c "
import json, sys
agents = json.load(sys.stdin)
for a in agents:
    print(f\"{a['name']:25s} {'CONNECTED' if a.get('connected') else 'OFFLINE':12s} {a.get('machine', '?')}\")
"
```
