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

## Continued in

- [`55_slurm-resource-scraper-contract-fields.md`](55_slurm-resource-scraper-contract-fields.md)
