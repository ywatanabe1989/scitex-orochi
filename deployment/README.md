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

## Cloudflare tunnels — canonical and standby

Two cloudflared connectors are registered with Cloudflare, but **only
one routes prod traffic at a time**. The split exists for failover, not
load-balancing — registering both for the same hostname would
half-route traffic to a backend the second connector can't reach.

| Tunnel ID | Host | Role | Service config |
| --- | --- | --- | --- |
| `c1fddc4d-13d9-4606-a2d9-ffeaa3e8c337` | **mba** (canonical prod) | Routes `scitex-lab.scitex-orochi.com → http://localhost:8559` (colima-bridged docker container `orochi-server-stable`). | LaunchDaemon `com.cloudflare.cloudflared` (homebrew). Lives at `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`. |
| `bc461e9d-e4fc-4c3d-addb-1f0ac5f2acaa` | **ywata-note-win** (standby) | Currently registered but **not** routing the dashboard hostname (`total_requests=0` since boot). Available to take over by adding the dashboard ingress in the CF dashboard and disabling the mba tunnel. | systemd-style autostart on WSL2; runs from `~/.local/bin/cloudflared tunnel run --token …`. |

`Makefile:100` hard-pins `PROD_HOST := mba` and assumes the canonical
tunnel above. If you need to fail over to ywata-note-win:

1. Cloudflare Zero Trust → Tunnels → `c1fddc4d` → pause / disable
   ingress to dashboard.
2. Same dashboard → `bc461e9d` → add public hostname
   `scitex-lab.scitex-orochi.com → http://localhost:8559`.
3. Update `Makefile:100` `PROD_HOST := ywata-note-win` (or pass
   `make PROD_HOST=ywata-note-win prod-deploy`).
4. `scripts/client/install-colima-caffeinate.sh` is a no-op on WSL2 —
   the failover host doesn't have the colima-suspend failure mode.

Probe the active connector:

```bash
curl -s http://127.0.0.1:20241/metrics | grep ^cloudflared_tunnel_total_requests
```

Non-zero = this tunnel is serving traffic; zero = standby.

**Do NOT register both tunnels for the same hostname.** Cloudflare
load-balances across all healthy connectors of a tunnel; if the
standby's backend is unreachable from its host, half the requests
return 502 even when the canonical container is healthy. (This was
the 2026-04-27 incident before the prod-host invariant was clarified.)

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
