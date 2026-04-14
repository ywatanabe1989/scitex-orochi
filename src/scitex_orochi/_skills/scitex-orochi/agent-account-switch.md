---
name: orochi-agent-account-switch
description: Credential file naming, dotfiles-shared symlinks, in-place `/login` swap without killing the agent, and quota-threshold triggers. Keeps fleet agents alive across Anthropic 5h/7d quota windows.
---

# Agent Account Switch (Credential Rotation)

Keep Orochi fleet agents alive when a single Anthropic account trips its 5-hour or 7-day quota. Agents swap credentials in-place — no kill, no respawn, no `--continue` context loss.

## Why

Observed 2026-04-13 (msgs #9400 / #9408 / #9494): one quota-exhausted account took down head-ywata-note-win for ~4 days of wait (`"resets Apr 17, 8am"`). Every agent pinned to the same account shares the same fate. Rotating credentials across 2+ Anthropic accounts distributes load and ensures at least one path is always live.

ywatanabe directive (msg #9494): *"5h/7days のリミットに合わせて credential 回す。全員が死なないように。"*

## Acquisition paths (canonical, 2026-04-14)

Provided by `mamba-auth-manager-mba` msg #10237. These are the only sanctioned read points for Claude credential metadata — do not parse `.credentials.json` tokens directly, use the helpers.

### Claude OAuth (active session)

| Path | What's there | How to read |
|---|---|---|
| `~/.claude.json` | `oauthAccount.emailAddress` — the currently logged-in account identity | Read directly (safe, whitelist) |
| `~/.claude/.credentials.json` | `claudeAiOauth.{subscriptionType, rateLimitTier}` | **Never** parse the tokens; use `scitex_agent_container.credentials.read_credentials_metadata()` |

Tokens inside `.credentials.json` are off-limits to agents. If you need to know "which account" or "what plan", call the metadata helper — it returns only the whitelisted fields.

### Saved account store (multi-account rotation)

| Path | Purpose |
|---|---|
| `~/.scitex/claude-accounts/<name>/credentials.json` | Encrypted credentials per stored account |
| `scitex_agent_container.account_store.list_accounts()` | Enumerate saved accounts |
| `scitex_agent_container.account_store.switch_account(name)` | Activate a stored account (this is the library-level counterpart to the symlink flip described below) |

There is **no** `SCITEX_CLAUDE_CREDENTIAL_ACTIVE` env var. The active account is always read live from `~/.claude.json`. Any automation that needs to know "who am I right now" reads that file, not an env var.

### OS passwords (for sudo / SSH unlock, not Claude)

| Path | Use |
|---|---|
| `~/.pw/mba.ssl` | MBA user / sudo — `~/.dotfiles/src/.bin/utils/decrypt.sh -t mba.ssl` |
| `~/.pw/ugreen.ssl` | NAS sudo — `decrypt.sh -t ugreen.ssl` |
| `~/.pw/nas2.ssl` | NAS2 — `decrypt.sh -t nas2.ssl` |

These unlock OS-level operations during a credential swap (e.g., systemd user unit reload requiring sudo) and are not Claude credentials themselves.

### Service tokens (via dotfiles env vars, not credential files)

| Env var | Source |
|---|---|
| `SCITEX_OROCHI_TOKEN` | `~/.bash.d/secrets/010_scitex/01_orochi.src` |
| `SCITEX_CLOUD_CAMPAIGN_ANTHROPIC_API_KEY` | `~/.bash.d/secrets/010_scitex/01_cloud.src` — API-key fallback, **not** OAuth |

The API-key fallback lets an agent survive when all OAuth accounts are quota-exhausted, at the cost of billing against direct API usage instead of the subscription. Use only when the OAuth rotation exhausts every account.

## Credential file naming

Canonical path layout on every host:

```
~/.claude/.credentials.json                      <- symlink (active)
~/.claude/.credentials-ywata1989.json            <- account A
~/.claude/.credentials-wyusuuke.json             <- account B
~/.claude/.credentials-<future-account>.json    <- extend as accounts are added
```

Rules:

- **Filename format**: `.credentials-<account-slug>.json`. Slug matches Anthropic account name, lowercase, no dots.
- **Active file is a symlink.** Claude Code reads `~/.claude/.credentials.json`; the rotation script flips the symlink target. Claude itself doesn't know — until `/login` refreshes its in-memory token.
- **Never edit `.credentials.json` directly.** Always write `<slug>.json` first, then `ln -snf` the symlink. Atomic on POSIX.

## Dotfiles sharing (optional, msg #9414)

If you want fleet-wide credential distribution:

```
~/.dotfiles/.claude-credentials/
  .credentials-ywata1989.json      # gitignored, encrypted, or in a separate private tree
  .credentials-wyusuuke.json
```

Then on each host:

```bash
ln -snf ~/.dotfiles/.claude-credentials/.credentials-<account>.json \
        ~/.claude/.credentials-<account>.json
ln -snf ~/.claude/.credentials-<account>.json ~/.claude/.credentials.json
```

**Security**: credential files contain refresh tokens. Do **not** commit them to a public git repo. Options:

1. Keep outside dotfiles entirely and distribute via `scp`/ansible/ssh. Simplest, no crypto.
2. Put under `~/.dotfiles/.claude-credentials/` with the directory in `.gitignore` (shared via private rsync, not git).
3. Encrypt at rest under dotfiles using `decrypt.sh` + per-host SSL keys (see `project_sync_policy.md` memory).

## The in-place swap (no-kill `/login` experiment)

ywatanabe explicitly opposed kill+respawn (msg #9416): *"kill しないで、クレデンシャルを切り替えて `/login` でいい."*

Canonical sequence on the host running the target agent (not inside the agent itself):

```bash
AGENT=mamba-healer-ywata-note-win
ACCOUNT=wyusuuke

# 1. Flip the credential symlink (atomic).
ln -snf ~/.claude/.credentials-${ACCOUNT}.json ~/.claude/.credentials.json

# 2. Confirm the flip.
ls -la ~/.claude/.credentials.json

# 3. Send /login to the agent's tmux pane — NOT kill the process.
tmux send-keys -t "${AGENT}" Escape
sleep 0.2
tmux send-keys -t "${AGENT}" "/login" Enter

# 4. Watch the pane for the OAuth URL.
tmux capture-pane -pt "${AGENT}" | tail -60

# 5. Post the URL to #ywatanabe (file upload preferred to avoid chat-copy breakage).
# 6. When ywatanabe returns the code, inject it:
tmux send-keys -t "${AGENT}" "<code>" Enter

# 7. Verify: pane should show new account email in the Claude status footer.
```

Why this works:

- Claude Code re-reads `~/.claude/.credentials.json` on `/login`. Symlink points to the new file before the reload.
- `--continue` context is preserved because the process is not killed; same session file, same in-memory transcript.
- Quota counters are per-account on Anthropic's side, so the agent immediately gets the fresh account's budget.

## State detection — when to trigger a swap

The agent's tmux pane exposes quota state visually. Detect by regex on `tmux capture-pane` output (see `pane-state-patterns.md` for the catalog):

| Trigger | Regex | Action |
|---|---|---|
| Hard out | `out of extra usage \| resets [A-Z][a-z]{2} \d+` | Immediate swap to a non-exhausted account |
| Near-limit warning | `(9\d)% \| Limit reach` | Pre-emptive swap if the other account is <70% |
| `/extra-usage` nag | `/extra-usage to finish what you're working on` | Same as hard out |
| Auth refresh | `401 Authentication Error` | Swap first, then `/login` even if credentials look fine |

Aggressive rule: **always leave one account below 70% on both 5h and 7d windows**, so that a quota spike on one agent doesn't cascade.

## Quota window awareness (5h and 7d)

Anthropic enforces two rolling windows. Both must be tracked per account:

- **5h window**: short-term rolling. Reset is automatic after 5 hours of reduced usage.
- **7d window**: long-term weekly. Hard reset at the stated reset time (e.g., "resets Apr 17, 8am").

Agents that share an account share both windows. Rotation strategy:

- **Account A** → heavy-work agents (head-mba, head-spartan) during business hours
- **Account B** → background agents (mamba-healer-*, mamba-synchronizer-mba, mamba-quality-checker-mba) always
- Swap roles when one account crosses 70% of either window

The `claude_account_status` / `quota_status` MCP tools (todo #299) surface current % for each window. Poll on the sampler's cadence, not inside a Claude Code loop.

## What *not* to do

- **Do not `set_password` or otherwise touch the Anthropic user account itself.** The 2026-04-13 incident (msg #9494 directive, memory `feedback_never_touch_user_credentials`) was triggered by an agent attempting to reset a user password. Agent credential ops are strictly file-level (`~/.claude/.credentials*.json`).
- **Do not kill + respawn.** That loses `--continue` context and the conversation history that made the agent useful.
- **Do not hardcode an account name in the agent yaml** — use the symlink. Hardcoding defeats rotation.
- **Do not use a wrapper that retries `/login` in a tight loop** if the swap fails. Stop, escalate, investigate. Tight retry loops against Anthropic are a ban vector.
- **Do not put credentials in channel posts.** File uploads (`.txt`) are acceptable for OAuth URLs that need human action; *values* never go anywhere that could be cached or indexed.

## Test-fail recovery

If the swap breaks the pane (login flow errors, timeout):

1. Flip the symlink back to the previous account.
2. Re-`/login` with the rollback credential — this is reversible.
3. If still stuck, capture the pane + escalate in `#escalation`. Do not kill the process unless `#escalation` escalates it further.

## Related

- `pane-state-patterns.md` — the regex catalog this skill triggers on
- `fleet-communication-discipline.md` rule #7 — identity integrity; new credential must not change the agent's `SCITEX_OROCHI_AGENT` attribution
- `agent-autostart.md` principle #6 — one agent, one process, one identity
- memory `project_account_switch_login_protocol.md` — ywatanabe posts OAuth URL to `#ywatanabe`, returns code, agent injects
- memory `feedback_never_touch_user_credentials.md` — agent credential ops are strictly file-level
- todos #299 / #353 / #359 — proactive rotation + graceful degradation + single-account survival mode

## Change log

- **2026-04-14 (initial)**: Drafted from the 2026-04-13 quota-exhaustion incident (msgs #9400–#9504) and mamba-todo-manager's skill request #9492. Author: mamba-skill-manager.
