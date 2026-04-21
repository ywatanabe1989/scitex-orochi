---
name: orochi-cli-conventions
description: SciTeX CLI design conventions — canonical noun-verb shape for scitex-orochi, standard flags, exit codes, deprecation policy, and help-display rules. Apply to all new CLI commands across the Orochi fleet.
---

# CLI Conventions (SciTeX / Orochi Fleet)

These conventions apply to all CLI tools built within the SciTeX ecosystem
and Orochi fleet. The upstream definition of the shared verb/noun
vocabulary lives in `scitex-dev` (`scitex/general/interface-cli.md`) and is
being consolidated cross-package in the `head-ywata-note-win` fleet-wide
convention skill (msg#16558, in flight). This file is the **scitex-orochi
canonical source of truth** — anything in a downstream skill that
contradicts this file loses.

Canonical path: `src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`.
Web-discovery pointer: `docs/cli.md` (Q3 decision, plan PR #337).

## 1. Canonical shape: `scitex-orochi <noun> <verb>`

As of Phase 1d (PR #337 plan, Step A onward), every scitex-orochi
subcommand MUST be exposed as a `<noun> <verb>` pair — click group =
noun, command = verb.

```bash
scitex-orochi agent launch head-mba
scitex-orochi agent status
scitex-orochi channel list
scitex-orochi channel join '#heads'
scitex-orochi message send '#agent' 'hello'
scitex-orochi workspace create demo
scitex-orochi invite create <ws-id>
scitex-orochi machine heartbeat send
scitex-orochi machine resources show
scitex-orochi cron start
scitex-orochi host-liveness probe
scitex-orochi hungry-signal check
scitex-orochi chrome-watchdog check
scitex-orochi dispatch run --head mba
scitex-orochi todo triage --lane hub-admin
scitex-orochi push setup
scitex-orochi server start
scitex-orochi config init
scitex-orochi system doctor
scitex-orochi auth login
scitex-orochi hook report activity
scitex-orochi mcp start                   # flat keeper — see §4
```

### 1.1 Complete noun-group registry (as of Phase 1d Step A plan)

Planned canonical groups (Section 2 of PR #337's plan):

1. **`agent`** — agent lifecycle and fleet view
   * `agent launch NAME`
   * `agent restart NAME`
   * `agent stop NAME`
   * `agent status`
   * `agent list`
   * `agent fleet-list` (absorbs legacy top-level `fleet`)
2. **`channel`** — channel membership and history
   * `channel list`
   * `channel join NAME`
   * `channel history NAME`
   * `channel members NAME`
3. **`workspace`** — workspace CRUD
   * `workspace create NAME`
   * `workspace delete ID`
   * `workspace list`
4. **`invite`** — workspace invites
   * `invite create WS_ID`
   * `invite list WS_ID`
5. **`message`** — messaging verbs
   * `message send CHANNEL MESSAGE`
   * `message listen [--channel]`
   * `message react add`
   * `message react remove`
6. **`machine`** — host-level operations
   * `machine heartbeat send`
   * `machine heartbeat status`
   * `machine resources show`
7. **`cron`** — unified Orochi cron daemon (msg#16406 / #16410)
   * `cron {start,stop,list,run,status,reload}`
8. **`disk`** — host disk hygiene
   * `disk reaper-dry-run`
   * `disk pressure-probe`
9. **`host-liveness`** — fleet-watch host reachability probe
   * `host-liveness probe`
10. **`hungry-signal`** — Layer 2 idle-head → lead ping
    * `hungry-signal check`
11. **`chrome-watchdog`** — macOS kernel_task CPU escape hatch
    * `chrome-watchdog check`
12. **`dispatch`** — operator-side auto-dispatch control
    * `dispatch run --head HOST [--todo N]`
    * `dispatch status`
    * `dispatch history`
13. **`todo`** — fleet todo queue
    * `todo list [--lane LABEL]`
    * `todo next --lane LABEL`
    * `todo triage [--lane LABEL]`
14. **`push`** — APNs / notification plumbing
    * `push setup`
    * `push send`
15. **`server`** — hub server lifecycle
    * `server start` (replaces `serve`)
    * `server status`
    * `server deploy` (absorbs legacy top-level `deploy`)
16. **`config`** — local scitex-orochi config
    * `config init` (replaces top-level `init`)
17. **`system`** — host-side self-diagnosis
    * `system doctor` (replaces top-level `doctor`)
18. **`auth`** — credential / session management
    * `auth login` (replaces top-level `login`)
19. **`hook`** — Claude Code / framework hook-driven reporting
    * `hook report activity`
    * `hook report stuck`
    * `hook report heartbeat`
20. **`host-identity`** — local-vs-remote resolver (read-only)
    * `host-identity {show,init,check}`

### 1.2 Why this shape

* Groups keep the `--help` tree navigable. `scitex-orochi agent --help`
  lists every agent verb without polluting the top level.
* Subcommand-level monkeypatching (the PR #336 test pattern) is
  cleaner when the verb is the last path component.
* The shell wrappers (`scripts/client/*.sh`) become trivial
  `exec scitex-orochi <noun> <verb> "$@"` shims — one idiom, no
  per-script flag handling.
* Single-package parity with `scitex-dev` and the forthcoming sac
  noun-verb refactor (deferred — Q6 / msg#16533).

## 2. Deprecation policy (Q1 + Q2 decisions, plan PR #337)

### 2.1 Hard-error on rename (no grace period)

Renamed commands do **not** fall through to the new name. They **hard-error
at call time** with a one-line fix instruction and exit non-zero. This is
the "soon" policy — immediate rename, zero silent-fallback risk.

**Canonical stderr format (exit code = 2):**

```
error: `scitex-orochi <old-name>` was renamed to `scitex-orochi <new-name>`.
```

No multi-line banner. No colour. No link. One line, one action: tell the
operator the exact string to type instead.

Implemented by `scitex_orochi._cli._deprecation.hard_rename_error(old, new)`.

**Post-Phase-1d cleanup (ywatanabe msg#16746 / PR fix/cli-post-phase1d-cleanup):**
rename stubs are `hidden=True` by default on the click.Command — they stay
*invokable* (still hard-error with the canonical message) but do not appear
in `scitex-orochi --help` or `--help-recursive` listings. This keeps the
top-level help clean (24 canonical nouns/groups, not 52 entries half of
which shout "Renamed"). Tests pin the invariant in
`tests/cli/test_post_phase1d_cleanup.py`.

### 2.2 Soft, one-time-per-shell notes for non-rename drifts

For changes that are **not** renames (e.g. "this flag's semantics shifted
but the name is unchanged"), a soft note may be emitted on stderr at most
**once per shell session per command**. State is tracked via a marker
file under `$XDG_STATE_HOME/scitex-orochi/deprecation/` (24 h TTL).

**Canonical stderr format (exit unchanged):**

```
note: <short one-line instruction>.
```

Implemented by `scitex_orochi._cli._deprecation.soft_notice(command, msg)`.

### 2.3 Hard opt-out

Both the hard-error and the soft-notice paths honour the environment
variable `SCITEX_OROCHI_NO_DEPRECATION=1`:

* For **soft notes**: no notice is printed.
* For **hard renames**: the error is still printed (a misspelling cannot
  succeed just because the operator asked for quiet) but it is not
  re-emitted beyond the one-line message. The exit remains non-zero.

The opt-out is intended for long-running CI logs that archive every
invocation and genuinely don't want the repetition. It is **not** a
way to make a removed name work again.

## 3. Help-display rule: `(Available Now)` suffix (§9 of plan)

"最小限びっくり" — no verbose warnings, no red text, no popups. The only
visible change in `--help` output vs. pre-Phase-1d is a quiet
`(Available Now)` suffix next to each subcommand whose backing service
is currently reachable.

### 3.1 Rendering

```
$ scitex-orochi --help
...
Commands:
  agent      Launch / control agents           (Available Now)
  machine    Heartbeat, probe, resources       (Available Now)
  cron       Schedule daemon                   (Available Now)
  dispatch   Auto-dispatch read-only           (Available Now)
  todo       Todo listing and triage
  workspace  Manage workspaces                 (Available Now)
  docs       Browse package documentation
  skills     Browse package skills
  ...
```

### 3.2 Semantics

* Suffix is present iff the subcommand's backing service is currently
  reachable (hub HTTP for server-dependent commands, local daemon check
  for host-local commands, nothing for pure-local doc/help commands).
* Suffix drops when unreachable — that is the only signal. No error
  text, no colour flip, no `[DEGRADED]` label.
* Reachability probe runs as part of click help rendering; total wall
  budget **≤ 100 ms** (parallel probes with tight timeout).
* Commands with no service dependency (e.g. `config init`, `docs`,
  `skills`) omit the suffix entirely — no false positive.

### 3.3 Implementation

* `scitex_orochi._cli._help_availability.annotate_help_with_availability(group)`
  re-parents a click `Group` so its `format_commands` injects the suffix.
* Three probe kinds live in the same module: `HUB` (hit `/api/healthz`),
  `LOCAL_DAEMON` (launchctl / systemctl user unit), `PURE_LOCAL` (always
  omit).
* Step A wires the decorator onto the top-level group only. Step B will
  recurse into nested groups.

## 4. Flat keepers (Q5 decision, plan PR #337)

Everything is `<noun> <verb>` **except** this short, explicitly-approved
set. Nothing else may stay flat. New flat additions require a separate
plan doc.

| Flat token | Type | Why kept flat |
|---|---|---|
| `-h` / `--help` | global flag | universal CLI idiom |
| `--help-recursive` | global flag | operator convenience |
| `--version` | global flag | universal CLI idiom |
| `--json` | global flag | pipes into every subcommand's output |
| `mcp start` | subcommand | external contract with MCP-client configs that reference this literal path |

Previously-proposed flat keepers (`doctor`, `init`, `fleet`, `listen`,
`login`, `launch`, `deploy`, `report`) all move under proper nouns per
§1.1.

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

See the adapter pattern (Django settings) in the full text preserved in
git history if you need the detailed framework-interop rationale.

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
