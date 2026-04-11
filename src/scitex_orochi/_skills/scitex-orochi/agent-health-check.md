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

### 6b. Permission Prompt Stuck

Claude Code permission dialogs ("Do you want to proceed?", tool approval prompts) block agents entirely. Unlike the dev channel dialog, **`screen -X stuff` keystrokes do NOT work** for these prompts — Claude Code uses raw terminal input (not line-buffered stdin), so injected keystrokes are silently dropped.

This is a known open issue tracked as "Dev channel dialog auto-confirm."

**Workarounds (in order of preference)**:

1. Pre-configure `allowedTools` in the agent's `settings.json` so permission prompts never appear.
2. Launch with `--dangerously-skip-permissions` to bypass tool permission prompts entirely.
3. Use `scitex-agent-container`'s auto-accept script, which handles TUI prompts during launch (but cannot handle mid-session permission prompts).

**When already stuck**: The only current fix is manual interaction (attach to the screen session and press the key) or a full session restart. There is no programmatic way to dismiss a mid-session permission prompt from outside the terminal.

**Root cause found**: Agents were launched without `--dangerously-skip-permissions` despite it being in YAML configs. The launch didn't go through the full scitex-agent-container pipeline — YAML `spec.claude.flags` is only read by the container pipeline, not by manual screen launches.

**Permanent fix**: Add `permissions.allow` to the **workspace-level** `.claude/settings.json` (NOT the global `~/.claude/settings.json`, which would dangerously allow all Claude Code sessions on the machine):

```
<workspace>/.claude/settings.json
```

```json
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Glob(*)",
      "Grep(*)",
      "mcp__scitex-orochi__*"
    ]
  }
}
```

These take effect on next agent restart. Each agent workspace (`~/.scitex/orochi/workspaces/<agent-name>/`) should have its own `.claude/settings.json`.

**Prevention**: Use `scitex-orochi launch` (reads YAML flags properly) or rely on settings.json allowlists.

**Known issue**: `screen -X stuff $'\r'` (raw carriage return) DOES work sometimes — it sends Enter which accepts the default option 1 (Yes). This is unreliable but can unblock agents in a pinch.

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
