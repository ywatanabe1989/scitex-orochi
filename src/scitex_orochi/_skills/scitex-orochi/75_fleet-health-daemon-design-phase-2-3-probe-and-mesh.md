---
name: orochi-fleet-health-daemon-design-phase-2-3-probe-and-mesh
description: Phase 2 (multi-signal health probe schema, threshold transitions) and Phase 3 (mamba-healer mesh + cross-host probing) of the fleet-health-daemon. (Split from 58_fleet-health-daemon-design-phases-later.md.)
---

> Sibling: [`58_fleet-health-daemon-design-phase-1-quota.md`](58_fleet-health-daemon-design-phase-1-quota.md) for Phase 1 quota scraping.

## 5. Phase 2 — Multi-signal health probe

The original todo#146 scope. Everything below is Phase 2 and later.
It ships as follow-up PRs after Phase 1 lands.

### 5.1 Signals

Every 30 s the daemon emits one NDJSON record containing a fixed
set of host-local health metrics on top of the Phase 1 quota
fields.

```
ts                       ISO-8601 UTC, second precision
host                     short hostname (mba / nas / spartan / ywata-note-win)
probe_version            semver of fleet-health-daemon itself
load_1  load_5  load_15  /proc/loadavg columns 1-3
ncpu                     int, nproc output
cpu_pressure_some_avg10  /proc/pressure/cpu "some avg10" value
mem_total_kb             /proc/meminfo MemTotal
mem_avail_kb             /proc/meminfo MemAvailable
slurm_running            squeue -h -t R | wc -l (NAS/Spartan/WSL only; 0 elsewhere)
slurm_pending            squeue -h -t PD | wc -l
slurm_cpu_used           sum of RES cpus over running jobs
failed_user_units        systemctl --user list-units --state=failed | grep -c .service
failed_sys_units         systemctl list-units --state=failed | grep -c .service (read-only)
docker_count             int, running container count (0 on hosts without docker)
docker_top_cpu_pct       float, max cpu_pct (% stripped at producer)
docker_total_cpu_pct     float, sum of cpu_pct (% stripped at producer)
docker_containers        array of {name: str, cpu_pct: float, mem_usage: str, mem_pct: float}
cf_bastion_active        bool, cloudflared tunnel active
cf_pid                   int or null
mcp_duplicates           {<agent-name>: [<pid>, <pid>, ...]} — only agents with >1 mcp_channel procs
claude_procs             {<agent-name>: int} — count of claude code processes per agent session
tmux_sessions            int, tmux ls count
pane_states              {<session>: <pane-state-regex-class>} via pane-state-patterns.md
```

Schema v2 spec for `docker_containers` per-container percentages:
floats, with `%` suffix stripped at the producer side via a
`docker stats --format` template that wraps `{{.CPUPerc}}` /
`{{.MemPerc}}` (head-mba decision msg#11748). `mem_usage` stays as
the composite string pair `"used / total"` because splitting at
the producer forces a unit choice the consumer doesn't own.

**Docker-absent guard** — Spartan has no docker, WSL's docker is
uncertain. The prober treats `command -v docker` as a per-tick
feature check: on hosts without docker, emit `docker_count=0`,
`docker_top_cpu_pct=0.0`, `docker_total_cpu_pct=0.0`,
`docker_containers=[]`. Fields are **always present** so the
schema stays stable and merge-on-`ts` continues to work across
heterogeneous hosts.

### 5.2 Threshold transitions

Same breadcrumb discipline as §4.3 Phase 1. The daemon is
silent-otherwise.

| Signal                              | Concerning when                                   | N samples | Breadcrumb file                                   |
|-------------------------------------|---------------------------------------------------|-----------|---------------------------------------------------|
| `docker_top_cpu_pct`                | > 200% sustained (any container)                  | 3         | `fleet-health.docker-cpu-spike.<container>`       |
| `docker_top_cpu_pct` (smoking-gun)  | > 100% on a single-process container (e.g. django) | 1       | Immediate breadcrumb. msg#11730 showed `scitex-cloud-prod-django-1` at 100.95% — canonical slow-failure example |
| `cpu_pressure_some_avg10`           | > 15.0                                            | 3         | `fleet-health.cpu-pressure`                        |
| `failed_user_units`                 | > 0 (any fleet-relevant unit)                     | 1         | `fleet-health.failed-unit.<unit>`                 |
| `mcp_duplicates` count              | > 1 for any agent                                 | 1         | `fleet-health.mcp-dup.<agent>`                    |
| `pane_states`                       | matches `permission_prompt` or `stuck`            | 3         | `fleet-health.pane-stuck.<session>`               |
| `mem_avail_kb`                      | < 10% of `mem_total_kb`                           | 3         | `fleet-health.mem-low`                             |
| `load_1` / `ncpu`                   | > 2.0                                             | 6 (3 min) | `fleet-health.loadavg-high`                        |
| `claude_procs` count for one agent  | > 1                                               | 1         | `fleet-health.claude-dup.<agent>` (do **not** auto-resolve, see §11) |

Breadcrumbs contain one line: triggering signal value, ISO-8601
timestamp, last-3-samples JSON. The daemon does not delete them;
the worker deletes after handling and writes a sibling
`<breadcrumb>.handled` file for audit.

## 6. Phase 3 — `mamba-healer-<host>` consumer + mesh redundancy

Once Phase 1 and Phase 2 are emitting NDJSON + breadcrumbs, the
existing `mamba-healer-{mba,nas}` workers extend their contract:

1. **Primary input source shifts.** Instead of DM-polling peers
   as the main signal, workers read their host-local
   `fleet-health-daemon.ndjson` and breadcrumb directory as the
   primary input. DM polling becomes the liveness-of-last-resort
   check (random-nonce-ping-protocol cadence, 60 s).
2. **Cross-host mutual probing** — each worker DM-pings its peers
   on the other hosts every 30 s. If any healer goes silent, its
   peers notice within one cadence and escalate to `#escalation`.
   This is the "healer redundancy" ywatanabe asked for in
   msg#11775: no single healer is load-bearing.
3. **Recovery authority stays worker-side.** Daemon never acts.
   Workers own keystroke injection, process kill, systemd
   restart, `/compact` trigger. See §8 Phase 4 playbook.
4. **New healer hosts**: `mamba-healer-spartan` and
   `mamba-healer-ywata-note-win` are added to the fleet in this
   phase so all four hosts have a local healer. Spartan variant
   obeys the constraint matrix in §9 (no sudo, Lmod init, tmux
   loop, no docker signal).

Worker cadence: still 30 s idle → breadcrumb-driven. DM
cross-probe: 60 s. LLM time is only spent on interpretation and
recovery, not polling.
