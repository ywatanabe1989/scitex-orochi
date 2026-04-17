<!-- ---
!-- Timestamp: 2026-04-16 21:22:35
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types.md
!-- --- -->

---
name: agent-types
description: Fleet agent type definitions — 2 layers (process/agent), 6 roles (daemon / lead / head / worker / proj / expert). Defining axis is "LLM-in-loop?".
---

# Agent Types

### Communicator
## Lead

### Coordinator
## Head

### Dedicated scope
## Proj
## Expert

## For repetitive tasks
### Worker
### Daemon

## Definitinos

| Role       | Definition                                                                                                                   | Naming                     | Example                                              |
|------------|------------------------------------------------------------------------------------------------------------------------------|----------------------------|------------------------------------------------------|
| **lead**   | The main communication interface to the user. A logical agent for redundancy.                                                | `fleet-lead`               | `fleet-lead`                                         |
| **head**   | Per-host representative. Understand the direction of the fleet. Knows the host machine most. Spawn actual working subagents. | `head-<host>`              | `head-host-a`, `head-host-b`                         |
| **proj**   | Project-scoped. Dedicated to a single repo. Deep codebase context. Reports to host's head.                                   | `proj-<project>-<host>`    | `proj-my-package-host-a`, `proj-my-paper-host-b`     |
| **expert** | Domain expert. Consulted for specialized knowledge, not dispatched for tasks.                                                | `expert-<domain>-<host>`   | `expert-scitex-host-a`                               |
| **worker** | Similar to daemon but agent for tasks difficult to code. Expected to have minimal communication channels.                    | `worker-<function>-<host>` | `worker-healer-host-a`, `worker-todo-manager-host-a` |
| **daemon** | Not agent but deterministic, programmatic loop.                                                                              | `daemon-<name>`            | `audit-closes.timer`, `skill-sync-daemon`            |

## Legacy Prefix Migration

The `mamba-` prefix is deprecated. New agents use `worker-`:

| Old (deprecated) | New |
|-------------------|-----|
| `mamba-healer-<host>` | `worker-healer-<host>` |
| `mamba-skill-manager-<host>` | `worker-skill-manager-<host>` |
| `mamba-todo-manager-<host>` | `worker-todo-manager-<host>` |
| `mamba-<function>-<host>` | `worker-<function>-<host>` |

## Anti-Patterns

1. **Daemon running Claude session** — contradiction. No LLM = daemon.
2. **Worker with no agentic decisions** — extract to daemon.
3. **Two leads** — cardinality-1 is the rule.
4. **Head speaking for another host** — route through correct head.
5. **Proj agent working outside its project** — escalate to head.
6. **Expert doing task execution** — reclassify as worker.
7. **Daemons posting to chat** — write to log; agent layer reads it.

## Daemon Host Policy

> Choose the host by what the daemon *costs*, not by what's convenient.

| Host type | Accepts | Rejects |
|-----------|---------|---------|
| **Stable workstation** | CPU-hot daemons (launchd/systemd) | — |
| **NAS / storage host** | I/O-light, CPU-cheap only | CPU-hot (competes with production workloads) |
| **NAS (via scheduler)** | Heavy work via SLURM/job queue | Direct exec for CPU-hot |
| **HPC cluster** | Cheap daemons, heavy via `sbatch` | Login-node compute |
| **WSL / secondary** | Cheap daemons | Heavy without job scheduler |

<!-- EOF -->