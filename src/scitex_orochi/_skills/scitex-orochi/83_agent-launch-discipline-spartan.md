---
name: agent-launch-discipline-spartan
description: Spartan-specific preconditions for scitex-agent-container launch — module load chain, libpython availability, and fresh-host registry bypass. Codified from 2026-04-16 recovery incidents (todo#461).
---

# Agent Launch Discipline — Spartan (and Module-Based HPC)

Before invoking `scitex-agent-container` (sac) on Spartan or any Lmod cluster, two preconditions **must** be satisfied. Missing either causes a silent failure that looks like a launch success but leaves the agent un-startable.

## Precondition 1 — libpython availability

Spartan's default shell has no Python in `$PATH` and no `libpython*.so` in `$LD_LIBRARY_PATH`. `sac` requires both. Non-interactive SSH sessions (the normal fleet-watch / respawn path) do **not** source Lmod's init, so `module` may not even exist.

**Canonical fix**: wrap every sac invocation in a `bash -lc` with the module chain and venv activation:

```bash
ssh spartan.hpc.unimelb.edu.au bash -lc "
    module load GCCcore/11.3.0 Python/3.11.3 &&
    source ~/proj/neurovista/.env-3.10/bin/activate &&
    scitex-agent-container start <agent-name>
"
```

Or inline on the Spartan login node:

```bash
module load GCCcore/11.3.0 Python/3.11.3
source ~/proj/neurovista/.env-3.10/bin/activate
scitex-agent-container start <agent-name>
```

Key points:
- `bash -lc` (login shell flag `-l`) sources `/etc/profile` and Lmod init.
- The venv activate supplies the correct `python3` + `libpython` to `sac`.
- Without the `module load` step, `sac` imports will fail even if `sac` itself is on `$PATH`.

## Precondition 2 — registry entry (fresh host recovery)

`scitex-agent-container start <name>` looks up the agent yaml in:

1. `~/.scitex/agent-container/agents/<name>.yaml`
2. `~/.scitex/orochi/shared/agents/<name>/<name>.yaml`  *(built-in fallback, sac ≥ 0.x)*
3. `~/.dotfiles/src/.scitex/orochi/agents/<name>/<name>.yaml`  *(built-in fallback)*
4. Dirs listed in `$SCITEX_AGENT_CONTAINER_YAML_DIRS`

On a fresh Spartan node only paths 2–3 may exist (the agents/ dir is empty until `sac` has registered an agent). **sac automatically falls back** to these paths since [todo#461 fix]. If you're on an older sac version that doesn't have the fallback, pass the yaml path explicitly:

```bash
scitex-agent-container start \
  ~/.dotfiles/src/.scitex/orochi/agents/neurovista-spartan/neurovista-spartan.yaml
```

Or set the env var so sac extends its search scope:

```bash
export SCITEX_AGENT_CONTAINER_YAML_DIRS=~/.scitex/orochi/shared/agents:~/.dotfiles/src/.scitex/orochi/agents
scitex-agent-container start neurovista-spartan
```

## Combined one-liner for Spartan recovery

```bash
ssh spartan.hpc.unimelb.edu.au bash -lc "
    module load GCCcore/11.3.0 Python/3.11.3 &&
    source ~/proj/neurovista/.env-3.10/bin/activate &&
    export SCITEX_AGENT_CONTAINER_YAML_DIRS=~/.scitex/orochi/shared/agents:~/.dotfiles/src/.scitex/orochi/agents &&
    scitex-agent-container start neurovista-spartan
"
```

## Checklist before any Spartan agent launch

- [ ] Modules loaded: `module load GCCcore/11.3.0 Python/3.11.3`
- [ ] Python venv active: `source ~/proj/<project>/.env-3.10/bin/activate`
- [ ] Agent yaml reachable: `sac resolve <name>` returns a path (not an error)
- [ ] tmux session for agent confirmed: `tmux ls | grep <agent-name>`

## Failure signatures

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: libpython3.11.so.1.0` | libpython not in `LD_LIBRARY_PATH` | `module load GCCcore/11.3.0 Python/3.11.3` first |
| `command not found: module` | Non-interactive shell, Lmod not init'd | Use `bash -lc` or source Lmod init manually |
| `Agent 'X' not found. Searched: ~/.scitex/agent-container/agents/` | Empty sac registry, yaml only in orochi tree | Pass yaml path or set `SCITEX_AGENT_CONTAINER_YAML_DIRS` |
| Agent starts but never joins channels | MCP `.mcp.json` not updated (todo#453) | Copy fresh `src_mcp.json` to workspace before launch |
