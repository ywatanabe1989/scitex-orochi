---
name: orochi-skill-manager-architecture
description: Two-layer architecture for fleet skill lifecycle. Splits `worker-skill-manager-<host>` (agent-layer worker, LLM-backed, on-demand queries) from `skill-sync-daemon` (process-layer daemon, no LLM, periodic rollup loop on primary host launchd primary + standby host systemd warm-standby via idempotent dual-run). First pilot of the hybrid-worker split pattern. Ratified 2026-04-14 msg#11475.
---

# Skill-Manager Architecture

The fleet's skill lifecycle (CRUD, aggregation, cross-host sync,
drift detection) has two halves with opposite requirements:

1. **Deterministic bulk work** — walking directories, running
   `scitex-dev skills export --clean`, diffing, rsync. Zero LLM
   judgment, pure procedure. Belongs in the **process layer**.
2. **Agentic query work** — "which skill covers X?", "can you
   scitexify this?", "is this skill still accurate given today's
   changes?". Requires LLM judgment. Belongs in the **agent layer**.

Before 2026-04-14 both halves lived inside a single Claude Code
session (`worker-skill-manager-<host>`), which meant the fleet was
burning Claude quota to run a deterministic filesystem scan every
rollup tick. The fix is to split them.

## Origin

See `00-agent-types.md` for the taxonomy that makes this split
the natural default (defining axis: "LLM-in-loop?"). The
skill-manager is intentionally the **first** hybrid agent to split,
so the same pattern can be applied immediately to
`worker-todo-manager-<host>` (parallel pilot `todo-sweep-daemon`), and
subsequently to `worker-synchronizer-<host>`, `worker-auth-manager-<host>`,
and others.

The host choice evolved across two phases (see
`00-agent-types.md` Origin for the full arc):

- **Phase 1** (msg#11438–#11448): standby host proposed as the sole daemon
  host because it's 24/7 on and systemd-native.
- **Phase 2** (msg#11464, #11483–#11502): empirical standby host load from
  `scitex-cloud` SLURM visitor sessions (6 concurrent jobs, 12/12
  CPU, 24GB allocated) plus primary host's better stability per the operator's
  assessment → pilot moves to **primary host primary + standby host warm-standby**
  via idempotent dual-run (head-<host> option (d), msg#11499).
- **Ratification**: msg#11475 the operator "final check before GO".

## The split

```
╔═══════════════════════════════════════════════════════════════╗
║  AGENT LAYER (LLM-backed, quota-consuming)                    ║
║                                                               ║
║    worker-skill-manager-<host>                                    ║
║    role=worker  function=[skill-sync, taxonomy-curator]       ║
║    host=primary host (Claude Code session)                             ║
║    job=Track B (on-demand queries)                            ║
║                                                               ║
║    Reads skill files, answers "where is X", drafts new        ║
║    skills from conversation, scitexifies legacy scripts,      ║
║    curates taxonomy revisions. Silent otherwise.              ║
╠═══════════════════════════════════════════════════════════════╣
║  PROCESS LAYER (no LLM, quota-zero)                           ║
║                                                               ║
║    skill-sync-daemon                                          ║
║    role=daemon  function=[skill-sync]                         ║
║    host=primary host launchd (primary)                                 ║
║         + standby host systemd (warm-standby, idempotent dual-run)     ║
║    cadence=30 min on both hosts                               ║
║    job=Track A (periodic rollup)                              ║
║                                                               ║
║    Scans the 4 skill locations, runs scitex-dev skills        ║
║    export --clean, diffs, rsync to dotfiles, writes           ║
║    one-line result to host-local log. Never holds a           ║
║    WebSocket session. Idempotent — running on both hosts      ║
║    produces the same output, no shared lease required.        ║
╚═══════════════════════════════════════════════════════════════╝
```

## Continued in

- [`52_fleet-skill-manager-architecture-impl.md`](52_fleet-skill-manager-architecture-impl.md)
