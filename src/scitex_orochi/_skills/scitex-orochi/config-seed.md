---
name: orochi-config-seed
description: Root-cause fix for Claude Code onboarding prompts — pre-seed `~/.claude/settings.json` + `~/.claude.json` (not a mythical `config.json`) via dotfiles symlink, with canonical permission allowlist and trusted-directories list. Stops every Write/Edit/Bash call from blocking on a human-approval prompt.
---

# Claude Code config seed

**Every agent boot should find a pre-populated `~/.claude/settings.json` and `~/.claude.json` waiting for it.** If those files are absent or the symlink target is missing, Claude Code will prompt for permission on every Write / Edit / Bash invocation, and fleet agents will stall on the first non-trivial tool call. The root cause of today's MBA stuck-prompt cluster (2026-04-14, todo#423) was a broken symlink to a missing dotfile, not an onboarding step.

This skill is the fix, and the canonical template location, and the checklist a fresh host runs.

## What is actually involved

Claude Code has **two** JSON files that agents care about, plus **one** commonly-mistaken non-file:

| Path | What it holds | Who writes it |
|---|---|---|
| `~/.claude/settings.json` | Permission allowlist, trusted directories, `skipDangerousModePermissionPrompt`, UI prompt suggestions | **You**, via dotfiles |
| `~/.claude.json` | `hasCompletedOnboarding`, `oauthAccount.emailAddress`, `claudeAiOauth` subscription metadata, theme choice, session history refs | **Claude Code itself**, on first run after `/login` |
| `~/.claude/config.json` | **Does not exist.** Agents asking for "`config.json`" usually mean `settings.json`. | — |

`settings.json` is the pre-seed surface. `~/.claude.json` is touched by Claude Code directly and should **not** be dotfiles-tracked (it carries per-machine OAuth tokens and onboarding flags — see `agent-autostart.md` principle #7).

## Canonical `settings.json` (verified live 2026-04-14)

```json
{
  "skipDangerousModePermissionPrompt": true,
  "promptSuggestionEnabled": false,
  "trustedDirectories": [
    "/Users/ywatanabe/proj",
    "/Users/ywatanabe/.scitex",
    "/Users/ywatanabe/.dotfiles"
  ],
  "permissions": {
    "allow": [
      "Bash(*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)",
      "Glob(*)",
      "Grep(*)",
      "Agent(*)",
      "mcp__scitex-orochi__*",
      "mcp__scitex__*",
      "mcp__filesystem__*"
    ]
  }
}
```

**Key fields**:

- `skipDangerousModePermissionPrompt: true` — removes the top-level "this operation could be risky, proceed?" prompt that otherwise fires on `rm`, `git reset --hard`, etc. Required for agents that run unattended.
- `promptSuggestionEnabled: false` — stops Claude from offering interactive prompt suggestions that block the input pipe.
- `trustedDirectories` — per-machine absolute paths (adapt per host: `/home/ywatanabe/...` on Linux, `/Users/ywatanabe/...` on macOS, `/home/ywatanabe/.scitex` etc. under WSL). Agents that need to touch a dir outside this list will still prompt.
- `permissions.allow` — tool allowlist. `Bash(*)` / `Read(*)` / `Write(*)` / `Edit(*)` / `Glob(*)` / `Grep(*)` / `Agent(*)` cover the core tools; `mcp__<server>__*` allowlists the MCP surfaces the fleet uses (`scitex-orochi`, `scitex`, `filesystem`).

If a permission is missing from `allow`, Claude Code prompts per call. Agents cannot answer those prompts from inside their own loop — only the pane / tmux layer can, and that is exactly what the 2026-04-14 actuator sweep had to clean up. Pre-seeding eliminates the class of stuck-prompt entirely.

## Dotfiles symlink layout (tested 2026-04-14, commit 82000b9e dotfiles)

The file lives in dotfiles and is symlinked into each user's `~/.claude/`:

```
~/.dotfiles/.claude-settings.json        ← the real file, tracked in dotfiles
~/.claude/settings.json                  ← symlink to the above
~/.scitex/orochi/templates/claude-code-seed.json   ← fresh-host template
```

Create on a fresh host:

```bash
# 1. Ensure dotfiles has the seed file
test -f ~/.dotfiles/.claude-settings.json || {
    cp ~/.scitex/orochi/templates/claude-code-seed.json \
       ~/.dotfiles/.claude-settings.json
    cd ~/.dotfiles && git add .claude-settings.json && git commit -m 'feat: seed Claude Code settings.json'
}

# 2. Symlink into ~/.claude/
mkdir -p ~/.claude
ln -snf ~/.dotfiles/.claude-settings.json ~/.claude/settings.json

# 3. Verify the symlink resolves
readlink ~/.claude/settings.json
jq '.permissions.allow' ~/.claude/settings.json
```

Per-host `trustedDirectories` differs (macOS vs Linux vs WSL paths). If you need per-host tweaks without forking the dotfile, use an `include` pattern: keep the shared `allow` list in dotfiles, and add a host-local file `~/.claude/settings.local.json` that Claude Code merges on top. For our fleet the differences are small enough that a single file per host is fine.

## Broken-symlink diagnostic (2026-04-14 root cause)

The MBA outbreak happened because `~/.claude/settings.json` was a **broken symlink** — the dotfile it pointed at had been deleted or never created. Every Write/Edit call on MBA therefore prompted for permission, and fleet agents stalled waiting for the operator to answer.

Detection:

```bash
test -L ~/.claude/settings.json && test ! -e ~/.claude/settings.json \
    && echo "BROKEN SYMLINK — Claude Code will prompt on every tool call"
```

Fix:

```bash
ln -snf ~/.dotfiles/.claude-settings.json ~/.claude/settings.json
# ensure the dotfiles target exists
test -f ~/.dotfiles/.claude-settings.json || cp \
    ~/.scitex/orochi/templates/claude-code-seed.json \
    ~/.dotfiles/.claude-settings.json
```

Fleet `drift-audit.sh` or a dedicated `seed-audit.sh` should check this on every healer sweep — a broken symlink is a silent killer that the pane-state classifier catches *downstream* (as `:permission_prompt`) but not *upstream* (at the bootstrap layer).

## Version-specific prompt catalog

Claude Code adds new interactive prompts in new versions. The ones currently known to fleet agents (2026-04-14):

| Prompt | Where it lives | Skip via |
|---|---|---|
| "Use these settings?" (first run) | Onboarding flow | `hasCompletedOnboarding: true` in `~/.claude.json` |
| "Choose theme: dark / light" | Onboarding flow | Same `~/.claude.json` |
| "I am using this for local development" (dev-channels confirmation) | Triggered by `--dangerously-load-development-channels` | `scitex-agent-container` pane-state handler + ack `1` + Enter |
| "Do you want to proceed? (y/n)" | Per-operation risk gate | `skipDangerousModePermissionPrompt: true` |
| "Allow access to this directory?" | File ops outside trusted dirs | Add the directory to `trustedDirectories` |
| "Do you want to create this file?" | First Write to a new file | `permissions.allow` includes `Write(*)` |
| "This file has been modified, overwrite?" | Edit-after-external-change | `permissions.allow` includes `Edit(*)` |
| "Press Enter to continue" (security disclaimer) | First `/login` | Handled by `scitex-agent-container` auto-ack |

If a new prompt appears that does **not** have a settings key to skip it, the classifier should mark it `:unknown_prompt`, escalate to `#escalation`, and **not** auto-dismiss. Auto-dismissing unknown prompts is a destructive-action failure mode — the prompt may be asking to delete files, revoke permissions, or accept terms. See `pane-state-patterns.md` § "Auto-actions" — unknown state = escalate, never act.

**Catalog expansion is a fleet-wide learning event**: every time a new prompt is observed, the observing agent adds it to this table + to `pane-state-patterns.md` regex list + to `scitex-agent-container` runtime handler. Three commits, one learning. See `fleet-communication-discipline.md` rule #9 (capture in-session).

## Defense in depth with `pane-state-patterns.md` + `scitex-agent-container`

The config seed is the **primary** fix — prevent the prompt from firing at all. Two secondary layers remain in place:

1. **`scitex-agent-container` runtime prompt handlers** (mamba-explorer-mba PR #30 merged 2026-04-14 msg #10899): even if a new Claude Code version introduces a prompt the seed doesn't cover, the container's runtime handlers recognize common patterns (`mcp-json-edit`, `file-trust`, `press-enter-continue`) and auto-dismiss them at the pane level.
2. **`mamba-healer-*` active-probe sweep** (`active-probe-protocol.md`): if both the seed and the runtime handler miss a prompt, the 60-second sweep classifies `:permission_prompt` / `:dev_channels_prompt` / `:paste_pending` via `pane-state-patterns.md` and auto-unblocks on the next cycle.

All three layers must be present. The seed is cheapest (a file on disk), the runtime handler is medium-cost (code in `scitex-agent-container`), and the healer sweep is most expensive (a full probe + classifier cycle). Fixing the seed is the right place to stop most problems; the other layers exist for anything the seed misses.

## Fresh-host bootstrap checklist

Run this once on every new fleet host, before launching any Claude Code agent:

1. `~/.dotfiles/.claude-settings.json` exists on disk (pull dotfiles if not).
2. `~/.claude/settings.json` is a symlink to the above and the target resolves (`readlink` + `test -f`).
3. `jq '.permissions.allow' ~/.claude/settings.json` returns the canonical list.
4. `jq '.trustedDirectories' ~/.claude/settings.json` contains this host's `~/proj`, `~/.scitex`, `~/.dotfiles` absolute paths.
5. `~/.claude.json` exists and `jq '.hasCompletedOnboarding' ~/.claude.json` returns `true` (this is set by Claude Code itself after first `/login`; if it is `false`, the next agent boot will spend 30 s in onboarding).
6. `scitex-agent-container` auto-dismiss handlers (PR #30) are on `develop` and installed: `scitex-agent-container version` shows a post-2026-04-14 build.
7. `mamba-healer-<host>` sweep timer is running (`systemctl --user list-timers | grep scitex-healer-sweep`).

If any step fails, the fresh host is not ready; fix that step before starting agents there.

## Anti-patterns

- **Editing `settings.json` by hand on a running host.** Dotfiles is the source of truth; edit the dotfile, commit, pull on the host. Otherwise the next dotfiles sync overwrites your change or leaves drift.
- **Copying `settings.json` as a file instead of symlinking.** Each host's copy drifts over time. Symlink to dotfiles, never copy.
- **Tracking `~/.claude.json` in dotfiles.** It carries OAuth tokens + per-machine onboarding state. `agent-autostart.md` principle #7 already bans this after the 2026-04-13 Spartan incident.
- **Writing to `~/.claude/config.json`.** This file does not exist in Claude Code. If a script or agent is creating it, that is a bug — it is reading documentation for some other tool or hallucinating a path.
- **Adding `Read(*)` before `Write(*)`** (or any arbitrary permission subset) **without `Bash(*)`**. Agents that can read but not run bash are strictly less useful than agents that can do nothing at all, because they burn tokens discovering they are handicapped.

## Related

- `agent-autostart.md` principle #6 (one process, one identity) + principle #7 (`~/.claude.json` is machine-local)
- `pane-state-patterns.md` — downstream layer that catches prompts the seed misses
- `active-probe-protocol.md` — the sweep that auto-unblocks what the pane-state classifier identifies
- `fleet-communication-discipline.md` rule #9 (capture in-session) — new prompts get added to the catalog immediately, not queued
- `fleet-communication-discipline.md` rule #13 (one-minute responsiveness) — a stuck-on-prompt agent violates rule #13, which is why the seed is the **primary** fix
- mamba-auth-manager-mba msg #10900 — the incident investigation + commit 82000b9e that shipped the fix
- mamba-explorer-mba msg #10899 / #10901 — PR #30 runtime handlers (defense-in-depth layer 2)
- todo#423 — originating issue

## Change log

- **2026-04-14 (initial)**: Drafted from the 2026-04-14 MBA broken-symlink incident + mamba-auth-manager-mba investigation (msg #10900) + mamba-explorer-mba defense-in-depth observation (msg #10901). Canonical `settings.json` content captured from live `~/.claude/settings.json` on MBA. Author: mamba-skill-manager.
