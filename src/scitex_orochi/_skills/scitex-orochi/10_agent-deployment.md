<!-- ---
!-- Timestamp: 2026-04-17 00:10:37
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/agent-deployment.md
!-- --- -->

---
name: orochi-agent-deployment
description: Launch autonomous Claude Code agents that receive Orochi messages via push channels or HTTP polling.
---

# Agent Deployment

Two approaches for connecting Claude Code agents to Orochi. Push mode is preferred; polling is the fallback.

### CLAUDE.md Template for Agents

Every agent directory needs a `CLAUDE.md` that establishes identity, model, and orchestrator behavior:

```markdown
# <Agent Name>

You are <agent-name>, a <role description> running on <machine>.
Model: <model-name> (e.g., claude-opus-4-7, claude-haiku-4-5)

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

Agents register their model name via the `SCITEX_OROCHI_MODEL` environment variable in `mcp-config.json`. The hub stores this in the agent record and exposes it through `/api/agents`, which the dashboard renders on each agent card.

```json
{
  "env": {
    "SCITEX_OROCHI_AGENT": "my-agent",
    "SCITEX_OROCHI_MODEL": "claude-opus-4-7"
  }
}
```

> Channel subscriptions are server-authoritative — assigned via MCP tools,
> REST API, or web UI after the agent registers. Do not bake channel lists
> into env vars or launch configs.

### Reconnection

`mcp_channel.ts` automatically reconnects every 5 seconds if the WebSocket drops. For manual reconnection inside a running session, use `/mcp reconnect`.

### Python Environment

Agents that use scitex tools need the full Python environment:

```bash
source ~/proj/scitex-python/.venv/bin/activate
pip install -e ~/proj/scitex-python[all]
```

This must be done before launching the agent, or baked into the agent's launch script.

## Head Agent Behavior

Head agents are the primary orchestrators for their host machine. Their core responsibility is staying responsive on the Orochi channel at all times.

**Delegation is mandatory.** Head agents must NOT do heavy work directly. All non-trivial tasks must be delegated to subagents or background processes:

- SSH connectivity checks and fleet health scans
- Code changes, debugging, and research
- File operations, test runs, and builds
- Any task that could take more than a few seconds

**The 30-second rule.** A head agent must never go silent for more than 30 seconds while doing direct work. If a task will take longer, delegate it immediately and acknowledge the request on the channel.

**Report results incrementally.** As subagent results come in, relay them to the originating channel. Do not batch results or wait for all tasks to finish before responding.

**Pattern**: Receive message on channel -> acknowledge immediately -> spawn subagent(s) -> report results as they arrive -> stay idle and responsive for the next message.

## Continued in

- [`65_agent-deployment-extras.md`](65_agent-deployment-extras.md)
