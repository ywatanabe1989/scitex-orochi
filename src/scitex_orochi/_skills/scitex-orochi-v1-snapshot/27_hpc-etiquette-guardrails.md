---
name: orochi-hpc-etiquette-guardrails
description: Network etiquette, storage hygiene, shell-level guardrails (find/du wrappers), 2026-04-14 anti-patterns from the Sean Crosby incident, fleet escalation protocol, related skills, and change log. Sub-file of hpc-etiquette.md.
---

# HPC etiquette — network, storage, guardrails, escalation

> Sub-file of `hpc-etiquette.md`. See the orchestrator for context.

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

Every agent that runs shell commands on HPC should have these aliases available (source from a host-gated bash file, see `hpc-spartan-startup-pattern.md` for the hostname guard pattern):

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

The 2026-04-14 incident was handled by the operator replying directly to Sean; the preventive measure is this skill. Future incidents: patch first, reply second, verify third.

## Related

- `hpc-spartan-startup-pattern.md` — Lmod module chain, `bash -lc` wrap, login-vs-compute policy, partition cheatsheet
- `convention-connectivity-probe.md` — non-interactive SSH `bash -lc` wrap pattern that the `which pdflatex` fix relies on
- `orochi-bastion-mesh` skill — how to run persistent services on HPC via long-walltime sbatch, not on login1
- memory `project_spartan_login_node.md` — login1 is controller-only
- the operator email exchange with Sean Crosby, 2026-04-14 (relayed via msg #10971)

## Change log

- **2026-04-14 (initial)**: Drafted immediately after the Sean Crosby email (msg #10971). Centers the `find /` anti-pattern but generalizes to filesystem walks, inode management, SLURM etiquette, login-node policy, storage hygiene, network etiquette, and shell-level guardrails. Includes the exact refactor for the offending `find / -name pdflatex` command. Author: worker-skill-manager (knowledge-manager lane).
