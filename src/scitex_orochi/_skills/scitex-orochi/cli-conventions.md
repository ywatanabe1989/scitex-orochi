---
name: orochi-cli-conventions
description: SciTeX CLI design conventions — verb-noun structure, standard flags, exit codes, output streams. Apply to all new CLI commands across the ecosystem.
---

# CLI Conventions (SciTeX / Orochi Fleet)

These conventions apply to all CLI tools built within the SciTeX ecosystem and Orochi fleet. The upstream definition lives in `scitex-dev` (`scitex/general/interface-cli.md`); this file extends and clarifies it for fleet use.

## Command Structure

### Verb-Noun Pattern (Preferred)
```bash
scitex-orochi list-agents          # verb-noun, hyphenated
scitex-orochi show-history #general
scitex-orochi send-message #general "hi"
```

### Subcommand Hierarchy (For grouped operations)
```bash
scitex-dev skills list             # noun → verb
scitex-dev skills export
scitex-dev mcp start
scitex-dev mcp doctor
```

Pick one style per package and stay consistent. Existing scitex-orochi uses verb-noun for top-level CLI; scitex-dev uses subcommands.

## Standard Flags (All Commands)

| Flag | Purpose | Required for |
|------|---------|--------------|
| `-h`, `--help` | Show usage with examples | All commands |
| `--help-recursive` | Show help for all subcommands recursively | Commands with subcommands |
| `--json` | Machine-readable JSON output | All data-fetching commands |
| `--dry-run` | Preview changes without applying | All mutating commands |
| `--version` | Print package version | Top-level entry point |
| `--verbose`, `-v` | Increase verbosity | Optional |
| `--quiet`, `-q` | Suppress non-error output | Optional |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Generic error (operation failed) |
| 2 | Usage error (bad flags, missing args) |
| 3+ | Domain-specific errors (document in `--help`) |

## Output Streams

- **stdout**: Data, JSON, parseable output. Pipe-friendly.
- **stderr**: Logs, progress, warnings, errors. Not for piped data.
- **Rule**: A user must be able to `cmd --json | jq` without log noise mixing in.

## Help Text Requirements

Every command's `--help` must include:
1. One-line description
2. Usage synopsis
3. **At least one example** (concrete invocation)
4. List of flags with descriptions
5. Exit code summary (if non-trivial)

## Environment Variables

- All package-level env vars use the `SCITEX_<PACKAGE>_*` prefix (e.g., `SCITEX_OROCHI_HOST`)
- CLI flags should override env vars
- Document env var fallbacks in `--help`

## MCP Tool Parity

When a CLI command corresponds to an MCP tool:
- Use the same name (or close: `scitex-orochi send-message` ↔ `mcp__scitex-orochi__send`)
- Same arguments
- Same JSON shape for output
- Document parity in the package SKILL.md

## Audit Checklist (For Existing Commands)

When auditing a SciTeX package's CLI for compliance:

- [ ] Verb-noun OR subcommand structure (consistent)
- [ ] `--help` works on every command
- [ ] `--help-recursive` works at top level
- [ ] `--json` available on all data commands
- [ ] `--dry-run` available on all mutating commands
- [ ] Exit codes follow convention
- [ ] stdout vs stderr separation correct
- [ ] Examples in help text
- [ ] Env var prefix correct (`SCITEX_<PKG>_*`)
- [ ] MCP tool parity (if applicable)

Failing items should be filed as `cli-audit` issues in `ywatanabe1989/todo`.
