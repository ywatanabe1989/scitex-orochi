---
name: orochi-hpc-etiquette-general-tools
description: Absolute rules + binary-location guidance + scoping filesystem queries + inode-aware ops + SLURM etiquette + login-node policy. (Split from 60_hpc-etiquette-general-extras.md.)
---

> Sibling: [`60_hpc-etiquette-general-rules.md`](60_hpc-etiquette-general-rules.md) for the general HPC rules.

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
