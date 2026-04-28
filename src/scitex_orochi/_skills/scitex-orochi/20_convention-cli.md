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

## Continued in

- [`56_convention-cli-extras.md`](56_convention-cli-extras.md)
