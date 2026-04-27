# `shared/scripts/systemd/` — canonical on-host orchestration

**Purpose:** one source of truth for how Orochi fleet agents are launched and
kept orochi_alive on every host. Templates here are host-agnostic; `bootstrap-host.sh`
substitutes per-host details and installs them under `~/.config/systemd/user/`.

## Templates

| File | Installs as | Purpose |
|---|---|---|
| `orochi-fleet-start.service.template` | `orochi-fleet-start.service` | On-boot starter: runs `sac start --all`, which walks `<host>/agents/ > shared/agents/` and applies scheduling.mode rules (per-host / singleton + preferred-host). Replaces the per-agent `orochi-head-<host>.service` units. |
| `orochi-agent-meta-push.service.template` + `.timer.template` | `orochi-agent-meta-push.{service,timer}` | Posts agent metadata to the hub every 30s so the dashboard keeps a live view. Canonical heartbeat pusher. |

## Substitution tokens

bootstrap-host.sh renders these into the deployed unit files:

| Token | Meaning | Example |
|---|---|---|
| `@SAC@` | Absolute path to the `sac` CLI | `/home/ywatanabe/.venv-3.11/bin/sac` |
| `@AGENT_META@` | Absolute path to `collect_agent_metadata.py` | `/home/ywatanabe/.scitex/orochi/shared/scripts/collect_agent_metadata.py` |
| `@CANONICAL_HOST@` | Fleet label from `resolve-orochi_hostname` | `mba` / `nas` / `spartan` / `ywata-note-win` |

## Environment file

Both units read `~/.config/systemd/user/orochi.env` (optional; the `-` prefix
on `EnvironmentFile=` makes it non-fatal if absent). Bootstrap writes the
file with `SCITEX_OROCHI_TOKEN=<token>` after discovering the value from the
user's shell environment.

Sensitive — gitignored, never committed. If the token rotates, re-run
bootstrap to refresh the file.

## Retiring old per-agent units

The pre-2026-04-18 pattern had `orochi-head-<host>.service`,
`orochi-mamba-healer-<host>.service`, etc. — one unit per agent, each with a
hardcoded YAML path. After the `shared/agents/` restructure those YAML paths
no longer exist, so the units are dead.

Bootstrap's cleanup loop (2026-04-18+) disables + removes any user-unit whose
ExecStart references `~/.dotfiles/src/.scitex/orochi/agents/` (the pre-shared
flat path). New canonical unit is `orochi-fleet-start.service`.

## macOS (mba)

These templates are systemd-specific; bootstrap emits launchd `.plist`
equivalents under `~/Library/LaunchAgents/` on darwin hosts. See
`bootstrap-host.sh` section `-- 4. Orchestration install`.
