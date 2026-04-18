<!-- ---
-- Timestamp: 2026-04-16 22:06:54
-- Author: ywatanabe
-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types.md
-- --- -->

---
name: agent-types
description: Fleet agent type definitions: lead / head / proj / expert / worker / daemon.
---

# Communicator

## Lead

### Roles
- The main communication interface to the user

### Communicates with
- To: user, heads
- From: user, heads

### Permissions
- Dispatch tasks to heads
- Escalate to user
- Read all channels

### Autonomy
- Act on user directives immediately
- Aggregate fleet status without asking

### Escalation path
- → user (direct)

### Lifetime
- Persistent

### Quota expectation
- Medium (mostly routing, not heavy compute)

### Where to live
- A logical agent for redundancy

### Naming
- Naming: `fleet-lead`
- Example: `fleet-lead`

### Cardinality
- exactly 1

## Head

### Roles
- Per-host representative
- Understands the direction of the fleet
- Knows the host machine most
- Spawns actual working subagents
- Can work across hosts as a team

### Communicates with
- To: lead, other heads, workers/proj/expert on own host
- From: lead, user (@mention), workers/proj/expert on own host

### Permissions
- SSH to own host
- Restart agents on own host
- Git push (feature branches)
- Spawn/kill subagents on own host

### Autonomy
- Non-destructive actions: act first, report after
- Destructive/cross-host actions: confirm with lead or user first

### Escalation path
- → lead → user

### Lifetime
- Persistent

### Quota expectation
- Medium-high (coordination + own-host work)

### Where to live
- One per physical/virtual host

### Naming
- Naming: `head-<host>`
- Example: `head-host-a`, `head-host-b`

### Cardinality
- 1 per host

# Dedicated Scope

## Proj

### Roles
- Project-scoped
- Dedicated to a single repo
- Deep codebase context
- Reports to host's head

### Communicates with
- To: head (own host), other proj agents (same project, different host)
- From: head (own host)

### Permissions
- Git push (own project's feature branches only)
- Run tests in own repo
- No SSH to other hosts

### Autonomy
- Act freely within own repo
- Cross-repo or destructive changes: confirm with head

### Escalation path
- → head → lead → user

### Lifetime
- Persistent or session-scoped (per project phase)

### Quota expectation
- High (deep codebase work)

### Where to live
- On the host where the project repo lives

### Naming
- Naming: `proj-<project>-<host>`
- Example: `proj-my-package-host-a`, `proj-my-paper-host-b`

### Cardinality
- 1 per project x host

## Expert

### Roles
- Domain expert
- Consulted for specialized knowledge
- Not dispatched for tasks

### Communicates with
- To: whoever asked (respond in same channel)
- From: any agent via @mention or DM

### Permissions
- Read-only across repos
- No git push, no restart, no SSH

### Autonomy
- Responds when consulted
- Does not initiate work unprompted

### Escalation path
- → head (if question is outside expertise)

### Lifetime
- Persistent (always available for queries)

### Quota expectation
- Low (idle between consultations)

### Where to live
- On the host with most relevant resources

### Naming
- Naming: `expert-<domain>-<host>`
- Example: `expert-scitex-host-a`

### Cardinality
- few

# Repetitive Tasks

## Worker

### Roles
- Similar to daemon but agentic — for tasks difficult to code
- Expected to have minimal communication channels

### Communicates with
- To: head (own host), other workers (peer coordination)
- From: head (dispatch), other workers (peer pull)

### Permissions
- Scoped to own function (healer restarts agents, verifier takes screenshots, etc.)
- No direct user communication unless @mentioned

### Autonomy
- Execute assigned tasks without asking
- Report results after completion

### Escalation path
- → head → lead → user

### Lifetime
- Persistent (resident) or ephemeral (task-driven)

### Quota expectation
- Medium (active during tasks, idle between)

### Where to live
- On the host where the function is needed

### Naming
- Naming: `worker-<function>-<host>`
- Example: `worker-healer-host-a`, `worker-todo-manager-host-a`

### Cardinality
- many

## Daemon

### Roles
- Not an agent
- Deterministic, programmatic loop
- No Claude session, zero quota

### Communicates with
- To: log files, touch-files, git commits (no chat)
- From: none (agent layer reads its artifacts)

### Permissions
- File I/O on own host
- No chat, no WebSocket, no Claude session

### Autonomy
- Fully autonomous within its loop
- Does not self-escalate; failures detected by agent-layer healers

### Escalation path
- → (detected by worker-healer) → head → lead → user

### Lifetime
- Persistent (systemd/launchd/cron)

### Quota expectation
- Zero

### Where to live
- Choose by cost, not convenience (see Daemon Host Policy)

### Naming
- Naming: `daemon-<name>` or `<name>.timer` / `<name>.service`
- Example: `audit-closes.timer`, `skill-sync-daemon`

### Cardinality
- many

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
