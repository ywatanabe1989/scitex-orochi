<!-- ---
-- Timestamp: 2026-04-16 22:30:00
-- Author: ywatanabe
-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types/90-policies.md
-- --- -->

---
name: agent-type-policies
description: Anti-patterns, legacy migration, and daemon host policy.
---

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
