# `shared/scripts/launchd/` — canonical macOS orchestration

**Purpose:** launchd equivalents of `shared/scripts/systemd/` for mba and any
other macOS host in the fleet. One source of truth; `bootstrap-host.sh`
substitutes per-host details and installs the result under
`~/Library/LaunchAgents/`.

## Templates

| File | Installs as | Purpose |
|---|---|---|
| `com.scitex.orochi.fleet-start.plist.template` | `com.scitex.orochi.fleet-start.plist` | On-login starter: runs `sac start --all`. Parallel to `orochi-fleet-start.service` on Linux. |
| `com.scitex.orochi.agent-meta-push.plist.template` | `com.scitex.orochi.agent-meta-push.plist` | Fires every 30s (StartInterval=30) to POST agent metadata to the hub. Parallel to `orochi-agent-meta-push.{service,timer}`. |

## Substitution tokens

| Token | Meaning | Example |
|---|---|---|
| `@SAC@` | Absolute path to the `sac` CLI | `/Users/ywatanabe/.venv/bin/scitex-agent-container` |
| `@AGENT_META@` | Absolute path to `collect_agent_metadata.py` | `/Users/ywatanabe/.scitex/orochi/shared/scripts/collect_agent_metadata.py` |
| `@CANONICAL_HOST@` | Fleet label | `mba` |
| `@HOME@` | Absolute `$HOME` | `/Users/ywatanabe` |

## Environment

launchd does not source `~/.bashrc` or `~/.bash_profile`, so all env the
agents need must be set explicitly — either in the plist's
`EnvironmentVariables` block or in `sac`'s own runtime (agent YAML + the
pre_agent SLURM hook on spartan). The agent-meta pusher reads
`SCITEX_OROCHI_TOKEN` from the running shell that loaded it; re-running
bootstrap after token rotation is the safe refresh path.

## Loading and unloading

Bootstrap runs:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<plist>
launchctl enable gui/$(id -u)/<Label>
```

Manual unload:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/<plist>
```

## Retiring pre-2026-04-18 per-agent plists

The pre-restructure pattern had `com.scitex.orochi.head-mba.plist`,
`com.scitex.orochi.mamba-healer-mba.plist`, etc. — one plist per agent,
each with a hardcoded YAML path under the dead
`~/.dotfiles/src/.scitex/orochi/agents/` flat layout. After the shared/
restructure those YAML paths no longer exist.

Bootstrap's cleanup loop (2026-04-18+) bootsouts and removes any user
LaunchAgent whose `ProgramArguments` references the pre-shared flat
path. The canonical plist is `com.scitex.orochi.fleet-start.plist`.
