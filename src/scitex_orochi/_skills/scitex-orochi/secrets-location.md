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

## Related

- memory `reference_secrets_location.md` — canonical reference
- memory `project_scitex_env_var_convention` — `SCITEX_<PACKAGE>_*` naming rule
- memory `project_sync_policy.md` — dotfiles sync + per-host SSL keys
