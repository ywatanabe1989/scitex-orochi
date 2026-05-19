---
name: orochi-cli-conventions-part-3
description: SciTeX CLI conventions §§5-13 — standard flags, exit codes, output streams, help text, env vars, MCP parity, non-interactive rule, audit checklist, cross-references. Continuation of 56_convention-cli-extras.md.
---

# CLI Conventions (SciTeX / Orochi Fleet) — §§ 5–13

Continuation of `56_convention-cli-extras.md`. That file covers §§1–4 (noun-verb shape, deprecation policy, help-display, flat keepers).

## 5. Standard Flags (All Commands)

| Flag | Purpose | Required for |
|------|---------|--------------|
| `-h`, `--help` | Show usage with examples | All commands |
| `--help-recursive` | Show help for all subcommands recursively | Top-level entry point |
| `--json` | Machine-readable JSON output | All data-fetching commands |
| `--dry-run` | Preview changes without applying | All mutating commands |
| `--version` | Print package version | Top-level entry point |
| `--verbose`, `-v` | Increase verbosity | Optional |
| `--quiet`, `-q` | Suppress non-error output | Optional |

## 6. Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Generic error (operation failed) |
| 2 | Usage error (bad flags, missing args, **deprecated-rename hit**) |
| 3+ | Domain-specific errors (document in `--help`) |

## 7. Output Streams

- **stdout**: Data, JSON, parseable output. Pipe-friendly.
- **stderr**: Logs, progress, warnings, errors, deprecation notices.
- **Rule**: A user must be able to `cmd --json | jq` without log noise
  mixing in. This is why deprecation messages and the `(Available Now)`
  suffix are stderr- / help-only, never on stdout.

## 8. Help Text Requirements

Every command's `--help` must include:
1. One-line description
2. Usage synopsis
3. **At least one example** (concrete invocation)
4. List of flags with descriptions
5. Exit code summary (if non-trivial)

## 9. Environment Variables

- All package-level env vars use the `SCITEX_<PACKAGE>_*` prefix
  (e.g., `SCITEX_OROCHI_HOST`).
- CLI flags should override env vars.
- Document env var fallbacks in `--help`.

### 9.1 Bare prefixes are forbidden (Hard Rule)

**Never use a bare package name as an env var prefix.** Always include
`SCITEX_`:

| Forbidden | Required |
|---|---|
| `OROCHI_AGENT` | `SCITEX_OROCHI_AGENT` |
| `OROCHI_TOKEN` | `SCITEX_OROCHI_TOKEN` |
| `OROCHI_HOST` | `SCITEX_OROCHI_HOST` |
| `OROCHI_MULTIPLEXER` | `SCITEX_OROCHI_MULTIPLEXER` |
| `AGENT_CONTAINER_*` | `SCITEX_AGENT_CONTAINER_*` |
| `SCHOLAR_*` | `SCITEX_SCHOLAR_*` |

Reason (operator directive 2026-04-12): bare prefixes collide with other
tools' env vars and pollute the global namespace. The `SCITEX_` namespace
makes ownership unambiguous and lets users `env | grep SCITEX_` to see
all SciTeX-related state at once.

When auditing existing code, `grep -rE '^OROCHI_|[^A-Z_]OROCHI_'` finds
violations. Rename and update all references in one commit.

### 9.2 Deprecation-specific env vars (Phase 1d)

| Var | Effect |
|---|---|
| `SCITEX_OROCHI_NO_DEPRECATION=1` | Suppress soft notes; hard-rename error still prints once |
| `SCITEX_OROCHI_SHELL_SESSION` | Explicit session key for soft-notice tracking (defaults to PPID) |

### 9.3 Scope: scitex-owned vars only

The `SCITEX_<PACKAGE>_*` rule applies **only to env vars that scitex code
defines and reads**. It does **not** apply to env vars defined by
third-party tools, frameworks, or upstream conventions:

- **Out of scope (keep upstream names):** `POSTGRES_*`, `DATABASE_URL`,
  `DJANGO_*`, `ALLOWED_HOSTS`, `VITE_*`, `NODE_ENV`, `PATH`, `HOME`,
  `LANG`, `BUILD_ID`, `CI`, `GITHUB_*`, `AWS_*`, etc.
- **In scope (must rename):** any env var that scitex code originates and
  whose name we control.

### 9.4 Where SCITEX_* env vars live (canonical location)

All scitex-owned env vars are sourced from
**`~/.dotfiles/src/.bash.d/secrets/010_scitex/`** (one `.src` file per
package: `01_orochi.src`, `01_cloud.src`, `01_agent-container.src`,
`01_scholar.src`, etc.).

Rules:
- When adding a new `SCITEX_<PACKAGE>_FOO` var, **add the export to the
  matching `01_<package>.src` file** in `010_scitex/`.
- When renaming a bare-prefix var (e.g. `OROCHI_TOKEN` →
  `SCITEX_OROCHI_TOKEN`), re-import / re-export from the same
  `01_orochi.src` file so all hosts pick up the new name on next shell
  init.
- Secrets stay in this directory (gitignored); never inline secrets in
  package code or YAML.

## 10. MCP Tool Parity

When a CLI command corresponds to an MCP tool:
- Use the same name (or close: `scitex-orochi message send` ↔
  `mcp__scitex-orochi__send`)
- Same arguments
- Same JSON shape for output
- Document parity in the package SKILL.md

## 11. No Interactive Prompts (Hard Rule)

CLI commands MUST be non-interactive by default — they must work in
pipelines, CI, and unattended agent runs.

- **Never prompt for input** at runtime (no `input()`, no `read`, no
  password prompts)
- If credentials are needed, read from env vars, config files, or
  `--flag` args
- If a value is missing, **fail fast with a clear error message** — do
  not block waiting

### 11.1 Fail-First Pattern

Validate all preconditions at the **start** of the command, before doing
any work:

```python
def main():
    # 1. Check all preconditions FIRST
    if not have_sudo():
        sys.stderr.write("error: this command requires sudo.\n")
        sys.exit(2)
    if not config_exists():
        sys.stderr.write("error: missing config at ~/.scitex/config.yaml\n")
        sys.exit(2)

    # 2. Only then proceed with the actual work
    do_work()
```

**Why**: Interactive prompts break agent automation.

### 11.2 Acceptable: `--yes` Override

Mutating commands may use `--yes` / `-y` to bypass safety checks, but the
**default** must be safe (e.g., `--dry-run` style preview, then `--yes`
to apply).

## 12. Audit Checklist (For Existing Commands)

When auditing a SciTeX package's CLI for compliance:

- [ ] `<noun> <verb>` structure (or explicit flat-keeper exception)
- [ ] `--help` works on every command
- [ ] `--help-recursive` works at top level
- [ ] `--json` available on all data commands
- [ ] `--dry-run` available on all mutating commands
- [ ] Exit codes follow convention
- [ ] stdout vs stderr separation correct
- [ ] Examples in help text
- [ ] Env var prefix correct (`SCITEX_<PKG>_*`)
- [ ] MCP tool parity (if applicable)
- [ ] Deprecated-rename hits call `hard_rename_error(old, new)` with
      exit 2 and no silent fallback

Failing items should be filed as `cli-audit` issues in the project's
issue tracker.

## 13. Cross-references

- `docs/cli.md` — public pointer to this file.
- `docs/cli-refactor-plan-2026-04-22.md` (PR #337) — the plan that
  produced these rules.
- `src/scitex_orochi/_cli/_help_availability.py` — implementation of
  the `(Available Now)` suffix layer.
- `src/scitex_orochi/_cli/_deprecation.py` — implementation of the
  hard-rename / soft-notice helpers.
- `src/scitex_orochi/_skills/SKILL_INDEX.md` — one-line role per skill
  (so agents can grep for "cli convention" and land here).
- head-ywata-note-win's msg#16558 fleet-wide convention skill — when it
  lands, this file cross-references it rather than duplicating text.
