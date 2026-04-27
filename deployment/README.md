# `deployment/`

All deployment artifacts (templates, container builds, host
provisioning) live here. Imperative drivers (the Makefile, install
scripts) live elsewhere — this directory is mostly **declarative**.

## Layout

```
deployment/
├── docker/                    # Hub container build + compose stacks
│   ├── Dockerfile
│   ├── docker-compose.dev.yml
│   ├── docker-compose.stable.yml
│   └── entrypoint.sh
│
├── fleet/                     # Per-fleet runtime helpers (tmux, ssh, agent respawn)
│   ├── agent-respawn.sh
│   ├── cloudflared-watchdog.sh
│   ├── tmux-unstick*.sh
│   └── launchd/               # plist templates installed by fleet helpers
│
└── host-setup/                # Host-level provisioning (probes, watchdogs, cron)
    ├── launchd/               # macOS LaunchAgent + LaunchDaemon plist templates
    ├── systemd/               # Linux systemd unit + timer templates
    ├── orochi-cron/           # cron config seeds
    └── logrotate/             # logrotate fragments
```

## Convention: template ↔ installer pairing

Each plist / unit template in `deployment/host-setup/` has a matching
`install-*.sh` under `scripts/client/`. The installer renders any
`__USERNAME__` / `__HOME__` placeholders, copies the file to the
right system path, and bootstraps it via `launchctl` or `systemctl`.

Examples:

| Template | Installer |
| --- | --- |
| `deployment/host-setup/launchd/com.scitex.fleet-host-liveness-probe.plist` | `scripts/client/install-fleet-host-liveness-probe.sh` |
| `deployment/host-setup/launchd/com.scitex.chrome-codesign-watchdog.plist` | `scripts/client/install-chrome-codesign-watchdog.sh` |
| `deployment/host-setup/launchd/com.scitex.hungry-signal.plist` | `scripts/client/install-hungry-signal.sh` |
| `deployment/host-setup/launchd/com.scitex.orochi-cron.plist` | `scripts/client/install-orochi-cron.sh` |
| `deployment/host-setup/launchd/com.ywatanabe.colima-caffeinate.plist` (Daemon) | `scripts/client/install-colima-caffeinate.sh` |

Every installer supports `--dry-run` and `--uninstall`.

## Hub deploy (Tier 1 / Tier 2 / Tier 3)

Driven by `Makefile` recipes in the repo root, not by ad-hoc shell
scripts:

| Tier | Recipe | What it does | Use when |
| --- | --- | --- | --- |
| 1 | `docker cp` of changed files (no Make recipe; manual hot-cp) | Drop static / template files into the running container | CSS / template-only fixes |
| 2 | `make prod-deploy` | git push → ssh PROD\_HOST → docker compose up -d --build → CF cache purge | Routine code change |
| 3 | `make prod-rebuild` (manual `--no-cache` extension) | Full image rebuild from scratch | Dependency / pyproject change |

See `~/.scitex/orochi/shared/skills/scitex-orochi-private/`:

- `infra-deploy-workflow.md` — when to pick which tier
- `infra-hub-stability.md` — failure modes (ping/pong layers, colima VM suspension, reconnect storms)
- `infra-hub-deploy-hotfix.md` — recovery recipes
- `infra-hub-docker-disk-full.md` — disk-pressure recovery on mba

## See also

- Top-level `Makefile` — `make help` lists every prod / host recipe.
- `scripts/server/bump-version.sh` — release tagging.
- `~/.scitex/orochi/shared/skills/scitex-orochi-private/` — the
  operational skill index that backs this directory.
