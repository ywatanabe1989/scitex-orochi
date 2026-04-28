---
name: orochi-hpc-etiquette-general-rules
description: General HPC rules — apply across Spartan, NCI, future sites. Filesystem, network, login-node policy basics. (Split from 60_hpc-etiquette-general-extras.md.)
---

> Sibling: [`77_hpc-etiquette-general-tools.md`](77_hpc-etiquette-general-tools.md) for absolute rules, binary location, scoping, SLURM etiquette, login-node policy.
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

