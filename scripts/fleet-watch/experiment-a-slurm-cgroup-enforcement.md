---
status: DRAFT-PRE-APPROVAL
ratified: false
requires: ywatanabe explicit GO + sudo access
authors: [head-nas, mamba-explorer-mba]
parent-investigation: ywatanabe msg#11554 (2026-04-14)
related-issues:
  - scitex-orochi#137 (cgroup-limits hypothesis)
  - scitex-orochi#139 (fleet-prompt-actuator tmux timeout symptom)
  - scitex-orochi#140 (fleet-watch env-mismatch, unrelated)
---

# Experiment A — SLURM kernel-level resource enforcement on NAS

> **DO NOT EXECUTE without explicit ywatanabe GO and sudo access.**
> This document is the design-time plan, rollback procedure, and pre-flight
> read-only verification for Experiment A of the 2026-04-14 NAS instability
> investigation. It describes changes to `/etc/slurm/cgroup.conf` and
> `/etc/slurm/slurm.conf` that require root privileges on NAS. Every command
> marked `# REQUIRES SUDO` below must be run by ywatanabe or a root-capable
> operator.

## 1. Why this experiment

Phase-1 empirical observation (head-nas probe, head-mba probe, mamba-healer-nas
probe, 2026-04-14):

- `/sys/fs/cgroup/user.slice/cpu.pressure` reported `avg10=23.11% avg60=13.06%`
  at investigation start. That is unambiguous resource contention: 23% of user
  tasks were blocked on CPU scheduler in the last 10 seconds.
- `fleet-prompt-actuator.service` failed with
  `subprocess.TimeoutExpired: tmux list-sessions timed out after 15s` 3h37m
  before probe start. `tmux list-sessions` is a trivial fork+read. When it
  takes more than 15s it is a direct symptom of user-slice scheduler
  starvation, not a tmux bug.
- `sinfo -o` and `squeue` showed 6 running `scitex_visitor-*_dotfiles` SLURM
  jobs, 12/12 CPUs allocated, 24GB RAM, all on a single node
  `DXP480TPLUS-994`.

Phase-1 pre-flight reads (head-nas 2026-04-14, all non-sudo, read-only):

```
$ slurmd -V
slurm 24.05.5

$ grep -E "^(ProctrackType|TaskPlugin|JobAcctGatherType|PrologFlags)" /etc/slurm/slurm.conf
ProctrackType=proctrack/linuxproc
TaskPlugin=task/none
JobAcctGatherType=jobacct_gather/none

$ scontrol show config | grep -E "^(ProctrackType|TaskPlugin|JobAcctGatherType|PrologFlags)"
JobAcctGatherType       = (null)
ProctrackType           = proctrack/linuxproc
PrologFlags             = (null)
TaskPlugin              = (null)
TaskPluginParam         = (null type)

$ ls /etc/slurm/cgroup.conf
ls: cannot access '/etc/slurm/cgroup.conf': No such file or directory

$ mount | grep cgroup
cgroup2 on /sys/fs/cgroup type cgroup2 (rw,nosuid,nodev,noexec,relatime,nsdelegate,memory_recursiveprot)

$ systemctl cat slurmd.service | grep Delegate
Delegate=yes
```

**What this tells us**:

1. **SLURM on NAS is running `TaskPlugin=task/none` (literally null)**.
   There is no task plugin loaded at all — not `task/cgroup`, not `task/affinity`,
   nothing. That means slurmctld allocates CPUs and memory at the scheduler
   level, but slurmd has no mechanism whatsoever to enforce those allocations
   on the Linux kernel. A visitor job allocated 2 CPUs can freely consume
   all 12. A job allocated 4GB can freely consume all 64GB.
2. **`ProctrackType=proctrack/linuxproc`** uses Linux process-table scanning
   to track job membership. This is the fallback plugin used when cgroup
   proctrack is unavailable. It misses forked/daemonized processes and
   cannot enforce resource bounds.
3. **`JobAcctGatherType=(null)`** means no per-job resource accounting is
   collected at all. `sacct` returning "Slurm accounting storage is disabled"
   earlier (head-nas slurm-resource-scraper-contract.md § A.3) is actually
   consistent: even if slurmdbd were configured, there's nothing gathering
   job-level resource usage to store.
4. **cgroupv2 unified mount is ready** (`cgroup2 on /sys/fs/cgroup`), and
   `slurmd.service` has `Delegate=yes`. All the kernel-side prerequisites
   for cgroup enforcement are in place; SLURM just isn't configured to use
   them.
5. **An existing slurm.conf backup** is present at
   `/etc/slurm/slurm.conf.backup.20251205_231553` (2025-12-05). That is a
   known-good pre-investigation state we can revert to.

**Hypothesis (testable)**: Enabling `TaskPlugin=task/cgroup,task/affinity` +
`ProctrackType=proctrack/cgroup` + `ConstrainCores/RAMSpace/SwapSpace=yes` in a
new `/etc/slurm/cgroup.conf` will cause the kernel to enforce SLURM's
allocation promises per-job, reducing user.slice cpu.pressure and eliminating
the second-order fleet failures (`fleet-prompt-actuator` tmux timeout).

## 2. The minimal diff (from mamba-explorer-mba msg#11570)

### 2.1 New file `/etc/slurm/cgroup.conf`

```
CgroupPlugin=cgroup/v2
CgroupMountpoint=/sys/fs/cgroup
ConstrainCores=yes
ConstrainRAMSpace=yes
ConstrainSwapSpace=yes
AllowedSwapSpace=0
MinRAMSpace=30
AllowedRAMSpace=100
```

This file does not exist today. It must be created fresh.

### 2.2 Additions to `/etc/slurm/slurm.conf`

Add exactly these four lines, replacing any existing definitions of the same
keys:

```
ProctrackType=proctrack/cgroup
TaskPlugin=task/cgroup,task/affinity
JobAcctGatherType=jobacct_gather/cgroup
PrologFlags=Contain
```

**Before-state on NAS** (confirmed 2026-04-14):

```
ProctrackType=proctrack/linuxproc      # will change
TaskPlugin=task/none                    # will change
JobAcctGatherType=jobacct_gather/none   # will change
(no PrologFlags line)                   # will add
```

### 2.3 NAS-specific gotchas from explorer (msg#11570)

- **`Delegate=yes` is already on slurmd** ✅ — cgroup-delegation conflict
  avoided.
- **Do NOT set `IgnoreSystemd=yes`** — catastrophic with systemd-unified
  cgroup.
- **Docker containers on NAS should use `--cgroupns=private`** — they
  currently don't (running as default `host`). **Out of scope for
  Experiment A**; docker cgroup-namespacing is a separate experiment B.
- Start with `AllowedRAMSpace=100`. If OOM-kill events spike, raise to 110.
- Monitor `journalctl -u slurmd -f | grep -i cgroup` and
  `dmesg | grep -i oom` for the first 15 minutes after apply.

## 3. Execution sequence (REQUIRES SUDO)

Every command below must run as root. Do NOT execute until ywatanabe GO.

### 3.1 Pre-apply: make a fresh-timestamped backup

```bash
# REQUIRES SUDO
ts="$(date -u +%Y%m%dT%H%M%SZ)"
sudo cp -v /etc/slurm/slurm.conf "/etc/slurm/slurm.conf.backup.${ts}.pre-experiment-a"
```

A 2025-12-05 backup already exists (confirmed by head-nas pre-flight). The
new timestamped backup is additional and captures any drift that may have
happened since December.

### 3.2 Write the new `cgroup.conf`

```bash
# REQUIRES SUDO
sudo tee /etc/slurm/cgroup.conf > /dev/null <<'EOF'
CgroupPlugin=cgroup/v2
CgroupMountpoint=/sys/fs/cgroup
ConstrainCores=yes
ConstrainRAMSpace=yes
ConstrainSwapSpace=yes
AllowedSwapSpace=0
MinRAMSpace=30
AllowedRAMSpace=100
EOF
sudo chown slurm:slurm /etc/slurm/cgroup.conf
sudo chmod 644 /etc/slurm/cgroup.conf
```

### 3.3 Edit `slurm.conf` in place (4 line changes)

**Manual edit** (do NOT sed in place on a live config without reviewing):
Open `/etc/slurm/slurm.conf` with an editor. Find and change:

```
-ProctrackType=proctrack/linuxproc
+ProctrackType=proctrack/cgroup

-TaskPlugin=task/none
+TaskPlugin=task/cgroup,task/affinity

-JobAcctGatherType=jobacct_gather/none
+JobAcctGatherType=jobacct_gather/cgroup
```

And **add a new line** (does not exist today):

```
+PrologFlags=Contain
```

### 3.4 Apply via `scontrol reconfig` (Option A, non-disruptive)

```bash
# REQUIRES SUDO
sudo scontrol reconfig
```

Wait ~10 seconds. Then verify the new config is loaded:

```bash
scontrol show config | grep -E "^(ProctrackType|TaskPlugin|JobAcctGatherType|PrologFlags)"
```

Expected output:

```
JobAcctGatherType       = jobacct_gather/cgroup
ProctrackType           = proctrack/cgroup
PrologFlags             = Contain
TaskPlugin              = task/cgroup,task/affinity
```

### 3.5 Verify cgroup hierarchy was created

Passive check (may not show anything immediately if no new jobs have
started yet, because the old linuxproc-tracked visitors continue under
the old plugin):

```bash
ls -la /sys/fs/cgroup/slurm/
```

**Active verification** (recommended, per mamba-explorer-mba msg#11576):
force creation of a cgroup by submitting a trivial job, then check.

```bash
# Active verification — forces cgroup hierarchy creation
srun -N1 --mem=256M -n1 hostname &
sleep 2
ls -la /sys/fs/cgroup/slurm/
```

Expected: new `/sys/fs/cgroup/slurm/` directory appears, containing at
least one sub-directory for the `srun` test job. If this directory does
NOT appear after the active `srun`, the reconfig did not take effect —
fall through to rollback.

## 4. Rollback procedure

If any of the following happen, immediately roll back:

- `scontrol reconfig` returns non-zero
- `/sys/fs/cgroup/slurm/` does not appear
- Visitor jobs start OOM-killing within 5 minutes
- slurmctld crashes or refuses to start
- `sinfo` shows nodes in `DOWN` / `DRAIN` / `FAIL` state unexpectedly

Rollback commands (REQUIRES SUDO):

```bash
# REQUIRES SUDO
ts="$(ls /etc/slurm/slurm.conf.backup.*.pre-experiment-a | tail -1)"
sudo cp -v "$ts" /etc/slurm/slurm.conf
sudo rm -f /etc/slurm/cgroup.conf
sudo scontrol reconfig
```

Fallback if `scontrol reconfig` itself is broken:

```bash
# REQUIRES SUDO
sudo systemctl restart slurmctld slurmd
sudo scontrol show config | grep -E "^(ProctrackType|TaskPlugin|JobAcctGatherType)"
```

Ultimate fallback (re-use the 2025-12-05 backup):

```bash
# REQUIRES SUDO
sudo cp -v /etc/slurm/slurm.conf.backup.20251205_231553 /etc/slurm/slurm.conf
sudo rm -f /etc/slurm/cgroup.conf
sudo systemctl restart slurmctld slurmd
```

## 5. Post-apply observation window (15 minutes)

After `scontrol reconfig` succeeds, leave the host-telemetry-probe running and
watch for:

### Expected signals (if hypothesis holds)

- `cpu.pressure avg10` on `/sys/fs/cgroup/user.slice/cpu.pressure` drops from
  ~20% to <5%.
- `sinfo -o` still shows the same running visitor jobs (they survive
  reconfig with `Option A`).
- `/sys/fs/cgroup/slurm/` populates with one cgroup per running job.
- New visitor job launches appear with correct per-job cgroup limits.
- `fleet-prompt-actuator.service` next invocation does NOT time out on
  `tmux list-sessions`.

### Failure signals (trigger rollback)

- Visitor jobs OOM-killed immediately (check `dmesg | grep -i oom`)
- slurmctld log showing cgroup plugin errors (`journalctl -u slurmctld -f`)
- slurmd log showing cgroup mount errors (`journalctl -u slurmd -f`)
- cpu.pressure does NOT drop after 5 minutes → hypothesis weaker than
  expected, investigate before declaring success

### Telemetry tie-in

The `host-telemetry-probe.sh` timer is already running at 30s cadence and
captures all of the observation signals above in the same NDJSON format
(`proc_pressure_cpu`, `cgroup_user_cpu_pressure`, `sinfo`, `squeue`,
`scontrol_node_json`, `systemd_user_units_failed`). No separate logging
infrastructure is required for the experiment; the probe IS the
observability layer.

At T+15min after apply, head-nas will join the probe data from before and
after apply, compute the cpu.pressure delta, and report on #agent.

## 6. Visitor traffic consideration

At time of writing, 6 `scitex_visitor-*_dotfiles` jobs are running on NAS
(real scitex-cloud production traffic, not dev workload). Option A
(`scontrol reconfig`) is explicitly chosen because it **does NOT kill running
jobs**. The currently-running visitors will continue under the OLD proctrack
plugin until they exit at their 59-minute TimeLimit, and NEW visitor jobs
submitted after reconfig will use the new cgroup proctrack.

**This means**: for ~59 minutes after apply, the NAS is in a mixed state
where older jobs run without kernel enforcement and newer jobs run with it.
That is fine — it is the graceful transition path. The post-apply observation
window should therefore run at least 60 minutes to ensure every running job
is cgroup-bound before declaring success.

## 7. What this does NOT change

Explicitly out of scope for Experiment A:

- **`slurmdbd` accounting** — Experiment A does not install `slurmdbd`.
  `sacct` / `sreport` will continue to report accounting unavailable.
  That is a separate experiment (Experiment C, parked).
- **Docker cgroup namespacing** — containers continue to run as
  `--cgroupns=host` by default. That is Experiment B, parked.
- **Cloudflared CPU shares** — Experiment D, parked until A's effect is
  measured.
- **`scitex-post-boot.service`** (failed since Apr 6, #137) — rolling
  Experiment A does not address the stuck unit. That is a separate sudo
  action ywatanabe can bundle with Experiment A's sudo session.
- **fleet-watch.service env mismatch** (#140) — unrelated to cgroup
  enforcement, tracked separately.

## 8. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| slurmctld refuses reconfig | Low | High | Rollback § 4, `Option B` conservative restart |
| Visitor jobs OOM-killed on reconfig | Medium | Medium | `Option A` protects running jobs; only new jobs get limits |
| cgroup hierarchy not created | Low | High | Pre-flight confirmed cgroupv2 + Delegate=yes, diff is minimal |
| NAS becomes SSH-unreachable | Very low | Critical | Pre-experiment sanity: verify ywatanabe has console access via bastion |
| Experiment succeeds but side-effects on scitex-cloud | Medium | Medium | 15-min observation window + full probe telemetry + explicit rollback |
| Experiment fails + rollback also fails | Very low | Critical | 2 rollback layers + original 2025-12-05 backup |

## 9. GO criteria

Experiment A may proceed when all of the following are true:

- [ ] head-nas has 1h+ of baseline telemetry showing sustained user.slice
      cpu.pressure > 10% (not a transient spike)
- [ ] head-mba has delivered MBA comparison baseline to confirm the
      pressure is NAS-local (not a fleet-wide issue)
- [ ] mamba-explorer-mba has reviewed this document for pattern accuracy
- [ ] mamba-synchronizer-mba has recorded the design in
      `slurm-resource-scraper-contract.md` as the "first observed
      production experiment target"
- [ ] ywatanabe has read this document and given explicit GO
- [ ] ywatanabe has sudo access ready (or delegated to someone who does)
- [ ] A 60-minute post-apply observation window is acceptable (no
      pressing need for the NAS during that time)

## 10. Post-ratification

After Experiment A succeeds (or fails and rolls back cleanly), this file
will be renamed from `experiment-a-slurm-cgroup-enforcement.md` to
`investigation/2026-04-14-nas-cgroup-enforcement.md` and marked with its
actual outcome, commit SHAs, and observed cpu.pressure deltas, so the
process leaves a permanent audit trail.
