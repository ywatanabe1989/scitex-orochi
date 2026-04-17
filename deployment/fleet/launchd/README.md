# `deployment/fleet/launchd/` — legacy tmux-unstick plist only

**Orchestration has moved.** The per-agent fleet-start plist template and
its `install-launchd.sh` installer that used to live here pointed at the
pre-restructure flat `~/.dotfiles/src/.scitex/orochi/agents/<name>/` path,
which no longer exists. They were retired on 2026-04-18.

## What lives here now

| File | Purpose |
|---|---|
| `com.scitex.orochi.tmux-unstick.plist` | Fleet-health unstick poller (60s interval, Phase 1 MVP). Orthogonal to fleet-start — keep using it. |

## Where canonical macOS orchestration lives

`~/.dotfiles/src/.scitex/orochi/shared/scripts/launchd/` — two templates,
substituted per host by `bootstrap-host.sh`:

- `com.scitex.orochi.fleet-start.plist.template` → runs `sac start --all`
  at login. Parallel to `orochi-fleet-start.service` on Linux hosts.
- `com.scitex.orochi.agent-meta-push.plist.template` → 30 s heartbeat
  pusher. Parallel to `orochi-agent-meta-push.{service,timer}`.

Install path: run `~/.dotfiles/src/.scitex/orochi/shared/scripts/bootstrap-host.sh`.
