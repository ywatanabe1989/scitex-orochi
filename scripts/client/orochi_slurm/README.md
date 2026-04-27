# `shared/scripts/orochi_slurm/` — SLURM plugin hooks for sac's SlurmRuntime

**Purpose:** orochi-specific shell fragments that plug into sac's generic
SlurmRuntime via the hook ports declared in each agent's
`spec.orochi_slurm.hooks`. sac knows nothing about orochi or Spartan; these
scripts inject the HPC environment and fleet identity.

## Hook contract (from sac's side)

Hooks are **sourced** (not exec'd) by the sbatch wrapper on the compute
node. The following env vars are set before each hook is sourced:

| Var | Meaning |
|---|---|
| `SAC_AGENT_ID` | Effective agent id, e.g. `head-spartan` |
| `SAC_JOB_ID` | `$SLURM_JOB_ID` (unset during `pre_submit`) |
| `SAC_WORKDIR` | Agent workspace path |
| `SAC_LOG_FILE` | `<logs_dir>/<jobid>.out` |
| `SAC_PHASE` | `pre_submit` / `pre_agent` / `walltime_signal` / `post_agent` / `attach` |

Any env vars the hook `export`s persist into the agent's process — this
is how `pre_agent` injects `LD_LIBRARY_PATH`, `SCITEX_OROCHI_*`, etc.

## Files

| File | Phase | Purpose |
|---|---|---|
| `spartan-pre-agent.sh` | `pre_agent` | Lmod module loads (GCCcore, Python/3.11.3, nodejs/20), LD_LIBRARY_PATH export, orochi env vars (SCITEX_OROCHI_AGENT, _CHANNELS), claude PATH + auto-update disable |
| `walltime-notify.sh` | `walltime_signal` | Best-effort POST to orochi hub `/api/fleet/walltime-warn/` one hour before SLURM walltime, so the dashboard surfaces the impending auto-resubmit |

## Agent YAML wiring

Host-override `<host>/agents/head/head.yaml` on spartan declares:

```yaml
apiVersion: scitex-agent-container/v2
kind: Agent
metadata:
  name: head
  labels: { role: head, orochi_machine: ${HOSTNAME} }
spec:
  orochi_runtime: orochi_slurm
  orochi_model: opus[1m]
  orochi_slurm:
    partition: sapphire
    time_limit: 7-00:00:00
    cpus_per_task: 2
    mem: 4G
    signal: B:USR1@3600
    auto_resubmit: true
    logs_dir: ~/orochi_slurm_logs
    hooks:
      pre_agent: ~/.scitex/orochi/shared/scripts/orochi_slurm/spartan-pre-agent.sh
      walltime_signal: ~/.scitex/orochi/shared/scripts/orochi_slurm/walltime-notify.sh
  claude:
    flags:
      - --dangerously-skip-permissions
      - "--dangerously-load-development-channels server:scitex-orochi"
```

## Testing a hook locally

```bash
# Render sac's sbatch wrapper to a file and inspect the rendered hooks:
sac render-sbatch head > /tmp/head.sbatch
grep -A 10 'Hook: pre_agent' /tmp/head.sbatch

# Dry-source the pre_agent hook with fake SAC_* env:
SAC_AGENT_ID=head-spartan SAC_JOB_ID=dry SAC_WORKDIR=~ SAC_LOG_FILE=/tmp/dry.log \
SAC_PHASE=pre_agent source ~/.scitex/orochi/shared/scripts/orochi_slurm/spartan-pre-agent.sh
```

## Failure mode

Hooks run under `set -uo pipefail` in the wrapper but are `source`d, so a
hook failure aborts the whole wrapper before the agent spawns. Keep hooks
defensive: guards around `command -v`, `[[ -d ... ]]` etc. rather than
bare assumptions about the HPC environment.
