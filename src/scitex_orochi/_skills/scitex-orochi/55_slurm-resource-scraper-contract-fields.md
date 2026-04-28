---
status: DRAFT
ratified: false
ratification-thread: scitex-orochi#133
owner: head-nas
pilot-order: "#2 (after skill-sync-daemon warm-standby proof)"
last-updated: 2026-04-14
authors: [head-nas, head-mba]
---

> Part 2 of 2. See [`44_slurm-resource-scraper-contract.md`](44_slurm-resource-scraper-contract.md) for the orchestrator/overview.
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
