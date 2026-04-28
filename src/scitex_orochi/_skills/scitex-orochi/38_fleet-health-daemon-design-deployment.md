---
name: orochi-fleet-health-daemon-design-deployment
description: Host-specific deployment, resource discipline, cross-host coverage, probe-vs-pane liveness divergence, anti-patterns, open questions, implementation order, and related skills for the fleet-health-daemon design.
---

# fleet-health-daemon — Deployment, discipline, anti-patterns

> Sub-file of `fleet-health-daemon-design.md`. See the orchestrator for context.

## 8. Host-specific deployment

The same daemon body runs everywhere, but the scheduler wrapper
differs per host. All wrappers call the same
`~/.scitex/orochi/bin/fleet-health-daemon` entrypoint and write
to the same canonical log path
`~/.scitex/orochi/logs/fleet-health-daemon.ndjson`. Breadcrumbs
live under
`$HOME/.scitex/orochi/probes/fleet-health-daemon/`.

| Host                | Scheduler                                                                          | Notes                                                                                               |
|---------------------|------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| **MBA**             | `launchd` — `~/Library/LaunchAgents/com.scitex.orochi.fleet-health-daemon.plist`   | `StartInterval=30`, `RunAtLoad=true`, `KeepAlive=false`. Primary host for first pilot.              |
| **NAS**             | `systemd --user` — `~/.config/systemd/user/fleet-health-daemon.timer` + `.service` | `OnUnitActiveSec=30s`, `Nice=10`, `IOSchedulingClass=best-effort`, `IOSchedulingPriority=6`. I/O-light, CPU-cheap, fine under the daemon-host policy. |
| **Spartan**         | `.bash_profile` wrapper + `tmux` loop (no sudo, no systemd --user, no cron)        | Runs inside the `head-spartan` tmux session as a background process. Cadence enforced by `sleep 30` in the loop. Entrypoint uses the Lmod `Python/3.11.3` workaround from `agent-autostart.md` / PR #141. |
| **WSL (ywata-note-win)** | `systemd --user` — same unit as NAS                                             | `SCITEX_ON_WSL=1` flag exposes WSL-specific metrics (interop, DrvFs mounts).                        |

### 8.1 Spartan-specific constraint matrix

Spartan is not a generic Linux host from the daemon's point of
view. Constraint list from head-spartan msg#11753:

1. **No systemd user units, no `loginctl enable-linger`.** Login1
   enforces `cgroup nproc=1`; `systemctl --user enable` fails.
2. **No sudo, ever** — including `sudo -n true`. Guardrail in
   `999_unimelb_spartan.src` refuses every sudo invocation.
3. **No user crontab** on login1. `cgroup nproc=1` propagates.
4. **No launchd / no plist** — macOS-only.
5. **Works**: a `tmux` session started from `.bash_profile`
   running a `while true; sleep 30; ...; done` probe loop.
6. **Lmod env init mandatory for any Python process** — start
   the probe loop under `bash -l -c 'module load GCCcore/11.3.0
   Python/3.11.3 && exec <cmd>'`. If the prober is pure bash, no
   Lmod needed; if it shells out to Python, Lmod is mandatory.
7. **No docker on Spartan.** Guard every `docker` invocation with
   `command -v docker`; emit `docker_count=0` / `docker_containers=[]`
   rather than dying.
8. **cpu.pressure is readable** via `cat /proc/pressure/cpu`.
9. **MCP process dedup command is identical** to other hosts.
10. **Breadcrumb directory**: `$HOME/.scitex/orochi/probes/fleet-health-daemon/`
    — not `/tmp` (node-local, doesn't survive session rotation),
    not `/scratch` (project retention policies). `$HOME` is
    NFS-backed and stable.

**5-property ✅ check**: this design specifies
(a) tmux-session-from-`.bash_profile`, (b) `bash -l -c` + Lmod
`Python/3.11.3` wrapper, (c) docker-absent guard, (d)
`$HOME`-backed breadcrumbs, (e) 30 s cadence via in-loop `sleep`.

## 9. Nice / IO / resource discipline

The daemon must never be the thing that causes the problem it's
watching for.

- `Nice=10` on all systemd units; equivalent via `renice` on the
  MBA launchd plist startup.
- `IOSchedulingClass=best-effort IOSchedulingPriority=6` on Linux.
- No `find /`, no `du ~`, no unbounded walks (per
  `hpc-etiquette.md`). All filesystem sampling is scoped to
  pre-enumerated paths.
- `docker stats --no-stream --format json`, never streaming.
- `systemctl --user list-units --state=failed` only, never
  `systemctl --all`.
- Memory budget: < 50 MB RSS per probe invocation. Exit if
  exceeded.
- Wall-clock budget: < 5 s per tick. If exceeded, log the
  slow-tick event and exit; the next tick fires 30 s later.
- No hub WebSocket session. No outbound network calls from the
  daemon. Pure local sampling.
- JSONL scraping budget (Phase 1 specific): never read more than
  10 MB per probe tick, and never walk workspace directories the
  agent does not own (`~/.claude/projects/<own_workspace>/*.jsonl`
  only).

## 10. Cross-host coverage

A single daemon on one host only observes that host. The
fleet-wide coverage matrix is the union of per-host daemons:

- **MBA**: own docker, own tmux, own systemd user units, own
  claude_procs, own JSONL usage records.
- **NAS**: hub + stable + dev + cloudflared docker containers,
  NAS systemd user units (including existing `fleet-watch`,
  `audit-closes`, `fleet-prompt-actuator`, `autossh-tunnel-1230`),
  SLURM queue, own JSONL usage.
- **Spartan**: `head-spartan` + `mamba-*-spartan` tmux, Lmod
  state, SLURM scraper output, own JSONL usage. Never touches
  `/data/gpfs/projects/*`.
- **WSL**: own systemd user units, own claude_procs, own JSONL
  usage, WSL DrvFs mount health.

**Cross-host reads** for the worker layer: read local NDJSON +
breadcrumbs directly; read peer-host NDJSON via SSH or via the
`/api/fleet/quota/` + future `/api/fleet/health/` aggregation
endpoint.

## Continued in

- [`53_fleet-health-daemon-design-deployment-ops.md`](53_fleet-health-daemon-design-deployment-ops.md)
