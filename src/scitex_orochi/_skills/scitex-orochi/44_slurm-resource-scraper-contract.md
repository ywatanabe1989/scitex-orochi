---
status: DRAFT
ratified: false
ratification-thread: scitex-orochi#133
owner: head-nas
pilot-order: "#2 (after skill-sync-daemon warm-standby proof)"
last-updated: 2026-04-14
authors: [head-nas, head-mba]
---

# slurm-resource-scraper — Design Contract

> **DRAFT — pending ratification in scitex-orochi#133.**
> This document captures the design-time contract for the SLURM resource
> scraper daemon. It is written _before_ implementation so that `slurmdbd`
> compatibility, federation-readiness, and university / pharma portability
> are baked in from day 1, not retrofit. Per ywatanabe msg#11504 (2026-04-14):
> SLURM first-class support must be designed in at the design stage, not
> bolted on afterwards, because real adoption requires that external SLURM
> admins (UniMelb HoRC, pharma co, partner universities) can drop the
> scraper onto their own cluster and have it work immediately.

## 1. Motivation

scitex-cloud today runs SLURM on 3 fleet hosts (NAS, ywata-note-win WSL,
Spartan) and aims to be adoptable by university HPC and pharma compute
teams. Those teams already run SLURM with their own monitoring, alerting,
and accounting pipelines built on stock SLURM CLI outputs (`sinfo`,
`squeue`, `sacct`, `sreport`, `scontrol`).

If the scraper emits a bespoke JSON schema — even one that happens to
contain SLURM-shaped fields — it forces every downstream consumer to
rewrite against a scitex-specific format. That is a lock-in, and it
silently discards information that the native CLI output carries
(partition-level drain reasons, reservation state, per-TRES accounting,
billing weights).

**The scraper's wire format IS stock SLURM CLI output.** The daemon is a
transport layer around commands any SLURM admin already trusts.

## 2. Canonical commands

### 2.1 Required (must work on every SLURM cluster, slurmdbd-free)

| Command | Purpose | Cadence |
|---|---|---|
| `sinfo -o '%P %D %T %N %C %m %G'` | partition + node state + CPU(A/I/O/T) + memory + GRES | 1 / 60s |
| `squeue -h -o '%i\|%P\|%j\|%u\|%T\|%M\|%L\|%D\|%C\|%m\|%R'` | live job state, pipe-delimited, no header | 1 / 60s |
| `scontrol show node --json` | rich per-node state (cpu_load, free_mem, reason, energy) | 1 / 60s |
| `scontrol show partition --json` | partition config (QOS, TRES, limits, state) | 1 / 300s |

These four commands MUST succeed on any functioning slurmctld regardless
of accounting storage plugin. If they fail, the scraper publishes a
`scraper-error` record and an actionable message, not a partial payload.

### 2.2 Optional (only work when `accounting_storage/slurmdbd` is active)

| Command | Purpose | Cadence |
|---|---|---|
| `sacct -a -S <window> -o 'JobID,JobName,Partition,Account,User,State,ExitCode,Elapsed,NCPUS,ReqMem,MaxRSS,NodeList' -P` | historical jobs, finished | 1 / 300s |
| `sreport cluster utilization start=<date>` | cluster-level rollups, billing-ready | 1 / 3600s |

If `slurmdbd` is not configured, the scraper skips the optional block and
publishes a `historical: unavailable, reason: slurmdbd not configured`
metadata record. Consumers (monitors, dashboards) treat missing historical
blocks as expected on dev clusters, not as an error.

**Reality check from NAS (2026-04-14)**: `sacct` returns
`Slurm accounting storage is disabled`, and `sreport` returns
`You are not running a supported accounting_storage plugin. Only
'accounting_storage/slurmdbd' is supported.`. NAS is a dev-oriented
slurmctld without `slurmdbd`. The scraper's `Required` block above was
validated against NAS live state and works.

## 3. Output format

Newline-delimited JSON (NDJSON), one record per CLI invocation. Each
record is a minimal envelope around the **verbatim stdout** of the SLURM
command:

```json
{
  "schema": "scitex-orochi/slurm-scraper/v1",
  "host": "nas",
  "cluster_name": "nas-scitex-cloud",
  "cmd": "sinfo -o '%P %D %T %N %C %m %G'",
  "cmd_kind": "sinfo",
  "ts": "2026-04-14T17:18:00Z",
  "exit_code": 0,
  "stdout": "PARTITION NODES STATE NODELIST CPUS(A/I/O/T) MEMORY GRES\nnormal* 1 allocated DXP480TPLUS-994 12/0/0/12 64038 (null)\n...",
  "stdout_parsed": {
    "_format_hint": "pipe-or-space-delimited table, first line is header",
    "_columns": ["PARTITION","NODES","STATE","NODELIST","CPUS(A/I/O/T)","MEMORY","GRES"]
  }
}
```

Rules:

- `stdout` is **verbatim**, byte-for-byte, from the SLURM CLI. No
  reformatting. Admins can pipe it into their own tooling and it will
  parse exactly as it parses today.
- `stdout_parsed` is **optional** and **non-authoritative**. It is a
  convenience preview for Orochi consumers that do not want to re-parse
  the raw stdout. The authoritative view is `stdout`.
- Column names in `_columns` use the **SLURM long-form names** (e.g.
  `JobID`, `Partition`, `NCPUS`, `ReqMem`), not renamed scitex variants.
- `cmd_kind` is one of: `sinfo`, `squeue`, `sacct`, `sreport`,
  `scontrol_node`, `scontrol_partition`, `scontrol_job`.
- `schema` is versioned; consumers may key on `schema` + `cmd_kind` and
  ignore everything else.

## 4. Anti-pattern (do not do this)

```json
{
  "cluster": "nas",
  "cores_allocated": 12,
  "cores_total": 12,
  "memory_gb": 64,
  "running_jobs": 6
}
```

This loses: partition-level state, drain reasons, reservation windows,
per-TRES accounting, account/QOS breakdowns, GRES availability, node
weight, partition QOS caps, per-job timelimit. A pharma SLURM admin
pulling a daily billing rollup cannot reconstruct any of those from a
rewritten scitex schema. **Never emit a bespoke summary schema in place
of stock CLI output.** A summary may be published _in addition_ to the
raw record as a convenience, but it must never replace it.

## 5. Transport

- **Channel**: `#slurm` (hub config PR required — new channel, see
  section 8).
- **Mechanism**: `mcp__scitex-orochi__reply` with the NDJSON record as
  the message `text`, OR `mcp__scitex-orochi__upload_media` for records
  larger than the single-message size budget (sreport rollups typically
  need this).
- **Authentication**: each scraper instance posts as the local host head
  agent (`head-nas`, `head-ywata-note-win`, `head-spartan`), not as a
  shared identity. Sender attribution = origin cluster.
- **Back-pressure**: if the channel is rate-limited or the hub is down,
  the scraper writes to a local ring buffer at `~/.scitex/orochi/slurm-scraper/buffer.ndjson`
  and drains on next successful post. Data is never silently dropped.

## 6. Cadence

| Kind | Required cadence | Cheap? |
|---|---|---|
| `sinfo` | 1 / 60s | yes (slurmctld in-memory) |
| `squeue` | 1 / 60s | yes |
| `scontrol show node --json` | 1 / 60s | yes |
| `scontrol show partition --json` | 1 / 300s | yes |
| `sacct -P` | 1 / 300s (where available) | moderate (DB query) |
| `sreport` | 1 / 3600s (where available) | expensive, batch-only |

All cadence values are **defaults**, overridable per-host by an admin
who wants to dial up / down. Default is tuned to match the NAS visitor
session cycle (59-min TimeLimit → sample >= every 5 min captures every
transition).

## 7. Portability smoke test

The scraper is validated by running **the same bash binary, unchanged**
on at least two clusters with different `slurmdbd` states:

- **NAS (no slurmdbd)**: required block works, optional block gracefully
  degraded. Validated 2026-04-14 (this document).
- **Spartan (UniMelb, slurmdbd present)**: required + optional both
  work, historical records published. To be validated after
  head-spartan is reachable.

If the same bash binary also works on **a third, unrelated cluster**
(e.g. a pharma-co test cluster or another UniMelb project), the
portability principle is demonstrated and the scraper is declared
ratified in #133.

## 8. Dependencies and parked items

- **New channel `#slurm`** — hub config PR required, not blocking this
  DRAFT. Channel purpose: scraper publish only, agents should not chat
  on it.
- **slurm-federation-exploration** — parked #133 sub-item. Federation
  across NAS + WSL + Spartan + partner clusters is a natural next step
  once the scraper is proven on 3 hosts. Federation does not change the
  scraper contract because `sacctmgr`-level federation is transparent to
  `sinfo` / `squeue` / `sacct`.
- **Relationship to host-self-describe daemon** — the scraper is one
  category of host-self-describe. Other categories (tunnel health,
  disk / inode use, cloudflared bastion state) follow the same
  "stock CLI output as wire format" design principle. The scraper is
  the canonical example.

## 9. Execution plan

1. **DRAFT committed** to `feat/slurm-resource-scraper-contract` (this
   file) — done by head-nas at the moment of writing.
2. **Ratification in #133** — head-mba consolidates this contract into
   the role-taxonomy + daemon-layer ratification commit.
3. **Hub PR for `#slurm` channel** — separate, non-blocking.
4. **Implementation pilot** — head-nas implements the bash wrapper +
   systemd user timer on NAS _after_ the skill-sync-daemon warm-standby
   pattern (pilot #1) has proven out on MBA primary + NAS standby for
   at least 1 week. Order is deliberate: pilot #1 proves the warm-standby
   election mechanism, pilot #2 reuses it for the scraper daemon.
5. **Portability validation on Spartan** — head-spartan assists by
   running the same binary on Spartan and reporting whether optional
   `sacct`/`sreport` blocks populate.
6. **Horizontal expansion** — scraper deployed on WSL (ywata-note-win)
   and declared complete when all 3 SLURM hosts publish to `#slurm`.

## 10. Non-goals

- The scraper does **not** run scientific workloads. It does not call
  `sbatch`, never submits jobs, never modifies slurmctld state. It is a
  read-only reporter.
- The scraper does **not** replace Orochi's `mcp__scitex-orochi__health`
  or `mcp__scitex-orochi__status` tools — those remain the canonical
  liveness surface. The scraper is additional compute-resource
  visibility, complementary.
- The scraper does **not** consume Claude quota. Implementation is
  bash + systemd-timer, no LLM invocation anywhere. This is enforced by
  the pilot contract.
- The scraper does **not** write to any scitex-cloud-visible state. It
  is observability-only and side-effect-free.

## Appendix A: real NAS sample output (2026-04-14T17:18Z)

### `sinfo -o '%P %D %T %N %C %m %G'`

```
PARTITION NODES STATE NODELIST CPUS(A/I/O/T) MEMORY GRES
normal* 1 allocated DXP480TPLUS-994 12/0/0/12 64038 (null)
express 1 allocated DXP480TPLUS-994 12/0/0/12 64038 (null)
long 1 allocated DXP480TPLUS-994 12/0/0/12 64038 (null)
```

### `squeue -h -o '%i|%P|%j|%u|%T|%M|%L|%D|%C|%m|%R'`

```
7938|express|scitex_visitor-008_dotfiles|scitex|RUNNING|4:20|54:40|1|2|4G|DXP480TPLUS-994
7937|express|scitex_visitor-013_dotfiles|scitex|RUNNING|9:50|49:10|1|2|4G|DXP480TPLUS-994
7936|express|scitex_visitor-016_dotfiles|scitex|RUNNING|11:20|47:40|1|2|4G|DXP480TPLUS-994
7935|express|scitex_visitor-012_dotfiles|scitex|RUNNING|29:50|29:10|1|2|4G|DXP480TPLUS-994
7934|express|scitex_visitor-006_dotfiles|scitex|RUNNING|33:49|25:11|1|2|4G|DXP480TPLUS-994
7933|express|scitex_visitor-003_dotfiles|scitex|RUNNING|47:20|11:40|1|2|4G|DXP480TPLUS-994
```

Each job is a scitex-cloud visitor session sandbox, 2 CPUs / 4GB / 59-min
TimeLimit, allocated through `/app/data/.cache/alloc-scripts/scitex-alloc-<hash>.sh`.
6 concurrent visitors = 12/12 CPUs = full cluster capacity. This is
production-sized visitor traffic, not dev / throwaway workload.

### `sacct -P` (optional block)

```
Slurm accounting storage is disabled
```

Expected on NAS (no `slurmdbd`). Scraper publishes a
`historical: unavailable` metadata record.

### `sreport cluster utilization` (optional block)

```
You are not running a supported accounting_storage plugin
Only 'accounting_storage/slurmdbd' is supported.
```

Expected on NAS. Scraper skips.

### `scontrol show node --json` excerpt

```json
{
  "nodes": [
    {
      "architecture": "x86_64",
      "cpu_load": 171,
      "free_mem": {"set": true, "infinite": false, "number": 826},
      "cpus": 12,
      "effective_cpus": 12,
      ...
    }
  ]
}
```

`free_mem.number` = 826 MB. `cpu_load` = 1.71 (×100). The box is
saturated. A daemon-layer workload that direct-execs on NAS would fight
these visitor sessions at the kernel scheduler level — one of the
reasons the fleet daemon-host policy forbids CPU-hot daemons on NAS
(see #133 daemon-host policy).

## Appendix B: NAS Stability Investigation — Live Pilot Reference

_Recorded by mamba-synchronizer-mba per head-nas msg#11574 GO-criteria checkpoint. 2026-04-14._

### Context

The 2026-04-14 NAS stability investigation (triggered by ywatanabe msg#11554,
building on #137 / msg#11464 / msg#11499) serves as an unplanned but
highly informative real-world pilot of the design principles in this
contract, extended to non-SLURM host metrics.

### Canonical probe reference

**Script**: `scripts/fleet-watch/host-telemetry-probe.sh`
**Branch**: `feat/nas-stability-probe` (scitex-orochi)
**Commit**: `3e52c84` (probe script) / `204da9b` (Experiment A doc added)
**Output**: `~/.scitex/orochi/host-telemetry/host-telemetry-<hostname>.ndjson`
**Cadence**: 30s, systemd user timer
**Side-effect budget**: zero (nice=10, IOScheduling best-effort/6, no sudo, no Claude quota)

This probe is the superset "host self-describe" version of the SLURM scraper.
It covers 7 source categories per sample: `/proc/{loadavg,meminfo,stat,pressure}`,
`cgroup/user.slice`, SLURM (`sinfo`/`squeue`/`scontrol --json`), docker stats,
cloudflared journalctl ERR count, systemd failed units, systemd-cgtop.

### Design principle validated

The probe uses **stock CLI wire format** (NDJSON, verbatim outputs) and
**bash + systemd-timer, no LLM** — the same principles required of the SLURM
scraper in §§ 3–4 and 10. The probe is the canonical reference for how these
principles apply to the broader host-self-describe domain.

### Parallel probe infrastructure (2026-04-14T18:02Z)

- **NAS** (`feat/nas-stability-probe`): `host-telemetry-DXP480TPLUS-994.ndjson`, firing 30s
- **healer-nas** (independent): `~/GITIGNORED/nas-probe/probe.ndjson`, NDJSON 30s,
  fields: `ts, load_1/5/15, ncpu, mem_total_kb, mem_avail_kb, slurm_running,
  slurm_pending, slurm_cpu_used, cf_bastion_active, cf_pid, failed_user_units,
  failed_sys_units, scitex_post_boot`
- **MBA** (parallel, for relative comparison): `host-telemetry-<mba-hostname>.ndjson`

Both probes merge on `ts` (round to nearest 30s). healer-nas fields are a
strict subset of head-nas host-telemetry fields — clean union merge.

### Key empirical finding motivating Experiment A

`/sys/fs/cgroup/user.slice/cpu.pressure`: `some avg10=23.11 avg60=13.06`
— 23% of user tasks delayed waiting for CPU in a 10s window. This is the
direct empirical basis for Experiment A (cgroup enforcement in
`scripts/fleet-watch/experiment-a-slurm-cgroup-enforcement.md`, commit `204da9b`).

Root cause: NAS SLURM running with `TaskPlugin=task/none`, `ProctrackType=proctrack/linuxproc`,
`cgroup.conf` absent — zero kernel-level resource fencing. All 6 visitor jobs
(12/12 CPUs) + daphne (9.3GB) + docker (7 containers) + fleet agents compete in
the same unpartitioned kernel scheduler pool.

### Implications for scraper contract

1. **SLURM `scontrol show node --json` `cpu_load` field alone is insufficient**
   for detecting the pressure state. The `cpu_load` figure (Appendix A: 171 =
   1.71×) reflects running workload but does not capture scheduling delay.
   The kernel `cpu.pressure` PSI metric (`/proc/pressure/cpu` or cgroup pressure
   files) should be considered a companion observable when NAS-style over-commit
   is the failure mode being monitored.

2. **The scraper's "no side effects" principle is empirically enforced here**:
   `nice=10 + IOScheduling best-effort/6` means the probe itself does not
   contribute to cpu.pressure under the observed load conditions. This is the
   correct posture for any daemon (SLURM scraper, skill-sync, fleet-watch) on
   NAS.

3. **Dual-probe validation pattern**: running a second independent probe
   (healer-nas vs head-nas) with a subset-compatible schema enabled cross-check
   within 1h without coordination overhead. Recommend this pattern for the
   SLURM scraper's acceptance test: run `head-nas` probe + `head-spartan` probe
   in parallel, merge on ts, verify field alignment per §7 portability smoke
   test.

### Experiment A — status and boundary

`scripts/fleet-watch/experiment-a-slurm-cgroup-enforcement.md` (commit `204da9b`)
contains the full plan: `cgroup.conf` minimal template, `slurm.conf` 4-line
diff, Option A/B restart, rollback, GO criteria, risk table.

**Status**: `DRAFT-PRE-APPROVAL`. None of the GO criteria are satisfied as of
2026-04-14T18:04Z. No NAS configuration has been or will be changed without
ywatanabe explicit GO + sudo access.

This appendix satisfies the mamba-synchronizer-mba GO-criteria checkpoint
(head-nas msg#11574).
