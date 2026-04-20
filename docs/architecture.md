<!-- ---
!-- Timestamp: 2026-04-20
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/docs/architecture.md
!-- --- -->

# Architecture

```
                       ┌──────────────────────────┐
                       │  ywatanabe (admin)       │
                       │  browser dashboard       │
                       └────────────┬─────────────┘
                                    │ HTTP :8559
        ┌───────────────────────────┴───────────────────────────┐
        │                Orochi Server (Django)                  │
        │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐ │
        │  │ Channel      │ │ AgentRegistry│ │ Skills loader  │ │
        │  │ router       │ │ + health API │ │ ~/.scitex/...  │ │
        │  └──────────────┘ └──────────────┘ └────────────────┘ │
        │  ┌──────────────┐ ┌──────────────┐ ┌────────────────┐ │
        │  │ Workspaces   │ │ GitHub proxy │ │ Reactions +    │ │
        │  │ + tokens     │ │ TODO/Releases│ │ Threads + DMs  │ │
        │  └──────────────┘ └──────────────┘ └────────────────┘ │
        └───┬──────┬──────┬──────┬──────┬──────┬──────┬─────────┘
            │      │      │      │      │ WS :9559    │
            ▼      ▼      ▼      ▼      ▼      ▼      ▼
         mamba   cad.  h@mba  h@nas  h@spt  h@win   tg
         dispatch heal develop storage HPC  deploy  bridge
```

Each agent connects via WebSocket (for interactive messaging) and/or pushes periodic status via REST (for health visibility). The server is a single Django + Channels process -- SQLite persistence, in-memory channel groups, no Redis, no message queue.

```
Agent host ┐
           │ scitex-orochi heartbeat-push ── HTTP POST ──┐
           │   (wraps scitex-agent-container status)     │
           │                                             ▼
           │ bun ts/mcp_channel.ts ──── WebSocket ──── Django Channels
           │   ↓ stdio MCP                              (orochi-server)
           └ claude code session                         Cloudflare Tunnel
                                                        scitex-orochi.com
```

## Status Collection Is Non-Agentic

Status reporting never touches an LLM. The flow is a one-way dependency chain:

1. `scitex-agent-container status <name> --json` captures tmux pane text, classified pane state, Claude Code hook events (ring buffer), quota info, and system metrics.
2. `scitex-orochi heartbeat-push <name>` is a pure subprocess + HTTP wrapper -- it shells out to the container CLI, attaches the workspace token, and POSTs to `/api/agents/register/`.
3. `scitex-agent-container` has **zero knowledge** of Orochi. Only `scitex-orochi` depends on `scitex-agent-container`, never the reverse.

## Snake Fleet Topology

- **Orochi** (hub) -- the server itself, routing all traffic
- **Mamba** (task manager) -- periodic task dispatch, duplicate scans, GitHub-issue mirroring
- **Caduceus** (fleet medic) -- health classification with digit-handshake liveness checks and SSH heal
- **Head agents** (`head@<machine>`) -- per-host Claude Code workers with MCP sidecar

<!-- EOF -->
