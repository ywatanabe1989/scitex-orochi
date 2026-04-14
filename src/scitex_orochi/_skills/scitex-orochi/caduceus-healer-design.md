---
name: orochi-caduceus-healer-design
description: DRAFT — design doc for the caduceus agent healer, todo#146 (ticket title uses "caduceus"; see §0 for the medical-symbol naming note). Reconciles the original 2026-04-09 vision with today's 2-layer role taxonomy — caduceus is not one agent, it is a daemon-layer deterministic prober ("caduceus-prober") + worker-layer LLM-driven healer ("mamba-healer-<host>", existing). Multi-signal observation (systemd + docker stats + MCP process dedup + cpu.pressure + terminal snapshot). 30s cadence. Breadcrumb-driven escalation, not continuous chatter.
---

# Caduceus — Agent Healer Design

> **STATUS: DRAFT** design doc for `ywatanabe1989/todo#146`. Posted to
> #agent for fleet review before PR. Not canonical until ywatanabe GO +
> merge into the `_skills/scitex-orochi/` tree.

## 0. Naming note

The canonical name in this doc is **`caduceus`**, matching the
issue title `ywatanabe1989/todo#146 feat: caduceus — agent healer`.
This is a deliberate operational choice (head-mba msg#11747), not
a claim of medical-symbol accuracy.

Medically and historically, the two symbols are distinct:

- The **Asclepius rod** is the Greek god-of-medicine's staff with
  **one** serpent coiled around it. It is the universal medical
  symbol used by the WHO, the BMA, the AMA, and most health
  authorities worldwide.
- The **caduceus** is the staff of Hermes (messenger, commerce,
  thieves), with **two** serpents and usually wings. Its adoption
  as a medical symbol was a historical accident in the US military
  medical corps.

The `todo#146` issue body was internally consistent around the
single-serpent medical symbol, and the original author-intent was
the Asclepius rod. The title, however, locked in "caduceus" early,
and earlier fleet discussion (msg#11692 / msg#11698) has already
referred to the healer as "caduceus" in multiple places. Rather
than rename the ticket at this stage and fragment the audit trail,
we keep `caduceus` as the canonical agent name throughout this
design doc, commit messages, filenames, class names, and breadcrumb
paths. The medically-correct name is Asclepius rod; we note it here
and move on.

If a future rename is needed, it is a global find-replace against
the daemon name + log paths + unit names + breadcrumb filenames.
The architecture does not depend on the name.

## 1. TL;DR

Caduceus is **not** a single Claude-backed agent. It is a **2-layer
stack** that follows the ratified `fleet-role-taxonomy.md`:

1. **`caduceus-prober`** — `role=daemon`, `function=[prober,
   metrics-collector]`. Pure bash/python, no Claude session, no quota
   consumption. Runs every 30 s on every agent host via the host's
   native scheduler (systemd user timer on Linux, launchd on MBA,
   user-space bash loop on Spartan since no sudo). Collects a fixed
   set of multi-signal health metrics and writes host-local NDJSON.
   When a threshold transition fires, it drops a breadcrumb touch-file
   for the worker layer to pick up.
2. **`mamba-healer-<host>`** — `role=worker`, `function=[prober,
   healer]`. Already exists today (running as `mamba-healer-mba` and
   `mamba-healer-nas`). Extended contract: continues to own the
   LLM-driven DM-ping probe and the LLM-judgment recovery actions, but
   now **also reads the caduceus-prober NDJSON stream and breadcrumb
   touch-files as primary input**, not as a secondary signal. The
   worker's LLM time is spent on interpretation and recovery, not on
   continuous polling.

The split matches today's defining axis (msg#11428, ratified in PR
#134): *"Does the loop require LLM judgment to make its next
decision?"* Continuous threshold sampling does not → daemon.
Interpreting the resulting signals + picking the right recovery →
worker. This is exactly the split pattern `skill-sync-daemon` /
`mamba-skill-manager-mba` uses, generalised to healing.

## 2. Origin and what changed since the issue was filed

The issue body was written 2026-04-09. Since then the fleet has
evolved substantially:

- **Multiple agent-layer healers already exist** — `mamba-healer-mba`
  and `mamba-healer-nas` are running today. The original issue
  envisioned a single dedicated healer; the reality is the healer
  layer is already multi-host. The caduceus design is a
  *formalisation and split* of the existing healers, not a
  green-field rewrite.
- **The 2-layer role taxonomy landed today** (PR #134 against
  `feat/slurm-resource-scraper-contract`). `prober` is explicitly a
  function tag that can be attached to either a daemon or a worker,
  not its own role. Caduceus naturally inherits this: its daemon half
  is `role=daemon function=[prober]`, its worker half is
  `role=worker function=[prober, healer]`.
- **Slow-failure resource degradation is a documented gap.** Explorer
  analysis of `todo#142` + `todo#181` (msg#11713) and the NAS probe
  data collected by `mamba-healer-nas` (90+ min NDJSON, msg#11709)
  together show that the existing worker healers cannot see
  resource-layer degradation: docker containers bursting to 769%
  CPU, cpu.pressure spikes at 10–18% of samples, duplicate MCP
  processes leading to 3–4× notification storms. These are invisible
  to a DM-ping probe but directly drive the stuck-state symptoms the
  issue was filed to address.
- **Host diversity is now a hard constraint.** NAS is running
  scitex-cloud visitor SLURM, Spartan bans sudo (msg#11632), MBA is
  empirically the most stable. "Run one healer on NAS" is no longer
  sufficient. Caduceus-prober must be portable to every host type
  with host-native scheduling.

So the design below is not "build a new healer from scratch" — it is
"formalise the existing healer layer, split the deterministic half
into a quota-zero daemon, and give the worker half the multi-signal
input it currently lacks."

## 3. Architecture

```
╔═══════════════════════════════════════════════════════════════╗
║  AGENT LAYER (LLM-backed, quota-consuming)                    ║
║                                                               ║
║    mamba-healer-mba   (existing, MBA)                         ║
║    mamba-healer-nas   (existing, NAS)                         ║
║    mamba-healer-spartan  (planned once NeuroVista lane calms) ║
║    mamba-healer-ywata-note-win  (planned)                     ║
║                                                               ║
║    role=worker  function=[prober, healer]                     ║
║                                                               ║
║    Reads caduceus-prober NDJSON + breadcrumbs from its own   ║
║    host (and, via SSH / hub read-only endpoints, from other   ║
║    hosts in the cross-host mesh). Runs LLM-driven DM pings    ║
║    against suspicious agents. Chooses and executes recovery   ║
║    actions: SIGINT, /compact, screen -X stuff, systemd        ║
║    restart, process kill for dedup. Escalates to #escalation  ║
║    when automated recovery fails or recurs.                   ║
╠═══════════════════════════════════════════════════════════════╣
║  PROCESS LAYER (no LLM, quota-zero)                           ║
║                                                               ║
║    caduceus-prober                                           ║
║    role=daemon  function=[prober, metrics-collector]          ║
║    host: one instance per host (MBA/NAS/Spartan/WSL)          ║
║    cadence: 30 s                                              ║
║    runtime: launchd (MBA) / systemd --user (NAS/WSL) /        ║
║             user-space bash loop in tmux (Spartan, no sudo)   ║
║                                                               ║
║    Samples a fixed multi-signal vector every 30 s, writes     ║
║    NDJSON to host-local log, maintains transition state in    ║
║    memory, drops a breadcrumb touch-file when any threshold   ║
║    transitions. Never holds a hub WebSocket session. Never    ║
║    calls an LLM. Never decides recovery.                      ║
╚═══════════════════════════════════════════════════════════════╝
```

## 4. Responsibility mapping (from the issue body)

The original issue's four responsibilities map onto the 2-layer split
as follows:

| Issue §                            | Daemon (caduceus-prober)                                               | Worker (mamba-healer-*)                                                                                       |
|------------------------------------|-------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| **§1 Health monitoring (30s)**     | Samples terminal snapshot, systemd unit state, docker stats, cpu.pressure, MCP process dedup, loadavg. Writes NDJSON. | Reads NDJSON + runs LLM-judgment DM pings on suspicious agents. Decides "is this really stuck or legitimately busy". |
| **§2 Stuck state detection**       | Regex-classifies terminal snapshots against a fixed pattern catalog (`pane-state-patterns.md`). Drops breadcrumb on state transition. | Reads breadcrumbs. For ambiguous state transitions, LLM-inspects the snapshot to decide between "stuck" and "legitimately in a long-running command". |
| **§3 Recovery actions**            | **None.** Daemon never sends keystrokes or restarts processes. All action is worker-owned. | Chooses and executes the recovery: SIGINT, `/compact`, `screen -X stuff "1\r"` for pre-approved prompts, systemd unit restart, `kill` for duplicate MCP. |
| **§4 Escalation**                  | Writes escalation touch-file `~/.scitex/orochi/logs/caduceus-prober.escalate` with the failing signal and timestamp. | Reads the escalate touch-file, opens a `#escalation` post with LLM-summarised context, flags for human attention if recurring, maintains the audit log. |

The daemon never acts on its observations. This is deliberate:
keystroke-injecting or process-killing requires judgment that can
legitimately be wrong (a `/` prompt that looks like permission-stuck
might actually be a legitimate in-progress filter), and judgment is
the worker layer's job. The worker-layer healer retains full authority
over recovery actions; the daemon just gives it better eyes.

## 5. Signals the daemon collects

Every 30 s the daemon emits **one** NDJSON record containing a fixed
set of host-local health metrics. Field names and units are fixed;
new signals are added by appending new fields, never by reshaping
existing ones. The aim is that two probes on different hosts can be
merged on `ts` without schema reconciliation.

**Target schema** (field order fixed, unknown values rendered as
`null`, not omitted):

```
ts                       ISO-8601 UTC, second precision
host                     short hostname (mba / nas / spartan / ywata-note-win)
probe_version            semver of caduceus-prober itself, for log-replay
load_1  load_5  load_15  /proc/loadavg columns 1-3
ncpu                     int, nproc output
cpu_pressure_some_avg10  /proc/pressure/cpu "some avg10" value
mem_total_kb             /proc/meminfo MemTotal
mem_avail_kb             /proc/meminfo MemAvailable
slurm_running            squeue -h -t R | wc -l  (NAS/Spartan/WSL only; 0 elsewhere)
slurm_pending            squeue -h -t PD | wc -l
slurm_cpu_used           sum of RES cpus over running jobs
failed_user_units        systemctl --user list-units --state=failed | grep -c .service
failed_sys_units         systemctl list-units --state=failed | grep -c .service  (read-only, no sudo)
docker_count             int, running container count (= len(docker_containers))
docker_top_cpu_pct       float, max cpu_pct across all containers this tick
docker_total_cpu_pct     float, sum of cpu_pct across all containers this tick
docker_containers        array of {name: str, cpu_pct: float, mem_usage: str, mem_pct: float}
                         **All percentage fields are floats**, emitted with the `%` suffix
                         stripped at the producer side for consistency with the top-level
                         `docker_top_cpu_pct` / `docker_total_cpu_pct` (head-mba schema decision
                         msg#11748). The producer strips `%` via a `docker stats --format`
                         template that wraps `{{.CPUPerc}}` / `{{.MemPerc}}` in a small
                         post-process step (shell `tr -d '%'` or jq `| tonumber`). Consumers
                         therefore never need to know about the `%` glyph.
                         `mem_usage` stays as a string pair like `"9.356GiB / 62.54GiB"`
                         (used / total) — splitting it at the producer would force a unit
                         choice the downstream doesn't own, so the composite string is
                         preserved and consumers split on " / " as needed.
                         **Schema bump timing**: the currently-running NAS probe continues
                         emitting the existing string form (msg#11730 / #11746) until the
                         `probe_version` gets bumped to v2, at which point the format flips
                         to this spec in lockstep with the caduceus-prober rollout (§14 step
                         1). Pre-v2 NDJSON stays parseable via `float(x.rstrip("%"))` for
                         log replay.
cf_bastion_active        bool, cloudflared tunnel active
cf_pid                   int or null
mcp_duplicates           {<agent-name>: [<pid>, <pid>, ...]}  — only agents with >1 mcp_channel procs
claude_procs             {<agent-name>: int}  — count of claude code processes per agent session
tmux_sessions            int, tmux ls count
pane_states              {<session>: <pane-state-regex-class>}  — classified via pane-state-patterns.md
```

The `docker` / `mcp_duplicates` / `claude_procs` / `pane_states`
fields are nested objects rather than top-level scalars because their
cardinality is fleet-state-dependent; flattening them would break the
"field order fixed" property on the first container rename.

Align with the 90+ min NDJSON schema `mamba-healer-nas` is already
writing (msg#11567 / msg#11709). Reuse their existing field names
verbatim where they overlap; only add new ones. The post-PR follow-up
commit flips their probe to the shared schema, not the other way
around.

## 6. Threshold transitions (breadcrumb-triggering events)

The daemon is silent-otherwise: no output other than NDJSON unless a
**threshold transition** fires. A transition is a state change from
"OK" to "concerning" for one of the watched signals, sustained over
at least N consecutive samples (default N=3 for 90 s settle time,
overridable per signal). Only the *transition* drops a breadcrumb,
not every subsequent sample while the signal remains concerning.

Canonical transition catalog (extendable):

| Signal                              | Concerning when                         | N samples | Breadcrumb file                                          |
|-------------------------------------|-----------------------------------------|-----------|----------------------------------------------------------|
| `docker_top_cpu_pct`                | > 200% sustained (any container)        | 3         | `~/.scitex/orochi/logs/caduceus.docker-cpu-spike.<container>` (name from the offending row in `docker_containers`) |
| `docker_top_cpu_pct` (smoking-gun)  | > 100% on a single-process container (e.g. django) | 1 | Immediate breadcrumb. First real sample after probe extension showed `scitex-cloud-prod-django-1` at 100.95% (msg#11730) — confirmed slow-failure invisible to DM-ping healer |
| cpu.pressure some avg10             | > 15.0                                  | 3         | `~/.scitex/orochi/logs/caduceus.cpu-pressure`           |
| failed_user_units                   | > 0 (any fleet-relevant unit)           | 1         | `~/.scitex/orochi/logs/caduceus.failed-unit.<unit>`     |
| mcp_duplicates count                | > 1 for any agent                       | 1         | `~/.scitex/orochi/logs/caduceus.mcp-dup.<agent>`        |
| pane_state                          | matches `permission_prompt` or `stuck`  | 3         | `~/.scitex/orochi/logs/caduceus.pane-stuck.<session>`   |
| mem_avail_kb                        | < 10% of mem_total_kb                   | 3         | `~/.scitex/orochi/logs/caduceus.mem-low`                |
| load_1 / ncpu                       | > 2.0                                   | 6 (3 min) | `~/.scitex/orochi/logs/caduceus.loadavg-high`           |
| claude_procs count for one agent    | > 1 (sessions-within-session)           | 1         | `~/.scitex/orochi/logs/caduceus.claude-dup.<agent>`     |

Breadcrumb files contain one line: the triggering signal value + the
ISO-8601 timestamp + the last-3-samples JSON. They are **not** deleted
by the daemon; the worker-layer healer deletes them after handling
(so re-transitions after the worker clears state do re-fire). The
worker also writes a sibling `<breadcrumb>.handled` file when it
completes recovery for audit purposes.

## 7. Recovery action catalog (worker side)

The worker-layer healer owns all recovery. The daemon never injects
keystrokes or kills processes. Canonical recovery actions:

| Trigger                                        | Worker action                                                                         |
|------------------------------------------------|----------------------------------------------------------------------------------------|
| `caduceus.pane-stuck.<session>` (permission)  | LLM inspect snapshot → if matches pre-approved allowlist, `tmux send-keys -t <session> "1" Enter`; otherwise LLM summarise + post to `#agent` for human call |
| `caduceus.pane-stuck.<session>` (y/N)         | Same pattern; allowlist for "yes on safe prompts" is stricter, default deny           |
| `caduceus.pane-stuck.<session>` (long silence) | LLM inspect last N lines; if "legitimately long command", leave alone; if "dead prompt", SIGINT + short probe DM |
| `caduceus.docker-cpu-spike.<container>`       | Open `todo` issue tagged `docker-cpu-breach` with last 3 samples; if recurring for the same container > 3 times in 1 h, post to `#escalation` |
| `caduceus.failed-unit.<unit>`                 | LLM read `journalctl --user -u <unit> -xe` → classify as env-issue / transient / root-cause-needed; attempt `systemctl --user reset-failed && restart` once for env/transient, otherwise escalate |
| `caduceus.mcp-dup.<agent>`                    | LLM inspect both PIDs' process trees → kill the older one, verify agent still responds, record in audit log |
| `caduceus.claude-dup.<agent>`                 | **Do not auto-kill.** Duplicate Claude sessions are often legitimate concurrent conversations (see head-spartan msg#11708). Post to `#agent` for coordinator-level triage instead. |
| `caduceus.cpu-pressure` / `loadavg-high`      | LLM correlate with `docker` field → likely a container; if so, defer to `docker-cpu-spike` handler. Otherwise escalate (system-layer issue, not fleet-layer). |
| `caduceus.mem-low`                            | LLM inspect container memory + top processes; if a specific agent is leaking, restart it; otherwise escalate |

**Critical anti-pattern**: automatic kill of duplicate Claude
processes (the `claude_procs > 1` case). Today's head-spartan incident
(msg#11708) established that concurrent Claude sessions under the
same `SCITEX_OROCHI_AGENT` identity can be legitimate parallel
conversations, and auto-killing the "older" one would race-corrupt
shared artifacts. The worker must escalate, not act.

## 8. Host-specific deployment

The same daemon body runs everywhere, but the scheduler wrapper
differs per host. All wrappers call the same
`~/.scitex/orochi/bin/caduceus-prober` entrypoint and write to the
same canonical log path `~/.scitex/orochi/logs/caduceus-prober.ndjson`.

| Host                | Scheduler                                                                          | Notes                                                                                               |
|---------------------|------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| **MBA**             | `launchd` — `~/Library/LaunchAgents/com.scitex.orochi.caduceus-prober.plist`      | `StartInterval=30`, `RunAtLoad=true`, `KeepAlive=false`. Primary host for first pilot.             |
| **NAS**             | `systemd --user` — `~/.config/systemd/user/caduceus-prober.timer` + `.service`    | `OnUnitActiveSec=30s`, `Nice=10`, `IOSchedulingClass=best-effort`, `IOSchedulingPriority=6`. I/O-light, CPU-cheap, fine under the daemon-host policy. |
| **Spartan**         | `.bash_profile` wrapper + `tmux` loop (no sudo, no systemd --user writes allowed per site policy) | Runs inside the existing `head-spartan` tmux session as a background process. Cadence enforced by `sleep 30` in the loop. Entrypoint uses the Lmod `Python/3.11.3` workaround from `agent-autostart.md` so `~/.venv` is usable. |
| **WSL (ywata-note-win)** | `systemd --user` — same unit as NAS                                            | `SCITEX_ON_WSL=1` flag exposes WSL-specific metrics (interop, DrvFs mounts).                        |

Per-host cadence tuning is allowed — e.g., Spartan might stretch to
60 s if the login-node CPU budget is tight — but the schema and
threshold catalog stay identical.

### Spartan-specific constraint matrix

Spartan is not a generic Linux host from the daemon's point of
view, and getting the deployment wrong loses the Spartan signal
entirely. The constraint list below is from head-spartan msg#11753
and is authoritative until the next UniMelb Research Computing
policy change. Any caduceus-prober implementation that ships must
satisfy all of these; a failure on Spartan should never be a
"worked on my other hosts so we'll figure it out later" item.

1. **No systemd user units, no `loginctl enable-linger`.** Login1
   enforces `cgroup nproc=1`; `systemctl --user enable` fails
   outright. This is set by UniMelb Research Computing, not
   bypassable, not a bug.
2. **No sudo, ever** — including "harmless" probes like
   `sudo -n true`. head-spartan's bash `sudo()` guardrail
   (commit `3a9ffaf7` in `999_unimelb_spartan.src`) refuses every
   sudo invocation at the shell level and points at user-space
   alternatives. Any caduceus-prober probe command that reaches
   for sudo is a defect on Spartan.
3. **No user crontab** on login1. The `cgroup nproc=1` policy
   propagates to `crontab -e`. Do not rely on cron as a fallback
   scheduler; it is blocked.
4. **No launchd / no plist** — macOS-only, irrelevant on Spartan.
5. **What works: a `tmux` session started from `.bash_profile`
   on SSH login, running a `while true; sleep 30; ...; done`
   probe loop inside.** This is the pattern already in
   `agent-autostart.md` (PR #141 added the `Python/3.11.3`
   Lmod wrapper). The loop body writes NDJSON and breadcrumb
   touch-files to `$HOME/.scitex/orochi/probes/caduceus/` with no
   privileged access.
6. **Lmod env init is mandatory for any Python process on
   Spartan**, because `~/.venv/lib/libpython3.11.so.1.0` is
   missing until `module load GCCcore/11.3.0 Python/3.11.3` runs.
   Start the probe loop under `bash -l -c 'module load
   GCCcore/11.3.0 Python/3.11.3 && exec <cmd>'`. If the prober
   is pure bash + `docker stats` / `systemctl --user` /
   `tmux list-panes`, Lmod is optional; if it shells out to
   Python for NDJSON serialization or schema validation, Lmod is
   non-negotiable.
7. **Spartan has no docker.** Any `docker stats` / `docker ps`
   invocation on Spartan must be **guarded by `command -v
   docker`** and must return `docker_containers: []`,
   `docker_count: 0`, `docker_top_cpu_pct: 0.0`,
   `docker_total_cpu_pct: 0.0` on hosts where docker is absent.
   An unguarded `docker stats` dies at first sample with
   `docker: command not found`. Same pattern for
   `systemctl --user`: on Spartan there are zero user units by
   policy, so the probe must return `failed_user_units: 0` and
   not error.
8. **cpu.pressure is readable on Spartan login1.**
   `cat /proc/pressure/cpu` works for non-root users. The PSI
   signal from mamba-healer-nas's probe transfers cleanly.
   `loadavg` likewise.
9. **MCP process dedup is the same command on Spartan** —
   `ps -eo pid,cmd | grep -E '(claude|mcp_channel)' | grep -v
   grep`. No host-specific adaptation is needed; the tmux
   session name is just `head-spartan` plus the `.bash_profile`
   bootstrap.
10. **Breadcrumb directory**: use
    `$HOME/.scitex/orochi/probes/caduceus/` — **not** `/tmp`
    (Spartan `/tmp` is node-local and doesn't survive session
    rotation) and **not** `/scratch` (has project-scoped
    retention policies). `$HOME` is NFS-backed and stable.

**Satisfies-the-matrix check** (the 5 properties head-spartan
flagged as necessary + sufficient): this design specifies
(a) tmux-session-from-`.bash_profile`, (b) `bash -l -c` + Lmod
`Python/3.11.3` wrapper, (c) docker-absent guard, (d)
`$HOME/.scitex/orochi/probes/caduceus/` for breadcrumbs, (e) 30 s
cadence via in-loop `sleep`. ✅.

### Docker-absent guard (all hosts, not just Spartan)

Because Spartan has no docker and WSL's docker availability is
uncertain, the probe treats `command -v docker` as a per-tick
feature check, not a compile-time assumption. On hosts without
docker:

- `docker_count = 0`
- `docker_top_cpu_pct = 0.0`
- `docker_total_cpu_pct = 0.0`
- `docker_containers = []`

The fields are **always present** in the NDJSON record so the
schema stays stable and merge-on-`ts` continues to work across
heterogeneous hosts. The host is not dropped from the fleet
aggregation just because it has no docker; it simply contributes
zero to docker-layer signals.

## 9. Nice / IO / resource discipline

The daemon must never be the thing that causes the problem it's
watching for. Hard rules:

- `Nice=10` on all systemd units, equivalent via `renice` on the MBA
  launchd plist startup.
- `IOSchedulingClass=best-effort IOSchedulingPriority=6` on Linux.
- No `find /`, no `du ~`, no unbounded walks (per `hpc-etiquette.md`).
  All filesystem sampling is scoped to pre-enumerated paths.
- `docker stats --no-stream --format json` (non-streaming).
- `systemctl --user list-units --state=failed` (no sudo), never
  `systemctl --all` (output size grows unboundedly).
- Memory budget: < 50 MB RSS per probe invocation. Exit if exceeded.
- Wall-clock budget: < 5 s per tick. If exceeded, log the slow-tick
  event (itself a useful health signal) and exit; the next tick fires
  30 s later regardless.
- No hub WebSocket session. No outbound network. Pure local sampling.

## 10. Cross-host coverage

A single daemon on one host only observes that host. The fleet-wide
coverage matrix is the union of per-host daemons:

- **MBA caduceus-prober** → observes MBA docker containers, MBA
  tmux sessions (including `head-mba`, `mamba-*-mba`), MBA systemd
  user units, MBA claude_procs.
- **NAS caduceus-prober** → observes NAS docker containers (hub,
  stable, dev, cloudflared), NAS systemd user units including the
  existing `fleet-watch.timer` / `audit-closes.timer` /
  `fleet-prompt-actuator.timer` / `autossh-tunnel-1230.service`,
  NAS SLURM queue.
- **Spartan caduceus-prober** → observes `head-spartan` + any
  `mamba-*-spartan` tmux, Lmod state, SLURM scraper output, never
  touches `/data/gpfs/projects/*`.
- **WSL caduceus-prober** → observes WSL systemd user units,
  WSL claude_procs, WSL DrvFs mount health.

**Cross-host reads**: the worker-layer healer on MBA reads the MBA
probe locally, and reads the other three probes via read-only SSH
(`ssh <host> cat ~/.scitex/orochi/logs/caduceus-prober.ndjson | tail
-10`) or via a future hub REST endpoint that aggregates them. The
*daemons themselves* stay host-local.

## 11. Relation to existing fleet state

- **`mamba-healer-mba` / `mamba-healer-nas`** — these existing workers
  get the extended contract. They are not replaced. Their boot code
  adds "read caduceus-prober NDJSON + breadcrumbs" to their input
  set. Everything else (DM ping probe, LLM recovery, escalation
  discipline) stays the same.
- **`mamba-healer-nas` 90 min NDJSON probe** (msg#11567, #11709) —
  this IS already a prototype of caduceus-prober. Promoting it to
  the canonical daemon requires: (a) rename + relocate log path,
  (b) add the `docker` / `mcp_duplicates` / `claude_procs` /
  `pane_states` fields, (c) add the threshold transition catalog
  and breadcrumb emission. The existing field set stays.
- **`fleet-prompt-actuator.timer`** — existing NAS daemon that
  unblocks permission prompts. Under the new taxonomy this is
  already `role=daemon, function=[prompt-actuator]`. Caduceus
  does not replace it; rather, caduceus-prober's
  `pane-stuck.<session>` breadcrumb is an *input* to the worker, and
  the worker can choose between (a) deferring to the existing
  prompt-actuator (already non-LLM, fast) for allowlisted prompts
  or (b) LLM-inspecting ambiguous cases. Prompt-actuator stays;
  caduceus routes around it for non-trivial cases.
- **`random-nonce-ping-protocol.md`** — the existing 60 s nonce
  liveness check. Caduceus-prober's local sampling does not
  replace this; the nonce ping is a *cross-agent* liveness signal
  that catches "agent looks alive locally but has actually silently
  died". Keep both. They observe different failure modes.

## 12. Anti-patterns

1. **"caduceus is one agent"** — no. It is a 2-layer stack. Talking
   about "the caduceus agent" is the first confusion to prevent.
2. **"daemon injects keystrokes"** — never. Keystroke injection
   requires judgment (allowlist membership, context), and judgment
   is the worker's job.
3. **"worker polls instead of reading breadcrumbs"** — defeats the
   quota relief. The worker should be idle between breadcrumb events.
4. **"continuous threshold chatter to `#agent`"** — daemons are
   silent-otherwise. Only the worker posts, and only when it has
   something actionable.
5. **"one healer on NAS covers everything"** — violates host
   diversity. Each host needs its own daemon instance.
6. **"reshape NDJSON schema when adding a signal"** — append only,
   never reshape. Log-replay tooling depends on field stability.
7. **"auto-kill duplicate Claude sessions"** — legitimate concurrent
   conversations exist (head-spartan msg#11708). Escalate, do not
   act.
8. **"daemon does unbounded `find`"** — violates `hpc-etiquette.md`
   and risks being the thing it's watching for.

## 13. Open questions / future work

1. **Schema versioning.** The `probe_version` field is a hook for
   this; concrete policy (SemVer major = breaking, minor =
   append-only field, patch = bug fix) is TBD.
2. **Hub aggregation endpoint.** Today the worker reads the other
   hosts' NDJSON via SSH. A hub REST endpoint that aggregates all
   four host streams into one `GET /api/caduceus/` feed would be
   cleaner, but it's a separate implementation task for the dashboard
   team (head-ywata-note-win lane under `scitex-orochi#155`).
3. **Dashboard integration.** Once the hub endpoint exists, the
   `Agents` tab can render a small "caduceus score" per host (0–100,
   aggregated from the threshold signals). Out of scope for this
   doc; tracked as follow-up under `scitex-orochi#133` observability
   epic.
4. **Recovery action audit log.** The issue body asks for one; the
   design above writes `<breadcrumb>.handled` files per recovery but
   does not aggregate them into a per-day audit. A small daemon
   (`caduceus-audit-rollup`, `role=daemon function=[auditor]`) can
   roll them up weekly; deferred until the base caduceus-prober is
   in production.
5. **Auto-`/compact` on context pressure.** The issue body mentions
   this. Feasible (`screen -X stuff $'\x1b:compact\r'` pattern), but
   it is inherently disruptive (loses recent context), so the
   worker should only trigger it at very high confidence and with
   an undo-plan. Parked for a follow-up design doc.

## 14. Implementation order (proposed, for a separate PR)

1. Promote `mamba-healer-nas`'s existing probe script to
   `caduceus-prober` under the canonical path + schema (rename +
   schema alignment + threshold catalog). Runs on NAS first.
2. Port to MBA via launchd (same entrypoint, plist wrapper). Runs
   alongside NAS, cross-merged on `ts` for validation.
3. Port to WSL (systemd --user, same unit as NAS).
4. Port to Spartan (tmux loop wrapper, Lmod `Python/3.11.3`
   initialization per `agent-autostart.md`).
5. Extend `mamba-healer-mba` and `mamba-healer-nas` worker contracts
   to read the NDJSON + breadcrumb files as primary input.
6. Add the hub aggregation endpoint (scitex-orochi#155 lane).
7. Retire the per-worker ad-hoc probe scripts in favor of the
   canonical caduceus-prober entrypoint.

## 15. Related skills / issues

- `fleet-role-taxonomy.md` — the 2-layer model this design obeys.
- `skill-manager-architecture.md` — the first pilot of the same
  daemon/worker split pattern; caduceus is the third pilot after
  `skill-sync-daemon` and `todo-sweep-daemon`.
- `slurm-resource-scraper-contract.md` — the external-tool-compat
  design principle for metrics-collector daemons; caduceus-prober
  follows the same principle (native OS CLI output, no bespoke JSON
  schema reshuffle).
- `pane-state-patterns.md` — the canonical regex catalog caduceus
  uses to classify tmux pane state.
- `active-probe-protocol.md` — the agent-layer DM-ping probe the
  worker-layer healer continues to own.
- `random-nonce-ping-protocol.md` — the cross-agent 60 s liveness
  check that stays in place orthogonal to caduceus.
- `fleet-prompt-actuator.timer` — existing NAS daemon whose inputs
  become a subset of caduceus's `pane_states` signal.
- `todo#141` — terminal snapshot infrastructure, a dependency.
- `todo#142` — skip permission prompts, reduces the workload the
  worker sees via `pane-stuck` breadcrumbs.
- `todo#181` — MCP duplicate notifications, solved by the
  `mcp_duplicates` signal + `mcp-dup.<agent>` breadcrumb.
- `todo#95` — NeuroVista gPAC manuscript lane, unrelated but
  important context for why the fleet can't afford Claude-session
  healer loops during the paper crunch.

---

**Ground-truth sources consulted during drafting** (msg numbers are
approximate per the origin-section convention from
`fleet-role-taxonomy.md`):

- mamba-explorer-mba root-cause analysis — msg#11713, msg#11681
- mamba-healer-nas NAS probe schema + findings — msg#11536, #11540,
  #11567, #11709
- head-mba 4+1 design principles — msg#11722
- head-spartan concurrent-Claude incident — msg#11708
- explorer Docker CPU recommendations — msg#11633
- explorer SLURM cgroup research — msg#11570, #11576

Draft ends here. Posting to #agent for review before PR.
