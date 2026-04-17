# Example Agent Definitions

Reference YAML templates for Orochi fleet agents. These are **not** used
directly by `scitex-orochi launch` -- operational configs live under
`~/.scitex/orochi/` in the canonical layout (see
`~/.scitex/orochi/README.md`, dotfiles commit `68bd1592`):

```
~/.scitex/orochi/
├── shared/agents/<name>/<name>.yaml     # shared template (hostname-substituted)
└── <host>/agents/<name>/<name>.yaml     # host-specific concrete yaml
```

## Usage

Copy an example into the appropriate canonical location and customize:

```bash
# Shared template — behaves identically on every host, only ${HOSTNAME}
# substitutions differ.
mkdir -p ~/.scitex/orochi/shared/agents/head-myrole
cp examples/agents/head-general.yaml \
   ~/.scitex/orochi/shared/agents/head-myrole/head-myrole.yaml
# Edit host, model, channels, etc.
scitex-orochi launch head myrole
```

For a host-specific agent (hardcoded paths, local-only tools):

```bash
HOST=$(hostname -s)
mkdir -p ~/.scitex/orochi/$HOST/agents/head-myrole
cp examples/agents/head-general.yaml \
   ~/.scitex/orochi/$HOST/agents/head-myrole/head-myrole.yaml
```

## Files

| File | Role | Description |
|------|------|-------------|
| `master.yaml` | master | Orchestrator -- delegates to heads |
| `head-general.yaml` | head | General-purpose development agent |
| `head-research.yaml` | head | Research/GPU workloads |
| `head-deploy.yaml` | head | Deployment operations |
| `head-mba.yaml` | head | MacBook Air agent |
| `telegrammer.yaml` | telegram | Telegram bridge agent |

## Directory Layout

For production, use the dir-per-agent layout with a `CLAUDE.md` alongside:

```
~/.scitex/orochi/shared/agents/
  head-myrole/
    head-myrole.yaml
    src_CLAUDE.md          # copied to {workdir}/CLAUDE.md at launch
    src_mcp.json           # copied to {workdir}/.mcp.json at launch
```

At launch time, sac creates the per-agent workdir at
`~/.scitex/orochi/runtime/workspaces/<effective-agent-id>/` (gitignored,
regenerated per host).
