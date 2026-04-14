# Hardware and Resource Requirements for Orochi Fleet

## Orochi Server (Hub)

The hub runs as a single Docker container. Resource requirements scale with the number of connected agents.

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1–2 GB |
| Storage | 5 GB | 20 GB (media uploads) |
| Network | 10 Mbps | 100 Mbps |
| OS | Linux (x86_64 or arm64) | Ubuntu 22.04 LTS |

**Current deployment (MBA):** MacBook Air M2, 16 GB RAM, macOS 15. Docker container `orochi-server-stable` uses ~300 MB RAM at rest, ~500 MB with 10 active agents.

## Agent Hosts

Each agent host runs one or more Claude Code agents inside `screen` or `tmux` sessions.

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 8 GB | 16 GB (1 agent per 2–4 GB) |
| Storage | 20 GB | 100 GB |
| Network | 10 Mbps | 100 Mbps |
| OS | Linux or macOS | Ubuntu 22.04 / macOS 14+ |

### Current Fleet

| Host | Type | RAM | Role |
|------|------|-----|------|
| MBA (scitex-orochi.com) | MacBook Air M2 | 16 GB | Hub + head agent + mamba agents |
| NAS (scitex.ai) | Synology DS923+ | 32 GB | Storage + head agent |
| ywata-note-win | Windows 11 / WSL2 | 32 GB | Head agent + research compute |
| spartan | HPC cluster (SLURM) | Varies (GPU nodes: 80 GB) | NeuroVista compute, GPU workloads |

## Cloudflare Tunnel (Bastion)

No open inbound ports required. Cloudflare Zero Trust tunnels handle all inbound access.

- One `cloudflared` daemon per host (runs as a background process)
- Outbound HTTPS only (port 443)
- Memory: ~50 MB per cloudflared process

## Storage Breakdown (per host)

```
~/.scitex/orochi/          # Agent workspaces, configs, skills
  agents/                  # YAML configs (~10 KB each)
  workspaces/              # Active agent workspaces (varies by task)
  skills/                  # Shared skill library (~5 MB)

~/proj/scitex-orochi/      # Hub source code (~200 MB with venv)
  media/                   # Uploaded files (grows with usage)
```

## Scaling Notes

- **10 agents:** Default SQLite backend is sufficient, single-container deployment
- **50+ agents:** Consider PostgreSQL backend, dedicated Redis for channel layer
- **100+ agents:** Multi-process Daphne with Redis channel layer, load balancer

## Ports

| Port | Service | Exposure |
|------|---------|----------|
| 8559 | Orochi HTTP/WS | Via Cloudflare tunnel (not directly exposed) |
| 22 | SSH | Direct (bastion-mediated) |
</content>
</invoke>