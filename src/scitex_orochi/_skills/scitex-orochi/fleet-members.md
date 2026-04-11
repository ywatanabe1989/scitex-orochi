---
name: orochi-fleet-members
description: Core fleet members — agent names, roles, host machines, and directory conventions.
---

# Fleet Members

All agents connected to the Orochi hub. Definitions are the single source of truth.

## Agent Definitions

| Agent | Host | Role | Model |
|-------|------|------|-------|
| head-ywata-note-win | ywata-note-win (WSL) | head | opus |
| head-mba | mba | head | opus |
| head-nas | nas | head | opus |
| head-spartan | spartan | head | opus |
| mamba-mba | mba | task-manager | opus |
| caduceus-mba | mba | healer | haiku |

## Directory Conventions

### Agent Definitions (shared via dotfiles, single source of truth)

```
~/.scitex/orochi/agents/<agent-name>/
  <agent-name>.yaml    # YAML definition
  CLAUDE.md            # Agent identity and instructions
```

Flat layout also supported: `~/.scitex/orochi/agents/<agent-name>.yaml`

### Workspace Directories (ephemeral runtime, per-host)

```
~/.scitex/orochi/workspaces/<agent-name>/
```

Each agent's workspace is created at launch by `scitex-agent-container`. The workspace contains a symlinked `.claude/CLAUDE.md` pointing back to the definition directory.

## Hub Address

| Context | Address |
|---------|---------|
| LAN (ywata-note-win, mba, nas) | `192.168.0.102:9559` |
| External (spartan) | `orochi.scitex.ai` (Cloudflare proxy, port 443) |
| Dashboard | `https://scitex-orochi.com/` or `http://192.168.0.102:8559` |

## Agent Roles

- **head** — General-purpose orchestrator on a host machine. Delegates work to subagents, stays responsive to messages.
- **task-manager** (mamba) — Monitors GitHub issues, tracks TODOs, reports to `#todo` channel.
- **healer** (caduceus) — Auto-heals low-risk agent issues (LP-001 through LP-009 learned patterns), escalates destructive actions.
