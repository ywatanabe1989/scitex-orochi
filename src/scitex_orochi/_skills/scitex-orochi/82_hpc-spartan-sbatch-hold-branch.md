---
name: orochi-spartan-hpc-sbatch-hold-branch
description: Canonical hardened sbatch wrapper template for Spartan head-agent jobs — hold-branch discipline, set -euo pipefail, while-tmux-has-session loop, and exit-1-on-session-death. Codified from todo#425 (2026-04-14): three out of four head-spartan submissions exited COMPLETED in 16 s due to a missing hold branch. (Part 3 — split from 66_hpc-spartan-startup-pattern-extras.md.)
---

> Part 3 of the Spartan HPC startup series. See [`29_hpc-spartan-startup-pattern.md`](29_hpc-spartan-startup-pattern.md) for the orchestrator/overview and [`66_hpc-spartan-startup-pattern-extras.md`](66_hpc-spartan-startup-pattern-extras.md) for non-interactive SSH trap, bash-startup latency, login/compute policy, and common mistakes.

## Sbatch wrapper hold-branch discipline

A Spartan head-agent typically lives inside an sbatch job so the controller survives a login-node logout. The wrapper script is the bridge between SLURM and the tmux-hosted Claude Code process. **The hold branch is where this bridge most often fails**, and the failure mode is subtle because SLURM marks it `COMPLETED` instead of `FAILED`.

### The anti-pattern

```bash
#!/bin/bash
#SBATCH --time=7-00:00:00
set -e                                    # ❌ not enough — missing -u, -o pipefail
tmux new-session -d -s head-spartan "..."  # returns immediately (-d = detached)
for i in 1 2 3; do                         # prompt-dismissal loop
  sleep 2
  # ...
done
echo "=== final pane ==="; tmux capture-pane -p | tail -20
echo "=== processes ==="; pgrep -af claude
                                           # ❌ script hits EOF and exits 0
                                           # ❌ SLURM marks cgroup COMPLETED, reaps tmux+claude
```

Observed empirically on 2026-04-14 (todo#425): three head-spartan jobs (`23934176`, `23936232`, `23936277`) all COMPLETED in ~16 s each. The bug wasted 3 SLURM submissions before the 4th attempt (`23936571`) held the allocation by accident. During a real 5 h quota outage this could burn the retry budget before the fleet stabilizes.

**Root cause**: `tmux new-session -d` is detached and returns immediately. The post-spawn diagnostic block runs synchronously (prompt-dismissal, pane capture, process list), and then control falls through to the end of the script. Without an explicit hold branch, `bash` hits EOF and exits `0`, SLURM interprets the zero exit as success, and the cgroup is reaped — killing tmux and the Claude session along with it.

### The canonical hardened template

```bash
#!/bin/bash
#SBATCH --partition=sapphire
#SBATCH --time=7-00:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --job-name=head-spartan
#SBATCH --output=/home/ywatanabe/slurm_logs/head_spartan_%j.log

set -euo pipefail   # fail hard, fail fast, catch pipeline errors
set -x              # trace every executed command into #SBATCH --output

mkdir -p /home/ywatanabe/slurm_logs
echo "sbatch wrapper start: job=${SLURM_JOB_ID:-manual} host=$(hostname) ts=$(date -u +%FT%TZ)"

# Module environment — see the Lmod sections above for why this is mandatory
module load GCCcore/11.3.0 Python/3.11.3

# Persistent tmux socket under $HOME so SLURM cgroup boundaries don't orphan it
export TMUX_TMPDIR="$HOME/.tmux-sockets"
mkdir -p "$TMUX_TMPDIR"

# Clean slate: kill any stale session from a previous allocation
tmux kill-session -t head-spartan 2>/dev/null || true

# Spawn the Claude Code session detached
tmux new-session -d -s head-spartan \
  "exec $HOME/.npm-global/bin/claude \
    --model opus[1m] \
    --dangerously-skip-permissions \
    --dangerously-load-development-channels server:scitex-orochi \
    --add-dir $HOME/proj/scitex-agent-container/src/scitex_agent_container/_skills/ \
    --add-dir $HOME/proj/scitex-orochi/src/scitex_orochi/_skills/ \
    --add-dir $HOME/.scitex/orochi/skills/"

# Post-spawn: auto-dismiss boot-time prompts
# (dev-channels banner, resume-from-summary, press-enter, etc.)
for i in 1 2 3 4 5 6 7 8; do
    sleep 2
    PANE=$(tmux capture-pane -t head-spartan -p 2>/dev/null | tail -40)
    if echo "$PANE" | grep -q "I am using this for local development"; then
        tmux send-keys -t head-spartan "1"; sleep 0.3; tmux send-keys -t head-spartan C-m
        continue
    fi
    if echo "$PANE" | grep -q "Resume from summary"; then
        tmux send-keys -t head-spartan Enter
        continue
    fi
    if echo "$PANE" | grep -qE '^\s*❯\s*$' && echo "$PANE" | grep -q "bypass permissions on"; then
        break
    fi
done

echo "=== final pane ==="
tmux capture-pane -t head-spartan -p | tail -20
echo "=== processes ==="
pgrep -af claude | grep -v pgrep | head -5

# THE HOLD BRANCH — unconditional, foreground, tied to tmux session lifetime.
# While the tmux session is alive the while loop blocks; when the session
# dies (tmux kill-session, OOM, claude crash, SIGTERM) the loop exits and
# the script exits non-zero so SLURM marks the job FAILED, giving any
# watchdog (launchd, systemd, human) a chance to re-submit.
while tmux has-session -t head-spartan 2>/dev/null; do
    sleep 60
done
echo "head-spartan tmux session gone at $(date -u +%FT%TZ), exiting 1" >&2
exit 1
```

### Why each guard matters

| Guard | Without it | Motivation |
|---|---|---|
| `set -e` | Silent errors in multi-command lines | Any single non-zero command kills the wrapper immediately instead of limping on |
| `set -u` | Undefined variables expand to empty, hiding typos | `${SLURM_JOB_ID}` typo falls through to `""` and logs land in the wrong file |
| `set -o pipefail` | `cmd \| tee` returns 0 even if `cmd` failed | Critical for the `tmux capture-pane \| grep` chains |
| `set -x` | Post-mortem is "look at the log and guess" | Every executed line is echoed to `#SBATCH --output`, short-exit is diagnosable |
| `while tmux has-session; sleep 60; done` | Script falls off EOF, exit 0, SLURM reaps cgroup | Ties the SLURM allocation lifetime to the tmux session, not to the script runtime |
| `exit 1` on session-gone | SLURM marks COMPLETED, watchdog assumes success | Non-zero exit surfaces the real state to SLURM + watchdog |

### Anti-patterns to avoid

- **`exec sleep 604800`** — works, but if the tmux session dies externally, the script keeps sleeping for 7 days holding the allocation with a dead agent inside. The `while tmux has-session` pattern is preferred because it self-exits on session death.
- **Conditional hold** — any `if ... then sleep ... fi` where the `if` can be false is a bug waiting to happen. The hold must be unconditional.
- **Hold on PID** — `wait $TMUX_PID` doesn't work because `tmux new-session -d` returns immediately; there's no long-lived PID to wait on. Hold on session name, not PID.
- **Script-level `sleep infinity` with no session check** — never self-exits, requires `scancel` for every allocation swap.
- **Multiple wrappers in the same home directory with the same intent** — pick one canonical script and symlink or `exec` to it. If a fragile variant must be preserved for forensic, rename it `.deprecated.bak-<date>` and leave a gate stub at the original name that `echo DEPRECATED >&2; exit 1`. Todo#425's `head_spartan_restart2.sh` was retired this way on 2026-04-14.

### Regression test

After modifying the wrapper, verify with a 5-minute throwaway sbatch:

```bash
sbatch --time=5:00 --cpus-per-task=1 --mem=1G \
       --job-name=head-spartan-regression-test \
       --output=/home/ywatanabe/slurm_logs/regtest_%j.log \
       <path-to-hardened-wrapper.sh>
squeue -u $USER   # should show R or PD
# wait until completion, then:
grep -c "^+ " ~/slurm_logs/regtest_<JOB_ID>.log  # set -x trace lines, expect > 10
grep "hold branch" ~/slurm_logs/regtest_<JOB_ID>.log
sacct -j <JOB_ID> --format=JobID,State,ExitCode  # expect COMPLETED or FAILED with exit 1
```

For a deliberately-broken variant (to verify `set -euo pipefail` catches it), inject a `false` before the hold branch and confirm the wrapper exits non-zero with the failing line visible in the `set -x` trace.

## Related

- memory `project_spartan_login_node.md` — login1 controller-only rule
- `agent-autostart.md` §"Spartan (HPC login node)" — tmux-based startup pattern
- `convention-connectivity-probe.md` — `bash -lc` wrap, cross-OS semantics, compound escalation
- `resource-management.md` (scitex-resource) — the future unified SLURM acquisition API
- scitex-python / scitex-agent-container commit `6900afdf` (2026-04-13): `fix(spartan): export LD_LIBRARY_PATH for Python 3.11 shared libs`
- todo#425 — sbatch head-spartan wrapper: hold branch fragile; this section is the canonical fix

## Change log

- **2026-04-14**: Initial capture. Codifies the `set -euo pipefail` + `set -x` + `while tmux has-session; sleep 60; done` + `exit 1` pattern. Trigger: todo#425 (3 of 4 head-spartan submissions on 2026-04-14 exited COMPLETED in 16 s, jobs 23934176 / 23936232 / 23936277). Author: head-spartan (instance B). Companion script hardening landed in `~/head_spartan_{sbatch,fresh,restart}.sh` on-host; `head_spartan_restart2.sh` retired to `.deprecated.bak-20260415` with a gate stub.
