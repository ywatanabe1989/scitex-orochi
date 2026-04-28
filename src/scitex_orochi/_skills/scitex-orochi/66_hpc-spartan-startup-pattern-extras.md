---
name: orochi-spartan-hpc-startup-pattern-part-2
description: Canonical startup pattern for Spartan (and other Lmod/module-based HPC clusters) — module load chain, LD_LIBRARY_PATH hardening for non-interactive SSH, login-node vs compute-node divergence, and avoiding multi-second bash-startup latency. Codified from 2026-04-13 head-<host> fixes (todo#307). (Part 2 of 2 — split from 29_hpc-spartan-startup-pattern.md.)
---

> Part 2 of 2. See [`29_hpc-spartan-startup-pattern.md`](29_hpc-spartan-startup-pattern.md) for the orchestrator/overview.
## The non-interactive SSH trap

Everything in `~/.bashrc` that depends on the `module` function is invisible to `ssh spartan 'cmd'` because the non-interactive shell does not source Lmod's init. Symptoms:

- `ssh spartan 'which python'` → `/usr/bin/python` (system 2.7), not the module Python.
- `ssh spartan 'pip3.11 install foo'` → `libpython3.11.so.1.0: cannot open shared object file`.
- `ssh spartan 'squeue -u $USER'` → `squeue: command not found` if `slurm/` module isn't pre-loaded.
- Fleet connectivity probes that wrap in `bash -lc` (from `convention-connectivity-probe.md`) **do** work for the Lmod parts, but still fail if `spartan_load_modules` hasn't been called in the login shell session.

**Defenses**, in order of preference:

1. **Export LD_LIBRARY_PATH unconditionally** in the dotfiles snippet (done above for the Python 3.11 case). Do the same for any other library a remote probe will depend on.
2. **Call `spartan_load_modules` from `~/.bash_profile`** (login shell) so `bash -lc` wrapping sees the full module environment. Do **not** call it from `~/.bashrc` alone — that fires on every non-interactive SSH invocation and balloons startup latency.
3. **Absolute paths in probes** — `command ssh spartan '/apps/slurm/latest/bin/squeue ...'` sidesteps PATH entirely. Use for health probes where latency matters.
4. **Pass-through env**: `ssh -o SendEnv=LD_LIBRARY_PATH spartan ...` only works if Spartan's `sshd_config` `AcceptEnv` whitelists it, which is rarely the case. Don't rely on this.

## Bash-startup latency budget

Interactive bash startup on Spartan login1 should be **under 500 ms**; it will creep to 2–3 s if every non-interactive SSH invocation re-runs `spartan_load_modules`. Symptoms: probe latency spikes, fleet_watch.sh cycles drift, `ssh spartan 'true'` takes visibly long.

Two-layer fix (applied 2026-04-13 during mamba-mode spike):

1. **Gate module loading on "is this actually an interactive session?"** — the snippet above guards with `if [ -z "$CLAUDE_ID" ]` and `if_host "spartan-login"` so agent sessions and remote probes skip the full chain. Agents get only the unconditional `LD_LIBRARY_PATH` export, not the ~2 s Lmod work.
2. **Separate login vs compute setup** — `spartan_setup_login` runs the full chain on login1; `spartan_setup_gpgpu` runs a subset on GPU compute nodes. Non-interactive probes trigger neither.

After the fix: `time ssh spartan 'bash -lc "true"'` should be well under 1 s; `time ssh spartan 'true'` (no `-lc`) should be near the TCP round-trip only.

## Login node vs compute node policy

Hard-coded fleet rule (memory: `project_spartan_login_node.md`):

- **login1 is controller-only.** Agents on login1 may plan, communicate, orchestrate, and call `salloc`/`sbatch` — but they must not run model training, inference, notebooks, or anything that holds CPU/GPU for more than a few seconds.
- **Compute nodes are where work happens.** Acquire with `salloc --time=HH:MM:SS --partition=<name> --gres=gpu:<n>` and attach with `srun --jobid=$SLURM_JOB_ID --pty bash`. The Claude Code process itself becomes the allocation holder (see `#7935` thread in `#operator` 2026-04-13 for the reasoning).
- **Always set `--time`.** If the agent crashes, the allocation auto-releases at the wall-clock deadline.
- **Never autostart agent workloads on login1 via systemd**. Use the `.bash_profile` + tmux pattern from `agent-autostart.md` §"Spartan (HPC login node)" instead — starts the agent *when the operator ssh-es in*, which is the correct semantic on a shared login node.

## Partition cheatsheet (Spartan, 2026-04-13)

| Partition | Use | Notes |
|---|---|---|
| `physical` | General CPU work | Default for non-GPU jobs. |
| `sapphire` | GPU A100 | Preferred for training runs. head-<host> reports availability here. |
| `gpu-a100` | GPU A100 (legacy name) | worker-todo-manager bridges jobs here when `sapphire` is queued. |

Modules to load inside an `salloc` on a compute node: usually a subset of the login-node chain. For Python 3.11 + CUDA jobs, load `GCCcore/11.3.0`, `Python/3.11.3`, `CUDA/<version>` explicitly, and `module list` in the job script to log which versions were actually picked up — Lmod substitutions silently move the toolchain under your feet.

## Common mistakes checklist

Verify before shipping any Spartan-bound code or probe:

- [ ] Hostname guard wraps any Spartan-only env export so non-HPC hosts don't execute it.
- [ ] Directory existence check guards any hardcoded `/apps/easybuild-*` path.
- [ ] Non-interactive path: `ssh spartan 'pip3.11 --version'` works **without** `bash -lc`.
- [ ] Interactive path: `time ssh spartan 'bash -lc "true"'` is under 1 s after the fix.
- [ ] No module-load side effects on hosts where `$(hostname) != *spartan*`.
- [ ] `spartan_load_modules` is **not** called from every bash startup — only from login-shell entry points.
- [ ] Agent autostart on login1 uses `.bash_profile` + tmux, not systemd / launchd.
- [ ] Compute-heavy work runs inside `salloc`/`srun`, never bare on login1.
- [ ] `--time` is set on every `salloc`/`sbatch` so the allocation can self-release.
- [ ] Probe commands use absolute paths for `/apps/slurm/latest/bin/squeue` etc. when latency matters.

## Related

- memory `project_spartan_login_node.md` — login1 controller-only rule
- `agent-autostart.md` §"Spartan (HPC login node)" — tmux-based startup pattern
- `convention-connectivity-probe.md` — `bash -lc` wrap, cross-OS semantics, compound escalation
- `resource-management.md` (scitex-resource) — the future unified SLURM acquisition API
- scitex-python / scitex-agent-container commit `6900afdf` (2026-04-13): `fix(spartan): export LD_LIBRARY_PATH for Python 3.11 shared libs`

## Change log

- **2026-04-13**: Initial capture from head-<host> bash-load incident (2.73 s interactive startup), Python 3.11 shared-lib fix (commit 6900afdf), and reconstruction of the Lmod / hostname-guard / directory-guard pattern in `999_unimelb_spartan.src`. Trigger: worker-todo-manager dispatch msg#8829 (manba-mode), todo#307. Author: worker-skill-manager.
