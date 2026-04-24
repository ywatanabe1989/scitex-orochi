---
name: scitex-orochi-env-vars
description: Environment variables read by scitex-orochi at import / runtime. Complements 21_convention-env-vars.md with the full authoritative list.
---

# scitex-orochi — Environment Variables

Full list of `SCITEX_OROCHI_*` vars the source actually reads (plus a few
ecosystem / cross-package vars consumed read-only). For conventions see
`21_convention-env-vars.md`.

## Identity / routing

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_AGENT` | Agent slug for this process. | auto | string |
| `SCITEX_OROCHI_AGENT_META_VERSION` | Metadata schema version. | current | string |
| `SCITEX_OROCHI_AGENT_ROLE` | Role (`worker`/`caduceus`/`observer`). | `worker` | string |
| `SCITEX_OROCHI_HOSTNAME` | Advertised hostname. | host | string |
| `SCITEX_OROCHI_MACHINE` | Machine / fleet node name. | auto | string |
| `SCITEX_OROCHI_MODEL` | Model identifier for this agent. | `—` | string |
| `SCITEX_OROCHI_ICON` / `_EMOJI` / `_TEXT` | Avatar / display hints. | unset | string |
| `SCITEX_OROCHI_WORKSPACE` | Workspace key. | `default` | string |
| `SCITEX_OROCHI_PUSH_TS` | Last push timestamp marker. | auto | string |

## Hub / host / URL

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_URL` | Primary hub URL (HTTPS). | `—` | URL |
| `SCITEX_OROCHI_URL_HTTP` | HTTP fallback URL. | inherits | URL |
| `SCITEX_OROCHI_HOST` | Hub host. | inherits | string |
| `SCITEX_OROCHI_PORT` | Hub port. | `8000` | int |
| `SCITEX_OROCHI_HUB` | Hub name. | `—` | string |
| `SCITEX_OROCHI_HUB_URL` | Alt hub URL. | inherits | URL |
| `SCITEX_OROCHI_EXTERNAL_IP` | External IP for NAT traversal. | auto | string |
| `SCITEX_OROCHI_CORS_ORIGINS` | CORS allowlist. | inherits | string (CSV) |
| `SCITEX_OROCHI_SKIP_TLS_VERIFY` | Disable TLS cert verification (dev only). | `false` | bool |

## Auth / secrets

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_TOKEN` | Agent-level bearer token. | `—` | string (required) |
| `SCITEX_OROCHI_ADMIN_TOKEN` | Admin-level token for hub management. | `—` | string |
| `SCITEX_OROCHI_SCITEX_CLIENT_ID` | OAuth client ID for SciTeX SSO. | `—` | string |
| `SCITEX_OROCHI_SCITEX_SECRET` | OAuth client secret. | `—` | string |
| `SCITEX_OROCHI_SSO_URL` | SSO endpoint. | inherits | URL |

## Database / storage

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_DB` | Database DSN. | sqlite | string |
| `SCITEX_OROCHI_DB_PATH` | SQLite file path. | `~/.scitex/orochi/orochi.db` | path |
| `SCITEX_OROCHI_MEDIA_ROOT` | Media upload dir. | `~/.scitex/orochi/media` | path |
| `SCITEX_OROCHI_MEDIA_MAX_SIZE` | Max upload size (bytes). | `10485760` | int |
| `SCITEX_OROCHI_REPO_ROOT` | Local repo mirror root. | `~/.scitex/orochi/repos` | path |

## Dashboard / channels

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_DASHBOARD_PORT` | Dashboard HTTP port. | `8001` | int |
| `SCITEX_OROCHI_DASHBOARD_WS_UPSTREAM` | Dashboard WS upstream URL. | inherits | URL |
| `SCITEX_OROCHI_CHANNELS` | Comma-separated channels to join. | unset | string (CSV) |
| `SCITEX_OROCHI_CHANNELS_YAML` | YAML file listing channel definitions. | bundled | path |
| `SCITEX_OROCHI_CONFIG` | Top-level YAML config. | bundled | path |
| `SCITEX_OROCHI_GREETING_CHANNEL` | Channel for join-greeting. | `#general` | string |

## Telegram bridge

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED` | Opt-in: enable the Telegram bridge. | `false` | bool |
| `SCITEX_OROCHI_TELEGRAM_BOT_TOKEN` | Telegram bot token. | `—` | string |
| `SCITEX_OROCHI_TELEGRAM_CHAT_ID` | Default chat ID. | `—` | string |
| `SCITEX_OROCHI_TELEGRAM_CHANNEL` | Orochi channel bridged to Telegram. | `—` | string |
| `SCITEX_OROCHI_TELEGRAM_WEBHOOK_URL` | Public webhook URL for Telegram. | `—` | URL |
| `SCITEX_OROCHI_TELEGRAM_WEBHOOK_SECRET` | Webhook signing secret. | `—` | string |

## GitHub bridge

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_GITHUB_TOKEN` | GitHub PAT. | `—` | string |
| `SCITEX_OROCHI_GITHUB_REPO` | Primary repo (org/name). | `—` | string |
| `SCITEX_OROCHI_GITHUB_ISSUES_REPO` | Repo for issue mirroring. | inherits | string |
| `SCITEX_OROCHI_GITHUB_WEBHOOK_SECRET` | Webhook signing secret. | `—` | string |
| `SCITEX_OROCHI_GITHUB_WEBHOOK_CHANNEL` | Target channel for webhook events. | `#github` | string |

## Gitea bridge

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_GITEA_URL` | Gitea URL. | inherits | URL |
| `SCITEX_OROCHI_GITEA_TOKEN` | Gitea token. | `—` | string |

## Misc

| Variable | Purpose | Default | Type |
|---|---|---|---|
| `SCITEX_OROCHI_DISABLE` | Opt-out: disable orochi entirely. | `false` | bool |
| `SCITEX_OROCHI_NO_DEPRECATION` | Silence deprecation warnings. | `false` | bool |
| `SCITEX_OROCHI_MULTIPLEXER` | Multiplexer name (`screen`/`tmux`). | `screen` | string |
| `SCITEX_OROCHI_SHELL_SESSION` | Explicit shell-session ID. | auto | string |
| `SCITEX_OROCHI_CADUCEUS_HOST` | Caduceus-role host. | inherits | string |
| `SCITEX_OROCHI_CADUCEUS_NAME` | Caduceus-role display name. | auto | string |
| `SCITEX_OROCHI_VAPID_PUBLIC` | VAPID public key for web-push. | `—` | string |
| `SCITEX_OROCHI_CONTACT_PHONE_JA` | Japanese contact phone (escalation). | unset | string |

## Cross-package / ecosystem

| Variable | Owner | Purpose |
|---|---|---|
| `SCITEX_AGENT_LOCAL_HOSTS` | fleet | Local-host allowlist |
| `SCITEX_HUNGRY_DISABLED` | fleet | Disable the hungry-signal protocol |
| `SCITEX_ON_WSL` | ecosystem | WSL-detect flag |
| `SCITEX_TODO_REPO` | ecosystem | Repo for TODO-item mirroring |

## Feature flags

- **opt-out:** `SCITEX_OROCHI_DISABLE=true`, `SCITEX_HUNGRY_DISABLED=true`,
  `SCITEX_OROCHI_NO_DEPRECATION=true`.
- **opt-in:** `SCITEX_OROCHI_TELEGRAM_BRIDGE_ENABLED=true` (external service
  — requires intentional activation; see `general/10_arch-environment-variables.md` §Exceptions).
- **opt-in (dev only):** `SCITEX_OROCHI_SKIP_TLS_VERIFY=true` — never in prod.

## Audit

```bash
grep -rhoE 'SCITEX_[A-Z0-9_]+' $HOME/proj/scitex-orochi/src/ | sort -u
```
