---
name: orochi-hpc-etiquette-general
description: General HPC cluster etiquette — login nodes, schedulers, filesystems, modules, network, and absolute rules (never find /, never compute on login nodes, etc.). Sub-file of hpc-etiquette.md.
---

# HPC etiquette — general rules

> Sub-file of `hpc-etiquette.md`. See the orchestrator for context and the
> Spartan-specific canonical policy + guardrails sub-files.

# HPC etiquette

Shared HPC filesystems have hundreds of millions of files and are watched by admins who can and will revoke access. A single agent scripting `find / -name X` across `/data/gpfs` hits the filesystem as hard as any real workload and is indistinguishable from a denial-of-service from the storage layer's perspective.

This skill is the fleet's rulebook for being a good HPC guest, written specifically after the 2026-04-14 incident where Sean Crosby (Head of Research Computing Infrastructure, UniMelb) emailed the operator to stop running `find / -name pdflatex` on Spartan (msg #10971). That `find` was started by an agent trying to locate a binary — the kind of operation that is free on a laptop and catastrophic on a shared cluster.

## General HPC rules (apply to every cluster the fleet touches — Spartan, NCI, future sites)

Before the Spartan-specific section below, the general rules every agent must follow on **any** HPC system. These generalize the Sean Crosby incident so that the same lesson does not need to be relearned on NCI / Gadi / Pawsey / DataCrunch / AWS ParallelCluster / etc.

### Compute + jobs

- **Never run compute on a login node.** Login nodes are for SSH, `cp`, `git`, `module avail`, `sbatch`, `squeue`, and short file inspection. They are not for training, inference, `pip install`ing large wheels, building C++, or running Jupyter kernels. Every site has at least one way to enforce this (Spartan: `cgroup nproc=1`; NCI: SIGKILL after N minutes; others: admin email). Do not fight the enforcement; use `srun` or `sbatch` to get onto a compute node.
- **Every long-running job goes through the scheduler** — SLURM, PBS/Torque, LSF, Kubernetes, whichever the site uses. Raw `nohup python train.py &` or `tmux new -d ...` on the login node is a policy violation on every site. If you need interactive access, use `srun --pty bash -i` / `qsub -I` / equivalent.
- **Always set `--time=HH:MM:SS`** (or PBS `walltime=`, LSF `-W`, etc.). Unbounded jobs are caught by admin sweeps and cancelled with prejudice. 24:00:00 is not "unbounded" — it is 24 hours and the scheduler decides when it ends.
- **Respect fair-share quotas and walltime limits.** Check the site docs for max concurrent jobs, max wall time per partition, max GPUs per user. Submitting 500 jobs at once when the quota is 50 is a policy violation even if the jobs are small.
- **Clean up after yourself**: `scancel` stale / abandoned jobs before submitting new ones (`squeue -u $USER -t CD,F,CA,TO,NF` for already-terminated rows to purge via `sacctmgr` if needed). Leaving a stuck `PENDING` queue behind is visible to admins.
- **Do not poll `sinfo` / `squeue` / `sacct` in tight loops.** Every site's scheduler database is shared; hammering it affects everyone. Minimum interval for polling queues is 60 s; prefer 5 min. Reference cached output where possible (the spartan dashboard for instance, see `infra-spartan-dashboard.md`).

### Filesystems + metadata

- **Never unbounded filesystem walks** — `find /`, `du /`, `ls -R /`, `rsync -a /`, `tar cf - /`. All of these are banned in the absolute rules below. The ban applies to **every** HPC site, not just Spartan.
- **Never walk `$HOME` on shared/NFS home**. Same failure at smaller scale.
- **Respect disk + inode quotas** per user and per project. Check with the site-specific CLI:
    - Spartan: `lfs quota` / `mmlsquota` / dashboard
    - NCI: `nci_account` / `lquota`
    - Generic: the site docs
  Check *before* a large job, not after it fails.
- **Consolidate small outputs into SQLite / Parquet / tarballs** instead of thousands of per-item files. Inode quotas bite faster than byte quotas; one SQLite replacing 10k PNGs buys you 10k inodes. `scitex.archive` + `scitex.db` exist for this.
- **Use `$SCRATCH` for ephemeral / intermediate data**, not `$HOME`. Move persistent results to the project-assigned storage (`/data/gpfs/projects/<punim>/` on Spartan, `/g/data/<proj>/` on NCI) before scratch purge sweeps.
- **Clean `/tmp` and scratch on job exit.** Wrap `sbatch` scripts in a trap:
  ```bash
  trap 'rm -rf "$TMPDIR"/run.$SLURM_JOB_ID' EXIT
  ```
  A terminated job that leaves behind GB in `/tmp` is visible to node operators.
- **Do not metadata-storm.** Creating 100k small files in a loop, stat-ing a directory thousands of times per second, or renaming/touching every file on disk all count as metadata attacks regardless of intent. Batch operations, use `--files-from` lists, aggregate.

### Modules + environment

- **Always use the site module system** (Lmod / Environment Modules / Spack / TCL modules) to load compilers, Python, CUDA, MPI, etc. Do not manually edit `$PATH` / `$LD_LIBRARY_PATH` with hard-coded absolute paths to `/apps/...` — the paths change between upgrades and your script will silently break.
- **Prefer `module load <pkg>/<version>`** with an explicit version over `module load <pkg>` without one. Sites change the default version without notice.
- **`module list`** before and after your job runs confirms the toolchain picked up what you expected. Log it in job output.
- **Do not `source` `/etc/profile` or `~/.bashrc` inside a script** as a way to "make modules work". Use `module load` directly or run the wrapper in an interactive shell that already sourced its profile. Calling `source /etc/profile` in a scripted context is a smell for a deeper `bash -lc` problem; see `convention-connectivity-probe.md` for the proper wrap.

### Network + SSH

- **No parallel SSH fork-bombs.** `parallel-ssh` / `pdsh` to 100+ nodes is a denial-of-service against the cluster's SSH daemon. Use the scheduler's job array or `srun --nodes=N --ntasks=N` instead.
- **Use the site bastion if one is configured.** Direct SSH from a login node to a compute node often goes through cgroup / firewall restrictions; the bastion exists because that path is not blessed.
- **Outbound-only from compute nodes** is the norm. HTTPS + outgoing SSH typically work; opening inbound listeners does not. See `orochi-bastion-mesh` skill for the fleet's way to put persistent reverse tunnels inside long-walltime sbatch jobs.
- **Download once, cache locally.** Do not re-fetch large datasets per script run; pin to `$SCRATCH/cache/` or a site dataset directory and reuse.

### Process + billing hygiene

- **`ps -ef | grep $USER`** on the login node before leaving, to confirm no stray processes are running. An agent that leaves behind a zombie `python` on login1 gets that process killed and the agent flagged.
- **Charge the right project.** `sbatch --account=<project-id>` (or your site equivalent) so compute is billed against the allocated project, not the user default. Wrong-account billing creates admin work.
- **Respect submission rate limits.** Some sites throttle `sbatch`; spamming 50 jobs in 10 seconds gets your submission rights rate-limited or revoked temporarily.

### Documentation + first contact

- **Read the site's user guide before your first job.** Most sites publish a wiki (Spartan: `https://dashboard.hpc.unimelb.edu.au/` links to the user guide; NCI: `https://opus.nci.org.au/`). Partition names, quota limits, account codes, bastion hosts, storage paths all live there.
- **Start with the smallest possible test job** before submitting a full-scale workload. 5 minutes on one core is a cheap way to discover that your module load chain is wrong.
- **If in doubt, email the site's help desk before running the job**, not after it breaks production. Admins are much happier answering a pre-emptive question than cleaning up a filesystem storm.

### If you are not sure whether a command is HPC-safe

Defensive rules of thumb:

- Does it touch a path that starts with `/`, `/data`, `/scratch`, `/home` **without** a specific subpath? → unsafe
- Does it scan more than ~10k files? → unsafe
- Does it run more than 60 s on a login node? → unsafe, move to `sbatch`
- Does it re-run every cycle in a polling loop faster than 60 s? → unsafe, cache
- Is there a site dashboard page / CLI that gives the same answer? → use that
- Would Sean Crosby email the operator if he saw this in `ps -ef`? → if yes, don't run it

The last one is the canonical test.

## The absolute rules

1. **Never `find /`.** Under any circumstances, on any HPC system, for any reason. Not even with `-maxdepth` limits. Not even with `2>/dev/null`. Not even briefly. The traversal starts before the filter applies; the filesystem pays for the walk regardless of what you filter out.

2. **Never walk the full home directory recursively on NFS.** `find ~/` / `du -sh ~/` / `ls -R ~/` on a GPFS or Lustre home is the same failure mode at a smaller scale. Use specific subpaths.

3. **Never run compute on the login node.** Policy-mandated on most HPC sites (Spartan's `cgroup nproc=1` on login1 enforces this by killing long-running processes). Controllers only; compute goes in `sbatch` / `srun` / `salloc`. See `hpc-spartan-startup-pattern.md` + memory `project_spartan_login_node.md`.

4. **Never run background `sleep inf` loops to hold allocations.** Use `sbatch --time=...` with a real walltime. Indefinite holds look exactly like orphaned jobs to schedulers and draw admin attention.

5. **Never `rsync -r` or `tar cf -` the entire `$HOME`.** Scope the operation to the specific subtree you need.

## Binary location — what to do instead of `find`

The 2026-04-14 incident was an agent trying to locate `pdflatex`. Here is the correct cascade, in order of preference and filesystem friendliness:

```bash
# 1. POSIX shell built-in — zero filesystem cost beyond the PATH cache
command -v pdflatex

# 2. which — same effect, one extra process
which pdflatex

# 3. type — shell builtin variant, extra details
type pdflatex

# 4. Module system — the canonical way on HPC
module avail texlive 2>&1 | head -10
module show texlive/20230313 2>&1

# 5. Loaded module list — find already-loaded tools
module list 2>&1 | head

# 6. Package database — if apt / dnf / rpm available
dpkg -L texlive-latex-base 2>/dev/null | grep bin/pdflatex
```

If all six fail, the binary is not available in any sanctioned location, and running `find` will not change that fact. Stop; install via `module load`, `pip`, `conda`, `pipx`, or ask the HPC help desk.

**Never** script fallbacks like `command -v X || find / -name X` — that is the failure mode the incident surfaced. The fallback *is* the bad behavior.

## Scoping filesystem queries

When you genuinely need to search a directory tree, **scope tight**:

```bash
# OK: scoped to a single subdir, one level deep
find ~/proj/scitex-python -maxdepth 2 -name '*.toml'

# OK: scoped to a single package's artifacts
ls ~/.cache/pip/wheels/

# OK: use cached metadata from the package manager
pip show scitex | grep Location

# BAD: unbounded
find / -name '*.toml'
find /data -name 'foo'
find ~ -name 'bar' -print    # home is NFS on HPC
du -sh ~/
```

Every `find` / `du` / `ls -R` invocation should answer "is the scope I am about to walk smaller than a few thousand files?". If not, it is the wrong tool.

## Inode-aware operations

HPC quotas are **per-user inodes**, not just bytes. The 2026-04-14 NeuroVista backfill hit a project directory with 72 free inodes (#372) because the PAC pipeline created one file per small artifact. Rules:

- **Consolidate small artifacts into SQLite / Parquet / tarballs** rather than thousands of per-item files. `scitex.archive` + `scitex.db` exist specifically for this.
- **Use `scitex.session` + `scitex.archive`** for pipeline outputs so session dirs become one SQLite, not `_out/` trees.
- **Clean up old RUNNING/stale session dirs** — per-session subdirs accumulate if not purged on success.
- **Never write one file per input sample** if you can write one SQLite per batch.

## SLURM etiquette

- Always set `--time=HH:MM:SS`. Unbounded jobs are caught by admin sweeps.
- Never submit more than the site's per-user concurrent job limit. `squeue -u $USER` before submitting a batch.
- Use the correct partition. `long` is for 90-day tunnels and stable services, `sapphire` for GPU work, `physical` for CPU. Misusing `long` for short jobs wastes the partition budget.
- Release unused allocations via `scancel` when you are done. Do not leave an `salloc` shell open overnight "just in case".
- `sbatch` jobs that are holders for long-running tunnels are allowed (see `hpc-spartan-startup-pattern.md`), but they must be single-purpose, documented, and tracked in `~/.scitex/orochi/scripts/`.

## Login-node policy (Spartan-specific but generalizable)

- `login1` / `login2` are **controller-only** nodes. No inference, no training, no `pip install` of heavy wheels (`torch`, `tensorflow`, etc.), no heavy compile, no background loops that stay resident past your ssh session.
- `cgroup nproc=1` on Spartan login1 auto-kills long-running processes. Do not fight it.
- Interactive work needs `srun --pty bash -i` on a compute node, not a login-node screen session.
- `tmux` / `screen` on login1 is OK for short-lived agent coordinators, not for compute. The `worker-healer-<host>` agent runs on login1 as a coordinator; it does not run inference or training.

See also the canonical UniMelb policy section below — the fleet's own login-node rule is a summary, the canonical source is the authority.
