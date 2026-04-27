# Example Agent Definitions

Reference YAML templates for Orochi fleet agents. These are **not** used
directly by `scitex-orochi launch` -- operational configs live in:

```
~/.scitex/orochi/agents/
```

## Usage

Copy an example to your user config directory and customize:

```bash
mkdir -p ~/.scitex/orochi/agents
cp examples/agents/head-general.yaml ~/.scitex/orochi/agents/head-myhost.yaml
# Edit host, model, channels, etc.
scitex-orochi launch head myhost
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
~/.scitex/orochi/agents/
  head-myhost/
    head-myhost.yaml
    CLAUDE.md
```
