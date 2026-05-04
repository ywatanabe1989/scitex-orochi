---
description: |
  [TOPIC] CLI output, flags, help, exit codes
  [DETAILS] Part of the scitex-orochi CLI conventions skill (split for SK401 budget). See companion 57_/58_ leaves and the parent 55_ overview.
tags: [scitex-orochi-convention-cli-output]
---

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
