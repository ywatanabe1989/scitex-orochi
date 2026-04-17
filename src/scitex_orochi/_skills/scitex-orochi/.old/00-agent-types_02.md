<!-- ---
!-- Timestamp: 2026-04-16 22:06:54
!-- Author: ywatanabe
!-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types.md
!-- --- -->

---
name: agent-types
description: Fleet agent type definitions: lead / head / proj / expert / worker / daemon.
---

# Communicator

## Lead

### Roles
- The main communication interface to the user

### Where to live
- A logical agent for redundancy.

### Naming
- Naming: `fleet-lead`
- Example: `fleet-lead`- 

### Cardinality
- exactly 1

## Head

### Roles
- Per-host representative
- Understands the direction of the fleet
- Knows the host machine most
- Spawns actual working subagents
- Can work across hosts as a team.

### Naming
- Naming: `head-<host>`
- Example: `head-host-a`, `head-host-b`

### Cardinality
- 1 per host

# Dedicated Scope

## Proj

Project-scoped. Dedicated to a single repo. Deep codebase context. Reports to host's head.
- Naming: `proj-<project>-<host>`
- Cardinality: 1 per project x host
- Example: `proj-my-package-host-a`, `proj-my-paper-host-b`

## Expert

Domain expert. Consulted for specialized knowledge, not dispatched for tasks.
- Naming: `expert-<domain>-<host>`
- Cardinality: few
- Example: `expert-scitex-host-a`

# Repetitive Tasks

## Worker

Similar to daemon but agentic — for tasks difficult to code. Expected to have minimal communication channels.
- Naming: `worker-<function>-<host>`
- Cardinality: many
- Example: `worker-healer-host-a`, `worker-todo-manager-host-a`

## Daemon

Not an agent. Deterministic, programmatic loop. No Claude session, zero quota.
- Naming: `daemon-<name>` or `<name>.timer` / `<name>.service`
- Cardinality: many
- Example: `audit-closes.timer`, `skill-sync-daemon`

# Legacy Prefix Migration

The `mamba-` prefix is deprecated. New agents use `worker-`:

- `mamba-<function>-<host>` → `worker-<function>-<host>`
- `neurovista-spartan` → `proj-neurovista-spartan`

# Anti-Patterns

1. **Daemon running Claude session** — contradiction. No LLM = daemon.
2. **Worker with no agentic decisions** — extract to daemon.
3. **Two leads** — cardinality-1 is the rule.
4. **Head speaking for another host** — route through correct head.
5. **Proj agent working outside its project** — escalate to head.
6. **Expert doing task execution** — reclassify as worker.
7. **Daemons posting to chat** — write to log; agent layer reads it.

# Daemon Host Policy

> Choose the host by what the daemon *costs*, not by what's convenient.

- **Stable workstation**: CPU-hot daemons (launchd/systemd)
- **NAS / storage host**: I/O-light, CPU-cheap only. CPU-hot competes with production workloads.
- **NAS (via scheduler)**: Heavy work must go through SLURM/job queue, not direct exec.
- **HPC cluster**: Cheap daemons OK. Heavy work via `sbatch`. No login-node compute.
- **WSL / secondary**: Cheap daemons only. Heavy work needs a job scheduler.

<!-- EOF -->