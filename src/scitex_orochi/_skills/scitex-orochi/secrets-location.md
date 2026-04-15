---
name: orochi-secrets-location
description: Where fleet agents find API tokens, credentials, and other secrets, and the "ガンガン使って" usage policy.
---

# Secrets Location

Fleet-wide reference for how any Orochi agent obtains credentials without asking the user each time.

## Sources

1. **`~/.dotfiles/src/.bash.d/secrets/`** — bash-sourceable `.src` files that export env vars. This is the primary source for scitex-owned secrets.
   - Search: `grep -ril <keyword> ~/.dotfiles/src/.bash.d/secrets/`
   - Example (verified 2026-04-13): `~/.dotfiles/src/.bash.d/secrets/010_scitex/99_cloudflare.src` exports `SCITEX_CLOUDFLARE_EMAIL` and `SCITEX_CLOUDFLARE_API_KEY` (Global API Key, full perms).
   - Naming: `SCITEX_<PACKAGE>_<FIELD>` per `project_scitex_env_var_convention`.
   - Usage: `source ~/.dotfiles/src/.bash.d/secrets/010_scitex/99_cloudflare.src && ./do-thing`.

2. **`~/.password-store/`** — `pass` CLI / GPG store.
   - List: `pass ls`
   - Read: `pass show <path>`
   - Scripted: `TOKEN=$(pass show github/token)`.

3. **Encrypted archives** (if present under `~/.dotfiles/`) — decrypted with per-host SSL keys `ugreen.ssl` / `mba.ssl` / `ywata-note-win.ssl`. See `project_sync_policy` memory. Rare; most agents never touch these.

Dotfiles are synced across MBA / NAS / spartan / ywata-note-win, so `source` works identically on every host.

## Usage Policy — "ガンガン使って"

ywatanabe has explicitly authorized (msg #8180, 2026-04-13): **use these secrets aggressively without asking permission each time.** No pre-approval prompts for routine operational use.

Applies to:
- CF API tokens (full-perm) for DNS / tunnel management
- scitex-orochi credentials for hub ops
- SSH keys for cross-host file transfer and remote exec
- Any other scitex-owned credential in the two sources above

**Forbidden regardless of policy:**
- Never paste secret values into Orochi channels, logs, commit messages, or issue bodies.
- Never write secrets into `GITIGNORED/` or any file that might leave the host.
- Share **paths** and **env var names** with other agents, not values.
- `echo "$SCITEX_CLOUDFLARE_API_KEY"` into a screen capture or chat = immediate incident.

## Agent Onboarding

New agents inherit this skill by default via scitex-orochi skill loading. No per-agent configuration needed. If an agent seems to be asking ywatanabe for tokens it can retrieve from the above paths, point it at this skill.

## Mail infrastructure (mbsync + msmtp + mutt/neomutt on ywata-note-win)

Added 2026-04-14 per ywatanabe msg #10420 directive. Mail credentials live outside the normal SciTeX secret tree; this subsection documents where to find them so fleet agents can help ywatanabe triage inboxes without touching credential flows they must not touch.

### Canonical paths (on `ywata-note-win` WSL)

| Purpose | Path |
|---|---|
| `mbsync` (IMAP sync, downloads mail) | `~/.mbsyncrc` |
| `msmtp` (SMTP send) | `~/.msmtprc` |
| Local Maildir (after sync) | `~/mail/<account>/INBOX/` |
| `mutt` / `neomutt` config | `~/.mutt/` or `~/.config/neomutt/` |
| IMAP passwords (App Passwords) | stored inline in `.mbsyncrc` / `.msmtprc`, or resolved via `PassCmd` against `pass` / `gpg` |

12 accounts configured: 3 Gmail + ~10 `@scitex.ai` (admin + per-user aliases). The exact account list lives in `~/.mbsyncrc` on `ywata-note-win`.

### Agent usage

From any host with SSH access to `ywata-note-win`:

```bash
# Sync all accounts (safe, idempotent)
ssh ywata-note-win 'mbsync -a'

# Sync one account
ssh ywata-note-win 'mbsync scitex-admin'

# Read an inbox
ssh ywata-note-win 'mutt -R -f ~/mail/scitex-admin/INBOX'

# Send via msmtp (plain text body on stdin)
ssh ywata-note-win 'cat /tmp/body.txt | msmtp -a scitex-admin recipient@example.com'
```

Use `mutt -R` (read-only) for inspection unless explicitly delegated write authority. Write operations (delete, flag, archive, move) are allowed for organization tasks ywatanabe has delegated (msg #10414 / #10417), but the **forbidden subset** below applies regardless.

### Forbidden subset — do not touch under any circumstance

1. **Password reset / recovery emails** from any service. Do not read, do not delete, do not forward. They are credential-flow artifacts; even reading them is forbidden per `feedback_never_touch_user_credentials.md`.
2. **2FA / MFA / one-time codes** in SMS-bridge emails or authenticator invitations.
3. **Banking, government, medical, legal** correspondence. Archive only at explicit ywatanabe instruction, never autonomously.
4. **Messages involving Anthropic account lifecycle** (quota appeals, billing escalations, extra-usage confirmations). These interact with the same credential surface `agent-account-switch.md` protects.

### Acceptable organization tasks

With ywatanabe delegation (msg #10414 / #10417):

- GitHub `notifications@github.com` — auto-file into `Archive/github/YYYY-MM/` after reading.
- Dependabot alerts — same pattern, or delegate to fleet agent for auto-review and batch response.
- Newsletter subscriptions (conference announcements, mailing lists) — bulk archive older than N days.
- Unsolicited sales / cold outreach — mark as spam or delete.
- Paper preprint notifications from journals + arXiv — triage by keyword, file into `Papers/`.

When in doubt, leave the message alone and summarize the ambiguity to ywatanabe in `#ywatanabe` with no action taken.

### Skill-level invariants

- Do not duplicate passwords into any other file (chat, logs, screenshots, commits). They are already in `.mbsyncrc` / `.msmtprc`; agents reference but never extract.
- Do not run `mbsync` on a host other than `ywata-note-win`. The Maildir is bound to that host; duplicating it elsewhere creates inbox-state drift.
- Do not send outgoing mail on behalf of ywatanabe without explicit per-message confirmation. `msmtp` is available for *system* notifications (escalation alerts, cron reports); human-addressed mail requires approval in the same `#ywatanabe` thread.
- Record every write operation (delete, flag, move) in `~/.scitex/mail-ops.log` with `{ts, agent, account, message_id, action}` so ywatanabe has an audit trail.

## Related

- memory `reference_secrets_location.md` — canonical reference
- memory `project_scitex_env_var_convention` — `SCITEX_<PACKAGE>_*` naming rule
- memory `project_sync_policy.md` — dotfiles sync + per-host SSL keys
