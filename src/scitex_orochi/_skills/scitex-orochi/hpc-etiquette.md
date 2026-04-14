---
name: orochi-hpc-etiquette
description: How to be a good citizen on shared HPC filesystems (Spartan et al). What NOT to run — especially no `find /`, no full-tree walks, no login-node compute. Response to the 2026-04-14 Sean Crosby (UniMelb HPC admin) complaint about unbounded find.
scope: fleet-internal
---

# HPC etiquette

Shared HPC filesystems have hundreds of millions of files and are watched by admins who can and will revoke access. A single agent scripting `find / -name X` across `/data/gpfs` hits the filesystem as hard as any real workload and is indistinguishable from a denial-of-service from the storage layer's perspective.

This skill is the fleet's rulebook for being a good HPC guest, written specifically after the 2026-04-14 incident where Sean Crosby (Head of Research Computing Infrastructure, UniMelb) emailed ywatanabe to stop running `find / -name pdflatex` on Spartan (msg #10971). That `find` was started by an agent trying to locate a binary — the kind of operation that is free on a laptop and catastrophic on a shared cluster.

## The absolute rules

1. **Never `find /`.** Under any circumstances, on any HPC system, for any reason. Not even with `-maxdepth` limits. Not even with `2>/dev/null`. Not even briefly. The traversal starts before the filter applies; the filesystem pays for the walk regardless of what you filter out.

2. **Never walk the full home directory recursively on NFS.** `find ~/` / `du -sh ~/` / `ls -R ~/` on a GPFS or Lustre home is the same failure mode at a smaller scale. Use specific subpaths.

3. **Never run compute on the login node.** Policy-mandated on most HPC sites (Spartan's `cgroup nproc=1` on login1 enforces this by killing long-running processes). Controllers only; compute goes in `sbatch` / `srun` / `salloc`. See `spartan-hpc-startup-pattern.md` + memory `project_spartan_login_node.md`.

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

HPC quotas are **per-user inodes**, not just bytes. The 2026-04-14 NeuroVista backfill hit `/data/gpfs/projects/punim2354` with 72 free inodes (#372) because the PAC pipeline created one file per small artifact. Rules:

- **Consolidate small artifacts into SQLite / Parquet / tarballs** rather than thousands of per-item files. `scitex.archive` + `scitex.db` exist specifically for this.
- **Use `scitex.session` + `scitex.archive`** for pipeline outputs so session dirs become one SQLite, not `_out/` trees.
- **Clean up old RUNNING/stale session dirs** — per-session subdirs accumulate if not purged on success.
- **Never write one file per input sample** if you can write one SQLite per batch.

## SLURM etiquette

- Always set `--time=HH:MM:SS`. Unbounded jobs are caught by admin sweeps.
- Never submit more than the site's per-user concurrent job limit. `squeue -u $USER` before submitting a batch.
- Use the correct partition. `long` is for 90-day tunnels and stable services, `sapphire` for GPU work, `physical` for CPU. Misusing `long` for short jobs wastes the partition budget.
- Release unused allocations via `scancel` when you are done. Do not leave an `salloc` shell open overnight "just in case".
- `sbatch` jobs that are holders for long-running tunnels are allowed (see `spartan-hpc-startup-pattern.md`), but they must be single-purpose, documented, and tracked in `~/.scitex/orochi/scripts/`.

## Login-node policy (Spartan-specific but generalizable)

- `login1` / `login2` are **controller-only** nodes. No inference, no training, no `pip install` of heavy wheels (`torch`, `tensorflow`, etc.), no heavy compile, no background loops that stay resident past your ssh session.
- `cgroup nproc=1` on Spartan login1 auto-kills long-running processes. Do not fight it.
- Interactive work needs `srun --pty bash -i` on a compute node, not a login-node screen session.
- `tmux` / `screen` on login1 is OK for short-lived agent coordinators, not for compute. The `mamba-healer-spartan` agent runs on login1 as a coordinator; it does not run inference or training.

## Network etiquette

- **Outbound-only from HPC**. UniMelb allows outbound SSH, HTTPS, and a small allowlist of registry hosts. Do not attempt to open inbound ports on login nodes.
- **Cloudflare named tunnels** (`bastion-spartan.scitex-orochi.com`) run inside a compute-node sbatch job, not on login1. See `orochi-bastion-mesh` skill.
- **Download once, cache locally**. Do not re-fetch large datasets on every script run; pin the dataset into `~/scratch/cache/` or equivalent.

## Storage hygiene

- **`$HOME` is small and slow** on HPC. Do not keep datasets there. Use project-assigned `/data/gpfs/projects/<punim>/` or `$SCRATCH`.
- **`$SCRATCH` is fast and ephemeral**. OK for intermediate files; expect periodic purge by admin sweeps. Move anything you want to keep to project storage before the scheduled purge.
- **Check quotas**: `sacctmgr show assoc user=$USER format=account,user,partition,maxsubmitjobs` + `mmlsquota` + `du --max-depth=1 /data/gpfs/projects/<punim>/`.
- **Never `rm -rf` inside a shared project dir without confirming you own every leaf file**. Other group members may have written data you cannot see.

## Shell-level guardrails

Every agent that runs shell commands on HPC should have these aliases available (source from a host-gated bash file, see `spartan-hpc-startup-pattern.md` for the hostname guard pattern):

```bash
# Refuse unbounded find
find() {
    for arg in "$@"; do
        if [[ "$arg" == "/" || "$arg" == "$HOME" ]]; then
            echo "HPC-ETIQUETTE: refusing unbounded find on $arg; use command -v / which / module avail instead" >&2
            echo "                 see scitex-orochi/_skills/scitex-orochi/hpc-etiquette.md" >&2
            return 2
        fi
    done
    command find "$@"
}

# Refuse full-tree du on home
du() {
    for arg in "$@"; do
        if [[ "$arg" == "$HOME" || "$arg" == "~/" ]]; then
            echo "HPC-ETIQUETTE: refusing du on \$HOME; scope tighter" >&2
            return 2
        fi
    done
    command du "$@"
}
```

These are defensive — they catch the common bad patterns at the shell layer so an agent that "tries to be helpful" with a fallback `find /` gets an explicit refusal and a pointer to this skill instead.

## Anti-patterns observed (2026-04-14 incident)

Sean Crosby's email quoted the offending command line:

```
bash -c 'find / -name pdflatex 2>/dev/null | head -5; source /etc/profile 2>&1; which pdflatex 2>&1'
```

What went wrong:

- `find / -name pdflatex` was used as the **primary** location strategy. `which pdflatex` was a fallback, not the primary.
- `2>/dev/null` silenced the errors but not the filesystem load. The traversal still happened.
- `head -5` is useless — the walk does not stop when `head` closes its read side unless the shell propagates SIGPIPE cleanly, and by the time it does the full traversal has already started.
- `source /etc/profile` was a guess — the agent was trying to "fix the environment" to make `which` work, which means it did not understand that `which` already works as long as `PATH` is set; the problem was that the agent was running in a non-interactive SSH context where `PATH` did not include the module-loaded texlive bin dir. The right fix was `bash -lc` + `module load texlive`, not `find`.

Correct refactor for that exact task:

```bash
ssh spartan 'bash -lc "module load texlive 2>/dev/null; command -v pdflatex"'
```

One line, zero filesystem traversal, uses the canonical module path.

## Fleet escalation

If an HPC admin complains about any fleet agent's behavior:

1. **Stop the offending agent immediately** (tmux kill or `scitex-agent-container stop`).
2. **Post to `#escalation`** with the admin's exact message, the offending command, and the host.
3. **Patch the skill (this one) with the specific anti-pattern** so the fleet never repeats it.
4. **Respond to the admin** within one business day, acknowledging the issue + naming the preventive measure.
5. **Verify with `ps -ef | grep $USER` on the affected host** that no similar process is still running.

The 2026-04-14 incident was handled by ywatanabe replying directly to Sean; the preventive measure is this skill. Future incidents: patch first, reply second, verify third.

## Related

- `spartan-hpc-startup-pattern.md` — Lmod module chain, `bash -lc` wrap, login-vs-compute policy, partition cheatsheet
- `connectivity-probe.md` — non-interactive SSH `bash -lc` wrap pattern that the `which pdflatex` fix relies on
- `orochi-bastion-mesh` skill — how to run persistent services on HPC via long-walltime sbatch, not on login1
- memory `project_spartan_login_node.md` — login1 is controller-only
- ywatanabe email exchange with Sean Crosby, 2026-04-14 (relayed via msg #10971)

## Change log

- **2026-04-14 (initial)**: Drafted immediately after the Sean Crosby email (msg #10971). Centers the `find /` anti-pattern but generalizes to filesystem walks, inode management, SLURM etiquette, login-node policy, storage hygiene, network etiquette, and shell-level guardrails. Includes the exact refactor for the offending `find / -name pdflatex` command. Author: mamba-skill-manager (knowledge-manager lane).
