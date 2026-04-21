# CLI Refactor Plan — Noun-Verb Restructure + Deprecation Strategy

- Status: draft, awaiting approval
- Origin: lead msg#16500, ywatanabe msg#16497
- Target package: `scitex-orochi` (primary); `scitex-agent-container` (sister)
- Authored: 2026-04-22
- Scope: this document only; NO implementation until approved
- Reviewers: ywatanabe, lead, head-{mba,ywata-note-win,spartan,nas}

## 0. TL;DR

Migrate `scitex-orochi` top-level CLI from mixed verb-noun + hyphenated
forms to a consistent noun-verb subcommand tree. Maintain every current
name as an alias for 3 months with a one-time-per-shell deprecation
warning, then drop in v0.17. Sister package `scitex-agent-container`
(`sac`) is already closer to noun-verb but has 4 verb-only commands
needing the same treatment.

Five review-sized PRs (doc-first → skeleton → move+alias → tests →
help/docs refresh). No `_main.py` conflicts with `ts-migration-v2`.

## 1. Complete CLI Inventory

### 1.1 `scitex-orochi` (v0.14.0) — 44 registered leaves

Entry point: `scitex_orochi._cli:main` (`pyproject.toml:64`).
Dispatcher: `src/scitex_orochi/_cli/_main.py`.
Commands dir: `src/scitex_orochi/_cli/commands/*.py`.

| # | Current name | Shape | Args | `--json` | `--dry-run` | Defined in |
|---|---|---|---|---|---|---|
| 1 | `agent-launch` | verb-noun | `NAME?` | yes | no | `agent_cmd/_launch.py` |
| 2 | `agent-restart` | verb-noun | `NAME?` | yes | no | `agent_cmd/_restart.py` |
| 3 | `agent-status` | verb-noun | — | yes | no | `agent_cmd/_status.py` |
| 4 | `agent-stop` | verb-noun | `NAME?` | yes | no | `agent_cmd/_stop.py` |
| 5 | `list-agents` | verb-noun | — | yes | no | `query_cmd.py` |
| 6 | `show-status` | verb-noun | — | yes | no | `query_cmd.py` |
| 7 | `list-channels` | verb-noun | — | yes | no | `query_cmd.py` |
| 8 | `list-members` | verb-noun | — | yes | no | `query_cmd.py` |
| 9 | `show-history` | verb-noun | `CHANNEL` | yes | no | `query_cmd.py` |
| 10 | `send` | verb | `CHANNEL MESSAGE` | yes | yes | `messaging_cmd.py` |
| 11 | `listen` | verb | `--channel` | yes | no | `messaging_cmd.py` |
| 12 | `login` | verb | `--name --channels` | yes | no | `messaging_cmd.py` |
| 13 | `join` | verb | `CHANNEL` | yes | yes | `messaging_cmd.py` |
| 14 | `create-workspace` | verb-noun | `NAME` | yes | yes | `workspace_cmd.py` |
| 15 | `delete-workspace` | verb-noun | `ID` | yes | yes | `workspace_cmd.py` |
| 16 | `list-workspaces` | verb-noun | — | yes | no | `workspace_cmd.py` |
| 17 | `create-invite` | verb-noun | `WS_ID` | yes | yes | `workspace_cmd.py` |
| 18 | `list-invites` | verb-noun | `WS_ID` | yes | no | `workspace_cmd.py` |
| 19 | `serve` | verb | — | no | no | `server_cmd.py` |
| 20 | `setup-push` | verb-noun | `--output --force` | yes | yes | `server_cmd.py` |
| 21 | `doctor` | noun | — | yes | no | `doctor_cmd.py` |
| 22 | `init` | verb | `--force` | yes | yes | `init_cmd.py` |
| 23 | `launch master` | noun-verb | `NAME?` | yes | no | `launch_cmd.py` |
| 24 | `launch head` | noun-verb | `NAME` | yes | no | `launch_cmd.py` |
| 25 | `launch all` | noun-verb | — | yes | no | `launch_cmd.py` |
| 26 | `deploy stable` | noun-verb | — | no | yes | `deploy_cmd.py` |
| 27 | `deploy dev` | noun-verb | — | no | yes | `deploy_cmd.py` |
| 28 | `deploy status` | noun-verb | — | yes | no | `deploy_cmd.py` |
| 29 | `stop` | verb | `NAME? --all --force` | no | no | `stop_cmd.py` |
| 30 | `fleet` | noun | — | yes | no | `fleet_cmd.py` |
| 31 | `heartbeat-push` | verb-noun | `NAME? --all` | yes | no | `heartbeat_cmd.py` |
| 32 | `docs list` | noun-verb | — | yes | no | `docs_cmd.py` |
| 33 | `docs get` | noun-verb | `NAME` | no | no | `docs_cmd.py` |
| 34 | `skills list` | noun-verb | — | yes | no | `skills_cmd.py` |
| 35 | `skills get` | noun-verb | `NAME` | no | no | `skills_cmd.py` |
| 36 | `skills export` | noun-verb | `--output` | no | no | `skills_cmd.py` |
| 37 | `report activity` | noun-verb | `--tool --task` | implicit | no | `report_cmd.py` |
| 38 | `report stuck` | noun-verb | `--reason` | implicit | no | `report_cmd.py` |
| 39 | `report heartbeat` | noun-verb | — | implicit | no | `report_cmd.py` |
| 40 | `host-identity show` | noun-verb | — | yes | no | `host_identity_cmd.py` |
| 41 | `host-identity init` | noun-verb | `--host` | yes | yes | `host_identity_cmd.py` |
| 42 | `host-identity check` | noun-verb | `HOST` | yes | no | `host_identity_cmd.py` |
| 43 | `cron start` | noun-verb | `--config --foreground` | yes | yes | `cron_cmd.py` |
| 44 | `cron stop` | noun-verb | `--force` | yes | no | `cron_cmd.py` |
| 45 | `cron list` | noun-verb | — | yes | no | `cron_cmd.py` |
| 46 | `cron run` | noun-verb | `NAME` | yes | yes | `cron_cmd.py` |
| 47 | `cron status` | noun-verb | `--job` | yes | no | `cron_cmd.py` |
| 48 | `cron reload` | noun-verb | — | yes | no | `cron_cmd.py` |
| 49 | `machine heartbeat send` | noun-verb | — | yes | no | `machine_cmd.py` |
| 50 | `machine heartbeat status` | noun-verb | — | yes | no | `machine_cmd.py` |
| 51 | `host-liveness probe` | noun-verb | `--dry-run --yes` | yes | yes | `host_liveness_cmd.py` |
| 52 | `hungry-signal check` | noun-verb | `--dry-run --yes` | yes | yes | `hungry_signal_cmd.py` |
| 53 | `chrome-watchdog check` | noun-verb | `--threshold` | yes | no | `chrome_watchdog_cmd.py` |
| 54 | `disk reaper-dry-run` | noun-verb | `--yes` | yes | implicit | `disk_cmd.py` |
| 55 | `disk pressure-probe` | noun-verb | `--warn-pct --crit-pct` | yes | no | `disk_cmd.py` |

Total: 55 leaf subcommands (44 top-level entries in `_main.py`; 55 counting
already-grouped leaves under `docs`, `skills`, `cron`, `launch`, `deploy`,
`report`, `host-identity`, `machine heartbeat`, `host-liveness`,
`hungry-signal`, `chrome-watchdog`, `disk`). The 44 vs 54 spec in msg#16500
counted top-level registrations; this table counts every leaf.

Exit codes: 0 ok; 1 generic failure; 2 usage; some host-ops use 3+
(`disk pressure-probe` — see `disk_cmd.py`, `host-liveness probe`).

### 1.2 `scitex-agent-container` / `sac` — 25 leaves

Entry point: `scitex_agent_container.cli:main` (`pyproject.toml:63-64`).
Dispatcher: `src/scitex_agent_container/cli_pkg/_main.py`.

| # | Current name | Shape | Args | `--json` | Defined in |
|---|---|---|---|---|---|
| 1 | `start` | verb | `CONFIG? --force` | implicit | `lifecycle_cmds.py` |
| 2 | `stop` | verb | `NAME? --all` | implicit | `lifecycle_cmds.py` |
| 3 | `restart` | verb | `NAME` | implicit | `lifecycle_cmds.py` |
| 4 | `cleanup` | verb | — | implicit | `lifecycle_cmds.py` |
| 5 | `status` | noun | `NAME?` | yes | `status_cmds.py` |
| 6 | `list` | verb | `--json` | yes | `status_cmds.py` |
| 7 | `health` | noun | `NAME` | yes | `status_cmds.py` |
| 8 | `inspect` | verb | `NAME` | yes | `status_cmds.py` |
| 9 | `find` | verb | `CAPABILITY` | yes | `info_cmds.py` |
| 10 | `logs` | noun | `NAME` | implicit | `info_cmds.py` |
| 11 | `attach` | verb | `NAME` | no | `info_cmds.py` |
| 12 | `list-python-apis` | verb-noun | `-v` | no | `info_cmds.py` |
| 13 | `check` | verb | `CONFIG_PATH` | no | `build_cmds.py` |
| 14 | `validate` | verb | `CONFIG_PATH` | no | `build_cmds.py` |
| 15 | `build` | verb | `--runtime` | no | `build_cmds.py` |
| 16 | `snapshot` | verb | `--agent` | yes | `snapshot_cmds.py` |
| 17 | `hook-event` | verb-noun | `KIND` | no | `hook_cmds.py` |
| 18 | `render-sbatch` | verb-noun | `NAME_OR_PATH` | no | `render_cmds.py` |
| 19 | `render-attach` | verb-noun | `NAME_OR_PATH` | no | `render_cmds.py` |
| 20 | `probe-network` | verb-noun | `--agent` | yes | `probe_cmds.py` |
| 21 | `quota-watch` | verb-noun | `--threshold` | yes | `account_cmds.py` |
| 22 | `account save/list/delete/switch` | noun-verb | `NAME?` | yes | `account_cmds.py` |
| 23 | `actions run` | noun-verb | `ACTION_NAME` | yes | `action_cmds.py` |
| 24 | `actions query` | noun-verb | `--agent` | yes | `action_cmds.py` |
| 25 | `actions stats` | noun-verb | `--agent` | yes | `action_cmds.py` |
| 26 | `actions purge` | noun-verb | `--keep-last` | yes | `action_cmds.py` |

Existing noun groups: `account`, `actions`. Verb-only leaves to reshape:
14 (`start`, `stop`, `restart`, `cleanup`, `list`, `health`, `inspect`,
`find`, `logs`, `attach`, `check`, `validate`, `build`, `snapshot`).
Hyphenated verb-nouns to reshape: 6 (`list-python-apis`, `hook-event`,
`render-sbatch`, `render-attach`, `probe-network`, `quota-watch`).

### 1.3 `scitex` core CLI

`scitex-dev` has its own CLI (`scitex skills …`, `scitex mcp …`) per
`convention-cli.md` reference, but that lives in a separate repo
(scitex-dev) and is **out of scope** for this plan. A parallel refactor
there can follow the same protocol if lead approves.

No other CLI surfaces found in scitex-orochi:
- `scitex-orochi-server` — internal, reads no flags beyond env
- `scitex-orochi-mcp` — MCP stdio server, no subcommands

## 2. Proposed Noun-Verb Mapping

### 2.1 `scitex-orochi` (55 current leaves → 15 noun groups)

| Current name | New name | Alias kept? | Deprecation status |
|---|---|---|---|
| `agent-launch` | `agent launch` | yes (3 mo) | deprecated 2026-04-22 |
| `agent-restart` | `agent restart` | yes (3 mo) | deprecated 2026-04-22 |
| `agent-status` | `agent status` | yes (3 mo) | deprecated 2026-04-22 |
| `agent-stop` | `agent stop` | yes (3 mo) | deprecated 2026-04-22 |
| `list-agents` | `agent list` | yes (3 mo) | deprecated 2026-04-22 |
| `list-channels` | `channel list` | yes (3 mo) | deprecated 2026-04-22 |
| `join` | `channel join` | yes (3 mo) | deprecated 2026-04-22 |
| `show-history` | `channel history` | yes (3 mo) | deprecated 2026-04-22 |
| `list-members` | `channel members` | yes (3 mo) | deprecated 2026-04-22 |
| `create-workspace` | `workspace create` | yes (3 mo) | deprecated 2026-04-22 |
| `delete-workspace` | `workspace delete` | yes (3 mo) | deprecated 2026-04-22 |
| `list-workspaces` | `workspace list` | yes (3 mo) | deprecated 2026-04-22 |
| `create-invite` | `invite create` | yes (3 mo) | deprecated 2026-04-22 |
| `list-invites` | `invite list` | yes (3 mo) | deprecated 2026-04-22 |
| `send` | `message send` | yes (3 mo) | deprecated 2026-04-22 |
| *(new)* | `message react add` | — | new 2026-04-22 |
| *(new)* | `message react remove` | — | new 2026-04-22 |
| `listen` | `message listen` (or keep top-level?) | yes (3 mo) | **decision ask** |
| `heartbeat-push` | `machine heartbeat send` (already exists at #49) | merge: keep `machine heartbeat send` canonical; alias `heartbeat-push` | deprecated 2026-04-22 |
| `machine heartbeat send` | `machine heartbeat send` | — (already canonical) | unchanged |
| `machine heartbeat status` | `machine heartbeat status` | — | unchanged |
| *(new)* | `machine resources show` | — | new 2026-04-22 |
| `cron start` | `cron start` | — | unchanged |
| `cron stop` | `cron stop` | — | unchanged |
| `cron list` | `cron list` | — | unchanged |
| `cron run` | `cron run` | — | unchanged |
| `cron status` | `cron status` | — | unchanged |
| `cron reload` | `cron reload` | — | unchanged |
| `disk reaper-dry-run` | `disk reaper-dry-run` | — | unchanged (keep hyphenated leaf; semantically a single verb) |
| `disk pressure-probe` | `disk pressure-probe` | — | unchanged (same reason) |
| `host-liveness probe` | `host-liveness probe` | — | unchanged |
| `hungry-signal check` | `hungry-signal check` | — | unchanged |
| `chrome-watchdog check` | `chrome-watchdog check` | — | unchanged |
| *(new, read-only)* | `dispatch status` | — | new 2026-04-22 |
| *(new, read-only)* | `dispatch history` | — | new 2026-04-22 |
| *(new)* | `todo list` | — | new 2026-04-22 |
| *(new)* | `todo next` | — | new 2026-04-22 |
| *(new)* | `todo triage` | — | new 2026-04-22 |
| `setup-push` | `push setup` | yes (3 mo) | deprecated 2026-04-22 |
| *(new)* | `push send` | — | new 2026-04-22 |
| `serve` | `server start` | yes (3 mo) | deprecated 2026-04-22 |
| *(new)* | `server status` | — | new 2026-04-22 |
| `doctor` | `doctor` | — (top-level keeper) | unchanged |
| `docs list` | `docs list` | — | unchanged |
| `docs get` | `docs get` | — | unchanged |
| `init` | `init` | — (top-level keeper) | unchanged |
| `skills list` | `skills list` | — | unchanged |
| `skills get` | `skills get` | — | unchanged |
| `skills export` | `skills export` | — | unchanged |
| `fleet` | `fleet` | — (top-level keeper) | unchanged |
| `deploy stable` | `deploy stable` | — | unchanged |
| `deploy dev` | `deploy dev` | — | unchanged |
| `deploy status` | `deploy status` | — | unchanged |
| `launch master` | `launch master` | — | unchanged |
| `launch head` | `launch head` | — | unchanged |
| `launch all` | `launch all` | — | unchanged |
| `report activity` | `report activity` | — | unchanged |
| `report stuck` | `report stuck` | — | unchanged |
| `report heartbeat` | `report heartbeat` | — | unchanged |
| `listen` | **decision ask** — keep top-level OR move under `message` | tbd | tbd |
| `login` | **decision ask** — keep top-level OR move under `auth login` | tbd | tbd |
| `stop` (fleet-scope) | `fleet stop` (move under `fleet` group) | yes (3 mo) | deprecated 2026-04-22 |
| `host-identity show/init/check` | `host-identity show/init/check` | — | unchanged |

### 2.2 Decision summary — counts

- **Rename (old → new, alias kept 3 mo):** 19
  (`agent-*` x4, `list-agents`, `list-channels`, `join`, `show-history`,
  `list-members`, `create-workspace`, `delete-workspace`, `list-workspaces`,
  `create-invite`, `list-invites`, `send`, `heartbeat-push`, `setup-push`,
  `serve`, `stop`)
- **Unchanged (already noun-verb or kept top-level):** 28
  (`doctor`, `init`, `fleet`, `docs {list,get}`, `skills {list,get,export}`,
  `launch {master,head,all}`, `deploy {stable,dev,status}`,
  `report {activity,stuck,heartbeat}`, `host-identity {show,init,check}`,
  `cron {start,stop,list,run,status,reload}`, `machine heartbeat {send,status}`,
  `host-liveness probe`, `hungry-signal check`, `chrome-watchdog check`,
  `disk {reaper-dry-run,pressure-probe}`)
- **New (added in this refactor):** 10
  (`message react add`, `message react remove`, `machine resources show`,
  `dispatch status`, `dispatch history`, `todo list`, `todo next`,
  `todo triage`, `push send`, `server status`)
- **Pending decision:** 2 (`listen`, `login` — keep top-level vs move)

New groups introduced: `message`, `channel`, `workspace`, `invite`,
`dispatch`, `todo`, `push`, `server`, `agent` (formerly hyphen forms).

### 2.3 `scitex-agent-container` (`sac`)

Separate follow-up. Proposed mapping:

| Current | New | Alias? |
|---|---|---|
| `start` | `agent start` | yes |
| `stop` | `agent stop` | yes |
| `restart` | `agent restart` | yes |
| `cleanup` | `agent cleanup` | yes |
| `list` | `agent list` | yes |
| `status` | `agent status` | yes |
| `health` | `agent health` | yes |
| `inspect` | `agent inspect` | yes |
| `attach` | `agent attach` | yes |
| `logs` | `agent logs` | yes |
| `find` | `capability find` | yes |
| `snapshot` | `agent snapshot` | yes |
| `check` | `config check` | yes |
| `validate` | `config validate` | yes |
| `build` | `config build` | yes |
| `list-python-apis` | `config list-python-apis` | yes |
| `hook-event` | `hook event` | yes |
| `render-sbatch` | `render sbatch` | yes |
| `render-attach` | `render attach` | yes |
| `probe-network` | `probe network` | yes |
| `quota-watch` | `quota watch` | yes |
| `account {save,list,delete,switch}` | unchanged | — |
| `actions {run,query,stats,purge}` | unchanged | — |

Not blocking this plan — surfaces the target shape. Separate PR per msg#16500.

## 3. Implementation Order (5 review-sized PRs)

Each PR is self-contained; rollback = `git revert <hash>` on that one PR.

| PR | Title | Scope | Est. LoC | Can be reverted independently? |
|---|---|---|---|---|
| **A (this doc)** | `docs(cli): refactor plan (msg#16500)` | plan markdown only; no code | ~400 | yes |
| **B** | `docs(cli): update convention-cli.md to canonical noun-verb` | update `src/scitex_orochi/_skills/scitex-orochi/convention-cli.md` only | ~80 | yes |
| **C** | `feat(cli): add noun-verb group skeleton + new leaves` | new groups `agent`, `channel`, `workspace`, `invite`, `message`, `push`, `server`, `dispatch`, `todo` as Click groups; each hosts placeholders that delegate into existing implementations (no code moved yet) | ~350 + tests | yes |
| **D** | `feat(cli): route aliases → new forms with deprecation warning` | register every old name as a thin wrapper that emits deprecation-stderr then calls the new impl; gate on `SCITEX_OROCHI_NO_DEPRECATION=1` | ~220 + tests | yes |
| **E** | `docs(cli): refresh help text, skills, SKILL.md, README snippets` | update examples in epilogs + all `.md` docs grepped in §5 | ~300 non-code | yes |

PR-A is this document. PR-B opens only after PR-A approved.

### 3.1 Dependency graph

```
A (plan)  ─────────▶  B (convention)  ─────────▶  C (skeleton)
                                                       │
                                                       ▼
                                                  D (alias + warn)
                                                       │
                                                       ▼
                                                  E (help/docs)
```

### 3.2 Rollback policy

If any PR reveals a design issue, revert and re-plan before the next.
Aliases in PR-D are the reversible layer — if one breaks a downstream
consumer we re-add the old name at top level with no warning.

## 4. Test Coverage Plan (for PR-D)

### 4.1 Alias equivalence matrix

For every alias in §2.1 row with "yes (3 mo)":

```
old_cmd_stdout, old_cmd_exit = run(f"scitex-orochi {old_form} {args}")
new_cmd_stdout, new_cmd_exit = run(f"scitex-orochi {new_form} {args}")
assert old_cmd_stdout == new_cmd_stdout
assert old_cmd_exit == new_cmd_exit
```

19 rename aliases × ≥ 1 representative invocation each ≈ 19+ equivalence
tests. Parametrise over a fixture of `(old, new, args)` tuples.

### 4.2 Deprecation warning checks

- Running `scitex-orochi <old-form>` emits a warning on **stderr**, not
  stdout (stdout-purity preserved for `--json | jq`).
- Setting `SCITEX_OROCHI_NO_DEPRECATION=1` suppresses the warning.
- Warning text includes the new form: e.g. `"'list-agents' is deprecated
  — use 'agent list' instead (removed in v0.17)"`.
- One-time-per-shell semantics (if we pick that mode — see §6):
  second invocation in the same process OR with the same
  `$SCITEX_OROCHI_DEPR_SEEN` env cache is silent.

### 4.3 CI time budget

- Equivalence matrix is parametrised, each test is a `CliRunner.invoke`
  (no network) ≤ 100 ms → ≈ 2 s total for 20 pairs.
- Acceptable: +2 s on the `scitex-orochi` unit suite. Hub suite
  unaffected.

### 4.4 Out of scope for PR-D

- No changes to hub-side API tests (`hub/tests/…`).
- No integration tests that hit a live server — all CLI tests use
  `click.testing.CliRunner` offline.

## 5. Risk Evaluation

### 5.1 Merge-conflict risk: `_cli/_main.py`

`_main.py` is the single file that registers every subcommand. It will
be touched by PR-C, PR-D, and any parallel feature work (e.g. a new
`dispatch` leaf). Mitigation:

- PRs B → C → D → E are **serial**, not parallel.
- Each PR rebases on `develop` before opening and runs `pytest -x` locally.
- No parallel CLI feature PR may merge between PR-C and PR-D without
  explicit lead coordination.

`ts-migration-v2` branch touches `src/scitex_orochi/_ts/`, not `_cli/` —
confirmed by file-path inspection. No conflict expected.

### 5.2 `cron.yaml` references

`deployment/host-setup/orochi-cron/cron.yaml.example` uses the old
hyphenated forms (lines 30, 37, 45, 52, 59). These already match the
`heartbeat-push`, `host-liveness probe`, `hungry-signal check`,
`chrome-watchdog check`, `disk pressure-probe` etc. Of these, only
`heartbeat-push` becomes an alias (→ `machine heartbeat send`); the rest
survive unchanged. Mitigation: update the example in the **same** PR
that deprecates `heartbeat-push` (PR-D).

Any operator-installed `~/.scitex/orochi/cron.yaml` continues to work
under the 3-month alias window. The daemon's command-string pipe
already runs through a shell, so the alias resolves naturally.

### 5.3 Downstream scripts / skill docs

Files that reference the old forms (to be refreshed in PR-E):

- `docs/reference.md`
- `docs/getting-started.md`
- `docs/architecture.md`
- `docs/sphinx/index.rst`
- `docs/sphinx/quickstart.rst`
- `docs/sphinx/installation.rst`
- `src/scitex_orochi/_skills/scitex-orochi/SKILL.md`
- `src/scitex_orochi/_skills/scitex-orochi/convention-cli.md` (PR-B)
- `src/scitex_orochi/_skills/scitex-orochi/agent-deployment.md`
- `src/scitex_orochi/_skills/scitex-orochi/agent-health-check.md`
- `orochi-config.yaml` (comments only)

Ecosystem files outside this repo (dotfiles, `agent-container` skills,
head READMEs): tracked as a follow-up issue, not blocking.

### 5.4 Third-party consumers

- **systemd / launchd units:** installed by `scripts/client/install-*.sh`
  — all currently reference the hyphenated forms and therefore hit the
  alias layer during the deprecation window. OK.
- **Claude Code hooks:** call `scitex-orochi report activity …` — no
  change, that command is already noun-verb.
- **Operator runbooks:** see §5.3 docs list. PR-E refresh.
- **MCP tools:** `mcp__scitex-orochi__*` names are independent of CLI
  names — no action needed.

### 5.5 Breakage window

Window `v0.15` → `v0.17`: both old and new forms work; warning printed.
At `v0.17` (estimated 2026-07-22 ≈ 3 months out): alias removal PR.
`v0.18` onwards: noun-verb only.

## 6. Decision Asks (blocking PR-B implementation)

Resolve these before PR-B opens. Each has a recommendation.

### Q1 — Alias maintenance period

- 3 months (2026-07-22 hard cutoff at v0.17)?
- 6 months (longer, friendlier to external consumers)?
- Until v1.0 (open-ended)?
- **Recommendation:** 3 months. Orochi has a small operator pool
  (us + a few) and fast release cadence; 3 months is ≈ 3 minor releases.

### Q2 — Deprecation warning style

- Every invocation prints to stderr (loud, annoying, obvious)?
- One-time-per-shell (tracked via `$SCITEX_OROCHI_DEPR_SEEN` marker
  file in `$XDG_CACHE_HOME` with 24 h TTL)?
- Muted by default, only shown under `--verbose`?
- **Recommendation:** one-time-per-shell (tracked via a cache marker
  keyed on `(user, shell_pid_or_session, command_name)`). Every-call
  noise breaks pipes; muted is too easy to miss. Opt-out via
  `SCITEX_OROCHI_NO_DEPRECATION=1` (hard off) in all modes.

### Q3 — `convention-cli.md` location

- Keep at `src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`
  (current, consumed by the skill system)?
- Move to `docs/convention-cli.md` (discoverable from GitHub)?
- Duplicate in both (sync risk)?
- **Recommendation:** keep the canonical file at the current
  `_skills/` path (skills authority), add a symlink or short pointer
  page at `docs/convention-cli.md` for web discoverability.

### Q4 — PR-B through PR-E execution

- One monolithic PR (plan + skeleton + alias + tests + docs)?
- Five micro-PRs as sketched in §3?
- **Recommendation:** five micro-PRs. Each is review-sized (< 400 LoC
  of new code). Monolith would be > 1500 LoC and hard to roll back.

### Q5 — Top-level keeper list

- Keep these as top-level (no noun prefix) for ergonomics:
  `doctor`, `init`, `fleet`, `listen`, `login`, `launch`, `deploy`,
  `report`?
- Or force everything under a noun (`health doctor`, `fleet init`,
  `fleet listen`, `auth login`, `cluster launch`, `cluster deploy`,
  `telemetry report`)?
- **Recommendation:** keep the 8 listed as top-level. These are
  top-of-mind operator verbs; forcing a prefix is churn without
  ergonomic benefit. Document the exception list in `convention-cli.md`.

### Q6 — `sac` refactor coupling

- Do `sac` renames in the same 5-PR cycle?
- Or defer to a parallel plan doc?
- **Recommendation:** defer. `sac` is a separate repo with its own
  release cadence; coupling doubles blast radius. File a companion plan
  after this one lands.

## 7. Approval Criteria

This PR (PR-A) is ready to merge when:

- [ ] ywatanabe answers Q1–Q6 inline on the PR
- [ ] lead approves the 5-PR sequencing
- [ ] At least one head-* reviewer (not the author) signs off on the
      inventory tables
- [ ] No unresolved objections to the renames in §2.1
- [ ] Deprecation window and warning style are pinned (Q1 + Q2)

Once merged, PR-B opens within 24 h using the approved decisions as
inputs.

## 8. Appendix — File inventory for PR-E

Generated 2026-04-22 from the working tree at
`origin/develop@5c9b345`. Will be re-run at PR-E open time.

```
docs/reference.md
docs/getting-started.md
docs/architecture.md
docs/sphinx/index.rst
docs/sphinx/quickstart.rst
docs/sphinx/installation.rst
src/scitex_orochi/_skills/scitex-orochi/SKILL.md
src/scitex_orochi/_skills/scitex-orochi/convention-cli.md
src/scitex_orochi/_skills/scitex-orochi/agent-deployment.md
src/scitex_orochi/_skills/scitex-orochi/agent-health-check.md
orochi-config.yaml
deployment/host-setup/orochi-cron/cron.yaml.example
src/scitex_orochi/_cli/commands/messaging_cmd.py (help epilogs)
src/scitex_orochi/_cli/commands/query_cmd.py (help epilogs)
src/scitex_orochi/_cli/commands/workspace_cmd.py (help epilogs)
src/scitex_orochi/_cli/commands/server_cmd.py (help epilogs)
src/scitex_orochi/_cli/commands/agent_cmd/_*.py (help epilogs)
```

## 9. Help-display policy (lead msg#16514, ywatanabe msg#16512)

"最小限びっくり" — no verbose warnings, no red text, no popups. The only
visible change in `--help` output is a quiet `(Available Now)` suffix
next to each subcommand that is currently reachable.

### Rendering rule
```
scitex-orochi --help:
  agent      Launch / control agents           (Available Now)
  machine    Heartbeat, probe, resources       (Available Now)
  cron       Schedule daemon                   (Available Now)
  dispatch   Auto-dispatch read-only           (Available Now)
  todo       Todo listing and triage
  workspace  Manage workspaces                 (Available Now)
  ...
```

- `(Available Now)` suffix present iff the subcommand's backing
  service is currently reachable (hub `/api/*` for server-dependent
  commands, local daemon ping for host-local commands, nothing for
  pure-local doc/help commands).
- Suffix drops when unreachable — that is the only signal. No error
  text, no colour flip, no `[DEGRADED]` label.
- Reachability probe runs as a click eager callback on `--help`; must
  short-circuit at ≤100 ms total (parallel probes with tight
  timeout) so `--help` stays responsive.
- For commands with no service dependency (e.g. `init`, `docs`,
  `skills`), the suffix is omitted entirely — no false positive.

### Deprecation warning style (Q2 decision integrating msg#16514)
One-time-per-shell, stderr only, single line. Example:
```
note: `scitex-orochi list-agents` is deprecated; use `scitex-orochi agent list`.
```
No multi-line banner, no colour, no link. Same "最小限びっくり"
principle as the help suffix. Opt-out via `SCITEX_OROCHI_NO_DEPRECATION=1`.

### Why this matters for §3 Implementation order
The `(Available Now)` suffix layer lands in **Step A** so it's in
place before any rename — otherwise the alias layer has no way to
signal degraded state quietly. Suffix implementation is shared
infrastructure used by both new and alias command paths.

## 10. ywatanabe decisions (2026-04-22, msg#16533 / msg#16546)

Locking in the approval asks from §6:

### Q1 — Alias period
**Pivot**: not a grace period. Deprecated commands **hard-error at
call time** with a one-line fix instruction. Example stderr output:
```
error: `scitex-orochi list-agents` was renamed to `scitex-orochi agent list`.
```
Exit non-zero. No silent fallback to the new command. This is the
"soon" policy — immediate rename, no grace period.

### Q2 — Warning style
**b) one-time-per-shell**, single stderr line, opt-out via
`SCITEX_OROCHI_NO_DEPRECATION=1`. Integrated with Q1: the hard-error
above is not a warning but a terminal error — the "one-time" rule
applies to any soft notes we emit on non-renamed commands (e.g.
feature drifts), not to hard renames.

### Q3 — `convention-cli.md` location
**a AND b**: canonical at `src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`,
with a short pointer in `docs/cli.md` that `include`s or links to the
canonical copy. Single source of truth, two discovery paths.

### Q4 — PR granularity
**a) 1 PR.** All rename + alias wrappers + tests + convention-cli +
help-suffix layer land together. Easier to review consistency,
avoids partial-state regressions.

### Q5 — Flat keepers
Force `<noun> <verb>` for everything **except**:
- `-h` / `--help`
- `--help-recursive`
- `--version`
- `--json` (global flag)
- `mcp start` (keep flat — external contract with MCP client
  configs that reference this literal path)

Previously-proposed flat keepers (`doctor`, `init`, `fleet`, `listen`,
`login`, `launch`, `deploy`, `report`) all move under proper nouns:
- `doctor` → `system doctor`
- `init` → `config init`
- `fleet` → `agent fleet-list`
- `listen` → `message listen`
- `login` → `auth login`
- `launch` → `agent launch` (already planned)
- `deploy` → `server deploy`
- `report` → `hook report`

### Q6 — sac coupling
**Not decided yet by ywatanabe.** Defaulting to §6 Q6 recommended:
scitex-orochi only in this refactor, sac gets a sister plan PR after
this lands.

## 11. Skill discoverability (msg#16546)

ywatanabe flagged: "the noun-verb convention lives in a skill that's
hard to find". Fix in the same refactor:

1. `docs/cli.md` gains a visible pointer in the repo README + any
   top-level agent-boot context files.
2. The `--help` output of `scitex-orochi` (top-level, no subcommand)
   ends with: `see <URL> for the noun-verb convention` pointing at
   `docs/cli.md`.
3. `src/scitex_orochi/_skills/SKILL_INDEX.md` (add if missing) lists
   every skill under this package by one-line role so a fleet agent
   can grep for "cli convention" and land in the right place.
4. head-ywata-note-win's concurrent work (msg#16558) consolidates the
   cross-package convention skill; this PR cross-references that
   canonical location rather than duplicating it.

---

End of plan. Q1–Q5 locked. Q6 pending ywatanabe. Implementation PR
opens once Q6 is answered (or auto-defaults to "defer sac" after a
reasonable wait).
