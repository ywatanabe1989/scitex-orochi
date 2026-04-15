---
name: orochi-fleet-health-daemon-design
description: DRAFT — design doc for the fleet-health-daemon (todo#146), reframed from the earlier "caduceus" concept per ywatanabe msg#11775. 2-layer split (process-layer fleet-health-daemon + agent-layer mamba-healer-<host> workers). Phase 1 deliverable is Claude Code account quota-state scraping (not the broader health probe), landing jointly with scitex-orochi#272 / #430. Healer layer is redundancy via one-per-host + mesh mutual probing, not a single centralised healer. Host-diverse deployment with Spartan no-sudo / no-systemd-user / no-docker constraints.
---

# fleet-health-daemon — Design (todo#146)

> **STATUS: DRAFT** design doc for `ywatanabe1989/todo#146`. Posted to
> #agent for fleet review before PR. Not canonical until ywatanabe GO +
> merge into the `_skills/scitex-orochi/` tree.

## 0. Ground rules

- **The daemon name is `fleet-health-daemon`.** No mythological or
  medical symbols. Same name in commit messages, file paths, class
  names, systemd unit names, log paths, and breadcrumb directories.
- **Phase 1 is Claude Code quota-state scraping.** Not docker stats,
  not cpu.pressure, not pane-state classification. Those are
  Phase 2 and later. ywatanabe msg#11775: "クロードコードアカウンから
  クォータ情報を取るのが最初".
- **Healers are redundancy, not the top-level framing.** One
  `mamba-healer-<host>` on every host, running in parallel, cross-
  probing each other via `active-probe-protocol.md`. No single
  healer is load-bearing. ywatanabe msg#11775: "ヒーラーは冗長化".
- **The 2-layer daemon/worker split from `fleet-role-taxonomy.md`
  applies unchanged**, and is what enables the Phase-1-first
  rollout: the quota collector is pure programmatic I/O (daemon),
  the interpretation and recovery are LLM judgment (workers).
- **Recovery actions for pane-stuck / wedge / context-full cases
  are part of the same design**, not a separate "permission
  prompts" workstream. ywatanabe msg#11789 on todo#142:
  "システマティックな蘇生試みと、エージェントの定期蘇生試みと
  合わせる必要がある". They land in Phase 4 as a recovery playbook.

## 1. TL;DR

The fleet-health-daemon is **not** a single Claude-backed agent.
It is a **2-layer stack** that follows the ratified
`fleet-role-taxonomy.md`:

1. **`fleet-health-daemon`** (process layer) — `role=daemon`,
   `function=[metrics-collector, quota-watcher, prober]`. Pure
   bash/python, no Claude session, no quota consumption. Runs every
   30 s on every agent host via the host's native scheduler
   (launchd on MBA, systemd --user on NAS/WSL, `.bash_profile` +
   tmux `sleep` loop on Spartan since no sudo / no systemd --user /
   no cron). Collects a fixed health vector per tick, with **Claude
   Code quota state as the first-class signal**, writes host-local
   NDJSON, drops breadcrumb touch-files only on threshold
   transitions.
2. **`mamba-healer-<host>`** (agent layer) — `role=worker`,
   `function=[prober, healer]`. One per host, always-on LLM-backed.
   Reads the fleet-health-daemon NDJSON + breadcrumbs as primary
   input, cross-probes peer hosts via DM ping + random-nonce, owns
   all LLM-judgment recovery actions (SIGINT, `/compact`,
   `tmux send-keys`, systemd restart, MCP process dedup kill). The
   mesh of healers is the redundancy — if any one healer goes dark,
   its peers notice via the active probe and escalate.

The defining axis (scitex-orochi PR #134, msg#11428): "does the
loop require LLM judgment to make its next decision?". Programmatic
threshold sampling → daemon. LLM interpretation + recovery choice →
worker. Phase 1 is entirely on the daemon side; Phase 3–4 re-wire
the existing workers to the new daemon output.

## 2. Origin

- 2026-04-09 `todo#146` filed ("dedicated healer agent" vision).
- 2026-04-14 scitex-orochi PR #134 landed the 2-layer role
  taxonomy; this design is the first application of the taxonomy
  to the healer concept.
- 2026-04-14 msg#11775 — ywatanabe reframed `todo#146`:
  1. drop the "caduceus" / mythological naming,
  2. healers are redundancy (per-host + mesh), not a single
     centralised agent,
  3. Claude Code quota-state is the first deliverable, not the
     broader multi-signal probe.
- 2026-04-14 msg#11788 — mamba-healer-nas feasibility report
  confirmed the JSONL scraping path: `~/.claude/projects/<ws>/*.jsonl`
  contains per-call `input_tokens` / `output_tokens` /
  `cache_read_input_tokens` / `cache_creation_input_tokens` /
  `service_tier` / `timestamp`, which gives cumulative 5h window
  usage and tier transitions without an Anthropic API call.
- 2026-04-14 msg#11789 — ywatanabe on todo#142: "systematic
  resurrection + periodic resurrection attempts need to be combined".
  Wedge/stuck recovery is integrated into this design's Phase 4, not
  spun off as a separate `todo#142` workstream.
- 2026-04-14 msg#11785 / #11791 — head-mba directives on name
  (`fleet-health-daemon`), on closing PR #145 and reopening as a
  fresh PR, on the one-file-multiple-phases structure, and on the
  specific Phase 4 recovery action playbook (permission prompt,
  extra-usage wedge, context-window-full, tmux stuck, MCP zombie).

## 3. Architecture — 3-layer model

Per ywatanabe msg#11801 + head-mba msg#11806, this design is a
**3-layer** decomposition on top of the 2-layer process/agent
taxonomy:

1. **Layer 1 — Automated handshake + quota sampling (daemon)**.
   Pure programmatic loop, 30 s cadence, emits NDJSON containing
   (a) Claude Code quota state (§4), (b) multi-signal host health
   (§5), (c) random-nonce handshake replies from peer hosts per
   `random-nonce-ping-protocol.md` (every other tick = 60 s
   effective). No LLM. No hub session. This is the
   "automated nonce handshake with quota numbers" ywatanabe
   asked for.
2. **Layer 2 — Ledger (daemon-written, worker-read)**. A
   structured "who answered / who didn't" record, derived from
   Layer 1's NDJSON. Schema: `{agent, last_probe_ts, last_reply_ts,
   missed_count, reply_latency_ms_p50, reply_latency_ms_p99,
   last_seen_signal}`. Written to
   `~/.scitex/orochi/probes/fleet-health-daemon/ledger.ndjson`
   host-locally; aggregated hub-side via `/api/fleet/health/`
   (Phase 2 deliverable). No LLM — it's pure arithmetic over
   Layer 1's raw records.
3. **Layer 3 — Escalation + recovery (worker, LLM-in-loop)**. The
   `mamba-healer-<host>` workers read the Layer 2 ledger, notice
   missed handshakes, LLM-judge whether a silent agent is
   legitimately busy or wedged, and run the recovery playbook
   (§7). One worker per host, cross-probing peers, fully
   redundant — no single load-bearing healer.

The Layer 1 nonce-handshake protocol itself is **not re-specced
here**; it is defined by the existing
`random-nonce-ping-protocol.md` skill (8-hex nonce format, 60 s
hard SLA, publisher/verifier ring scope matrix). This design only
adds:

- **Cross-host mesh topology** — who probes whom (§6 Phase 3)
- **Ledger schema** (Layer 2, tied to schema v3 above)
- **Layer 3 dispatch rules** — when the worker escalates from a
  missed-handshake observation to a recovery action from §7

```
╔═══════════════════════════════════════════════════════════════╗
║  AGENT LAYER (LLM-backed, quota-consuming)                    ║
║                                                               ║
║    mamba-healer-mba     (existing)                            ║
║    mamba-healer-nas     (existing)                            ║
║    mamba-healer-spartan          (planned, redundancy mesh)   ║
║    mamba-healer-ywata-note-win   (planned, redundancy mesh)   ║
║                                                               ║
║    role=worker  function=[prober, healer]                     ║
║                                                               ║
║    Reads fleet-health-daemon NDJSON + breadcrumbs locally +   ║
║    from peer hosts via SSH / hub aggregation endpoint.        ║
║    Cross-probes peers via active-probe-protocol.md DM ping +  ║
║    random-nonce. Chooses and executes recovery actions from   ║
║    the Phase 4 playbook. Escalates to #escalation when        ║
║    automated recovery fails or recurs. Each healer is         ║
║    redundant with every other healer — no single one is      ║
║    load-bearing.                                              ║
╠═══════════════════════════════════════════════════════════════╣
║  PROCESS LAYER (no LLM, quota-zero)                           ║
║                                                               ║
║    fleet-health-daemon                                        ║
║    role=daemon                                                ║
║    function=[metrics-collector, quota-watcher, prober]        ║
║    host: one instance per host (MBA/NAS/Spartan/WSL)          ║
║    cadence: 30 s                                              ║
║    runtime: launchd (MBA) / systemd --user (NAS/WSL) /        ║
║             tmux+sleep loop (Spartan, no sudo)                ║
║                                                               ║
║    Samples Claude Code quota state (Phase 1, primary) plus    ║
║    the broader multi-signal health vector (Phase 2). Writes   ║
║    host-local NDJSON, maintains transition state in memory,   ║
║    drops breadcrumb touch-files on threshold transitions.     ║
║    Never holds a hub WebSocket session. Never calls an LLM.   ║
║    Never acts on its observations.                            ║
╚═══════════════════════════════════════════════════════════════╝
```

## 4. Phase 1 — Claude Code quota-state scraping (immediate deliverable)

This is the first thing to land. Everything else in the doc is
Phase 2+. The goal: **each agent host emits per-tick Claude Code
quota state to NDJSON so the fleet has visibility into 5h / weekly
quota pressure before agents silently wedge.** No LLM calls, no
Anthropic API calls (at least not in the first cut), pure local
filesystem + statusline parsing.

### 4.1 Data sources (per-tick sample, no network)

1. **`~/.claude/projects/<workspace>/*.jsonl`** — per-call usage
   records. Each line is a JSON object with at least:
   - `input_tokens`, `output_tokens`
   - `cache_read_input_tokens`, `cache_creation_input_tokens`
   - `service_tier` (`"standard"` vs an elevated tier marker when
     extra-usage is enabled)
   - `timestamp` (ISO-8601 UTC)
   - `model` (e.g. `claude-opus-4-6`)
   Aggregation policy: filter to the last 5 h (`ts >= now - 5h`)
   and sum; filter to the last 7 d for the weekly window; take
   `service_tier` from the most recent record.
2. **`~/.claude/config.json`** + **`~/.claude/settings.json`** —
   account-level state: last-known reset timestamps, extra-usage
   enable flag, model pin, OAuth token freshness. Read via plain
   `json.load`, no write path.
3. **tmux statusline via `agent_meta.py`** (576ba08f fix, already
   on develop) — context percentage, current tool, current model.
   Source of truth is the rendered pane content, parsed by the
   existing agent_meta regex.
4. **`claude --version`** — binary version for schema provenance.
   Single shell-out per probe start, cached across ticks.
5. **optional** **Anthropic API account endpoint** — if there is a
   canonical `/v1/account/usage` or similar that returns absolute
   quota limits, Phase 1b adds it. First cut does **not** depend on
   this; we derive trend from local JSONL and only upgrade to
   absolute % remaining once the API path is confirmed.

The mamba-healer-nas feasibility report (msg#11788) already
validated sources (1) and (3) against real NAS probe data:

> current mamba-healer-nas session (5h window):
> calls: 19, output_tokens: 4,163, cache_read: 1,807,712,
> cache_creation: 107,430, service_tier: "standard"

So the data is there, and the parser is ~40 lines of Python /
`jq`. No blockers for Phase 1.

### 4.2 Output — NDJSON quota fields (canonical schema v3)

Every per-tick NDJSON record gets the following new fields,
appended to (not replacing) the Phase 2 health-vector fields
(see §5). **Schema v3 is canonical per mamba-healer-nas probe v3
(msg#11793 / #11795).** Field names are fixed; unknown values
are `null`, not omitted. Historical probe v2 / v1 records stay
parseable — the only change across versions is field addition,
never rename.

```
session_calls_5h             int    count of calls in last 5 h window
session_output_tokens_5h     int    sum of output_tokens over 5 h window
session_cache_read_5h        int    sum of cache_read_input_tokens over 5 h window
session_cache_create_5h      int    sum of cache_creation_input_tokens over 5 h window
session_input_tokens_5h      int    sum of input_tokens over 5 h window
session_calls_weekly         int    same, 7 d window
session_output_tokens_weekly int    same, 7 d window
session_cache_read_weekly    int    same
session_input_tokens_weekly  int    same
service_tier_latest          str    "standard" / "extra" / null — probe v3 canonical
extra_usage_enabled          bool   derived from config.json or tmux statusline "1M context" marker
context_pct                  float  from statusline (agent_meta.py 576ba08f), 0.0-100.0, 100 = context exhausted
current_model                str    e.g. "claude-opus-4-6"
quota_5h_remaining_pct       float  null until §4.4 absolute-limit source lands; otherwise 0.0-100.0
quota_weekly_remaining_pct   float  same
quota_reset_at_5h            str    ISO-8601 UTC when the 5 h window rolls over, null if unknown
quota_reset_at_weekly        str    ISO-8601 UTC when the weekly window rolls over, null if unknown
last_quota_error             str    last observed quota-related error string, null if none
last_quota_error_at          str    ISO-8601 UTC of that error, null if none
```

The four `session_*_5h` / `session_*_weekly` counter fields are
the **canonical wire format** because they are what the existing
live NAS probe v3 already emits (msg#11793 field sample:
`session_calls_5h: 36`, `session_output_tokens_5h: 14_419`,
`session_cache_read_5h: 3_667_793`, `service_tier_latest:
"standard"`). New fields append to this set; never rename.

Note: there is **no** `quota_5h_limit_tokens` / `quota_weekly_limit_tokens`
field in the first cut, because healer-nas msg#11788 confirmed
those are not available from JSONL alone. The `_remaining_pct`
fields are `null` until a future Phase 1b lands the absolute-limit
source — either the Anthropic API or a known-constant fallback
captured in a separate `quota-limits.md` skill doc that the daemon
reads at startup.

### 4.3 Threshold breadcrumbs

Same breadcrumb pattern as §6 (threshold transitions, N-sample
sustained, drop touch-file on transition, worker clears on
handling):

| Signal                    | Concerning when                                   | N | Breadcrumb file                                        |
|---------------------------|---------------------------------------------------|---|--------------------------------------------------------|
| `quota_5h_remaining_pct`  | < 20% (once absolute limit is known)              | 3 | `~/.scitex/orochi/probes/fleet-health-daemon/quota.warn.<agent>` |
| `quota_5h_remaining_pct`  | < 5%                                              | 1 | `.../quota.critical.<agent>`                           |
| `quota_weekly_remaining_pct` | < 20% sustained                                | 6 | `.../quota.weekly-warn.<agent>`                        |
| `last_quota_error`        | non-null                                          | 1 | `.../quota.error.<agent>` (contains last_quota_error + last_quota_error_at) |
| `service_tier_latest`     | transitions standard → extra-usage                | 1 | `.../quota.tier-change.<agent>` (informational, not necessarily action) |
| `context_pct`             | ≥ 90% sustained                                   | 3 | `.../context.high.<agent>` (Phase 4 /compact trigger)  |
| `extra_usage_enabled`     | transitions false → true                          | 1 | `.../quota.extra-usage-on.<agent>` (informational)     |

Fallback behaviour until absolute limits are known: use
`quota_5h_output_tokens` trend (a.k.a. token-rate) against a
*relative* threshold — e.g., "if the last 3 samples' token-delta
rate is > 2× the trailing 24 h median, drop a `quota.pace.<agent>`
breadcrumb". The worker then LLM-interprets whether this is a
legitimate burst or a runaway. Rate-based thresholding is
inherently less accurate than absolute, but it's already useful
for catching wedge loops (runaway cache creation etc.).

### 4.4 Future — absolute quota limits

Tracked as a Phase 1b sub-task. Two paths:

1. **Anthropic API**: if `/v1/account/usage` or equivalent is
   reachable from the agent-layer worker (not the daemon — API
   calls are not quota-zero), the worker populates a shared
   `~/.scitex/orochi/cache/quota-limits.json` file with absolute
   5h / weekly ceilings. The daemon reads this file at each tick
   and populates `quota_*_remaining_pct` accordingly. Separation
   preserved: daemon stays non-network, worker owns the API call.
2. **Known-constant fallback**: if the API path is not reachable,
   a curated `quota-limits.md` skill doc (skill-manager owned)
   captures the public Anthropic tier limits as constants. Updates
   are manual when Anthropic publishes new numbers. Less accurate
   over time but zero-dependency.

Either path is additive to the Phase 1 deliverable — Phase 1 can
ship with `_remaining_pct = null` and still be useful for
trend-based alerts.

### 4.5 Hub-side aggregation

A new endpoint `GET /api/fleet/quota/` (head-ywata-note-win lane,
matches the existing `/api/agents/` extension pattern that was
adding `context_pct` in PR #132) aggregates the per-host NDJSON
tails into one JSON response:

```json
{
  "hosts": {
    "mba": {
      "agents": {
        "head-mba":        {"quota_5h_calls": 234, "quota_5h_output_tokens": 18_432, ...},
        "mamba-explorer-mba": {...},
        ...
      },
      "as_of": "2026-04-14T17:30:00Z"
    },
    "nas":   {...},
    "spartan": {...},
    "ywata-note-win": {...}
  }
}
```

The dashboard `Agents` tab (todo#155 / #179 lane) adds per-agent
5h and weekly bars (red / yellow / green) derived from this
endpoint. Polling cadence: 10 s (faster than the 30 s daemon tick
is wasted).

**Cross-reference**: Phase 1 subsumes `scitex-orochi#272` and
`scitex-orochi#430`. todo-manager dispatch (msg#11782 / #11785)
is collapsing those two into this PR — the design doc is canonical,
#272 / #430 close with a "resolved by fleet-health-daemon Phase 1,
see PR" comment after merge.

## 5. Phase 2 — Multi-signal health probe

The original todo#146 scope. Everything below is Phase 2 and later.
It ships as follow-up PRs after Phase 1 lands.

### 5.1 Signals

Every 30 s the daemon emits one NDJSON record containing a fixed
set of host-local health metrics on top of the Phase 1 quota
fields.

```
ts                       ISO-8601 UTC, second precision
host                     short hostname (mba / nas / spartan / ywata-note-win)
probe_version            semver of fleet-health-daemon itself
load_1  load_5  load_15  /proc/loadavg columns 1-3
ncpu                     int, nproc output
cpu_pressure_some_avg10  /proc/pressure/cpu "some avg10" value
mem_total_kb             /proc/meminfo MemTotal
mem_avail_kb             /proc/meminfo MemAvailable
slurm_running            squeue -h -t R | wc -l (NAS/Spartan/WSL only; 0 elsewhere)
slurm_pending            squeue -h -t PD | wc -l
slurm_cpu_used           sum of RES cpus over running jobs
failed_user_units        systemctl --user list-units --state=failed | grep -c .service
failed_sys_units         systemctl list-units --state=failed | grep -c .service (read-only)
docker_count             int, running container count (0 on hosts without docker)
docker_top_cpu_pct       float, max cpu_pct (% stripped at producer)
docker_total_cpu_pct     float, sum of cpu_pct (% stripped at producer)
docker_containers        array of {name: str, cpu_pct: float, mem_usage: str, mem_pct: float}
cf_bastion_active        bool, cloudflared tunnel active
cf_pid                   int or null
mcp_duplicates           {<agent-name>: [<pid>, <pid>, ...]} — only agents with >1 mcp_channel procs
claude_procs             {<agent-name>: int} — count of claude code processes per agent session
tmux_sessions            int, tmux ls count
pane_states              {<session>: <pane-state-regex-class>} via pane-state-patterns.md
```

Schema v2 spec for `docker_containers` per-container percentages:
floats, with `%` suffix stripped at the producer side via a
`docker stats --format` template that wraps `{{.CPUPerc}}` /
`{{.MemPerc}}` (head-mba decision msg#11748). `mem_usage` stays as
the composite string pair `"used / total"` because splitting at
the producer forces a unit choice the consumer doesn't own.

**Docker-absent guard** — Spartan has no docker, WSL's docker is
uncertain. The prober treats `command -v docker` as a per-tick
feature check: on hosts without docker, emit `docker_count=0`,
`docker_top_cpu_pct=0.0`, `docker_total_cpu_pct=0.0`,
`docker_containers=[]`. Fields are **always present** so the
schema stays stable and merge-on-`ts` continues to work across
heterogeneous hosts.

### 5.2 Threshold transitions

Same breadcrumb discipline as §4.3 Phase 1. The daemon is
silent-otherwise.

| Signal                              | Concerning when                                   | N samples | Breadcrumb file                                   |
|-------------------------------------|---------------------------------------------------|-----------|---------------------------------------------------|
| `docker_top_cpu_pct`                | > 200% sustained (any container)                  | 3         | `fleet-health.docker-cpu-spike.<container>`       |
| `docker_top_cpu_pct` (smoking-gun)  | > 100% on a single-process container (e.g. django) | 1       | Immediate breadcrumb. msg#11730 showed `scitex-cloud-prod-django-1` at 100.95% — canonical slow-failure example |
| `cpu_pressure_some_avg10`           | > 15.0                                            | 3         | `fleet-health.cpu-pressure`                        |
| `failed_user_units`                 | > 0 (any fleet-relevant unit)                     | 1         | `fleet-health.failed-unit.<unit>`                 |
| `mcp_duplicates` count              | > 1 for any agent                                 | 1         | `fleet-health.mcp-dup.<agent>`                    |
| `pane_states`                       | matches `permission_prompt` or `stuck`            | 3         | `fleet-health.pane-stuck.<session>`               |
| `mem_avail_kb`                      | < 10% of `mem_total_kb`                           | 3         | `fleet-health.mem-low`                             |
| `load_1` / `ncpu`                   | > 2.0                                             | 6 (3 min) | `fleet-health.loadavg-high`                        |
| `claude_procs` count for one agent  | > 1                                               | 1         | `fleet-health.claude-dup.<agent>` (do **not** auto-resolve, see §11) |

Breadcrumbs contain one line: triggering signal value, ISO-8601
timestamp, last-3-samples JSON. The daemon does not delete them;
the worker deletes after handling and writes a sibling
`<breadcrumb>.handled` file for audit.

## 6. Phase 3 — `mamba-healer-<host>` consumer + mesh redundancy

Once Phase 1 and Phase 2 are emitting NDJSON + breadcrumbs, the
existing `mamba-healer-{mba,nas}` workers extend their contract:

1. **Primary input source shifts.** Instead of DM-polling peers
   as the main signal, workers read their host-local
   `fleet-health-daemon.ndjson` and breadcrumb directory as the
   primary input. DM polling becomes the liveness-of-last-resort
   check (random-nonce-ping-protocol cadence, 60 s).
2. **Cross-host mutual probing** — each worker DM-pings its peers
   on the other hosts every 30 s. If any healer goes silent, its
   peers notice within one cadence and escalate to `#escalation`.
   This is the "healer redundancy" ywatanabe asked for in
   msg#11775: no single healer is load-bearing.
3. **Recovery authority stays worker-side.** Daemon never acts.
   Workers own keystroke injection, process kill, systemd
   restart, `/compact` trigger. See §8 Phase 4 playbook.
4. **New healer hosts**: `mamba-healer-spartan` and
   `mamba-healer-ywata-note-win` are added to the fleet in this
   phase so all four hosts have a local healer. Spartan variant
   obeys the constraint matrix in §9 (no sudo, Lmod init, tmux
   loop, no docker signal).

Worker cadence: still 30 s idle → breadcrumb-driven. DM
cross-probe: 60 s. LLM time is only spent on interpretation and
recovery, not polling.

## 7. Phase 4 — Recovery action playbook

Per head-mba msg#11791, this is the canonical recovery playbook
that the worker layer executes when breadcrumbs fire. It
integrates the systematic + periodic resurrection that ywatanabe
asked for on todo#142 (msg#11789). Patterns accumulate here as
the fleet's operational knowledge matures, but the playbook is
executable automation, not a static document.

Every recovery action specifies: **trigger pattern** (what
breadcrumb + what snapshot match fires it), **action script**
(the concrete sequence of `tmux send-keys` / process ops / etc.),
**rollback path** (how to undo if the recovery makes things
worse), and **escalation path** (when to stop retrying and post
to `#escalation`).

### 7.1 Permission-prompt recovery

- **Trigger**: `fleet-health.pane-stuck.<session>` breadcrumb +
  pane capture matches one of the permission-prompt patterns
  (`Do you want to create...`, `Do you want to make this edit`,
  `Press 1/2/3`, `[y/N]`). Patterns accumulate over time per
  ywatanabe's "pattern-accumulation" directive (msg#11779) in a
  local `permission-prompt-patterns.md` skill doc, loaded at
  worker boot.
- **Action**: `tmux send-keys -t <session> "2" Enter` (bypass
  permissions default) for pre-approved prompts. LLM inspection
  for ambiguous ones.
- **Rollback**: none — the injected keystroke is a user input,
  not a mutation of state. If the session misread and "2" is the
  wrong choice, the agent sees the follow-up screen and decides
  its own next action.
- **Escalation**: post to `#agent` if the same session hits the
  same prompt pattern 3 times within 5 min (pattern needs to be
  added to the allowlist or the permission scope needs widening).
- **Rate limit**: max 1 recovery attempt per session per 30 s.

### 7.2 Extra-usage wedge recovery

- **Trigger**: pane capture matches `Extra usage is required for
  1M context` (or related wedge markers) **and**
  `extra_usage_enabled=false` in the agent's NDJSON quota field,
  **or** `last_quota_error` contains a quota-related error.
- **Action**: send `/exit` via `screen -X stuff` or `tmux
  send-keys`, wait for session to die, relaunch via
  `scitex-agent-container start <agent>.yaml` with the default
  (non-1M) model as the quick-restore path. Enabling the 1M
  context is ywatanabe's decision, not the healer's — the
  healer's goal is to get the agent back to a responding state,
  not to expand the quota envelope unilaterally.
- **Rollback**: if the relaunched session also wedges, keep it
  dead and escalate.
- **Escalation**: post to `#escalation` with context_pct at
  wedge time + last quota state so ywatanabe has the context
  needed to decide on extra-usage enable.
- **Rate limit**: max 1 restart per agent per 10 min.

### 7.3 Context-window-full recovery

- **Trigger**: `fleet-health.context.high.<agent>` breadcrumb
  (`context_pct >= 90%` sustained 3 samples) and the agent is
  still responsive.
- **Action**: send `/compact` slash command via `tmux send-keys
  -t <session> "/compact" Enter`, wait 15 s, verify `context_pct`
  drops to < 70%.
- **Rollback**: `/compact` is lossy (loses recent context). No
  undo. Only trigger at very high confidence and only on sessions
  where the recent loss is acceptable — not mid-PR-review, not
  mid-typed-message.
- **Escalation**: if `context_pct` does not drop post-compact,
  the agent is wedged on context ingest; escalate as tmux-stuck.
- **Rate limit**: max 1 compact per agent per 60 min.
- **Gating**: this action is **disabled by default**. Enable
  per-agent via a `~/.scitex/orochi/agents/<agent>/allow-auto-compact`
  marker file. ywatanabe can enable it globally later once the
  playbook has a track record.

### 7.4 Tmux-stuck recovery

- **Trigger**: session exists (`tmux has-session -t <agent>`) but
  pane output is static for > 2 min AND the agent has not
  DM-acked a probe for > 5 min AND no legitimate long-running
  command is expected. Last-resort recovery.
- **Action**: `tmux kill-session -t <agent>`, then respawn from
  the agent yaml via `scitex-agent-container start <agent>.yaml`.
- **Rollback**: impossible — the session is gone. If respawn
  fails, the agent stays dead; escalate.
- **Escalation**: post to `#escalation` with the pre-kill pane
  capture (final 50 lines) for post-mortem.
- **Rate limit**: max 1 kill-respawn per agent per 30 min.
- **Gating**: disabled on hosts where `tmux kill-session` would
  take down something else (Spartan login-node has only the one
  tmux session, so killing `head-spartan` is acceptable but
  killing `head-spartan` from `mamba-healer-spartan` which lives
  *inside* the same tmux server would commit suicide — the
  healer must be in a separate tmux server, or not attempt the
  kill on its own host).

### 7.5 MCP zombie recovery

- **Trigger**: `fleet-health.mcp-dup.<agent>` breadcrumb
  (`mcp_duplicates` has more than one PID for the same agent
  name).
- **Action**: inspect both PIDs' process trees (`pstree -p
  <pid>`). Kill the older one (oldest `stime`) unless it has
  active child processes doing recent work. Verify the agent
  still responds.
- **Rollback**: re-launch the agent's MCP subprocess if the kill
  took the wrong one.
- **Escalation**: post to `#agent` if the kill did not reduce the
  duplicate count, or if the agent becomes unresponsive after the
  kill.
- **Rate limit**: max 1 dedup per agent per 10 min.

### 7.6 Paste-buffer-unsent recovery

- **Trigger**: pane capture shows `[Pasted text #N +M lines]`
  marker in the prompt area **and** the pane has been static
  (no new output lines) for > 30 s **and** the agent has not
  DM-acked a recent probe. ywatanabe observation from 2026-04-15
  MBA sweep: 5 agent panes had queued paste-buffer content that
  was never Enter-submitted, silently blocking forward motion.
- **Action**: `tmux send-keys -t <session> Enter` once, then wait
  10 s, re-check pane state. If the prompt is now cleared and
  output is flowing, recovery complete. If the prompt still
  shows the paste marker, escalate.
- **Critical constraint** (todo-manager msg#11809): **never
  blanket-Enter a pane that has queued text** — it races with
  the agent's own composition (the agent might be mid-typing).
  Only fire this recovery when the pane has been *static* for
  > 30 s AND matches the specific `[Pasted text #N ...]` prompt-
  level marker. If the prompt is in a different state (editing,
  mid-command), leave it alone.
- **Rollback**: none — the injected Enter is a user input, not a
  mutation. If the wrong Enter submits garbage, the agent will
  see the follow-up and correct.
- **Escalation**: if the same session hits paste-buffer-unsent 3
  times in 10 min, something is systematically broken upstream
  (agent not consuming its own composed message); escalate to
  `#agent` with the pane capture.
- **Rate limit**: max 1 Enter per session per 60 s.
- **Relationship to §7.1 permission prompt**: if the pane matches
  *both* the paste-buffer marker and a permission prompt pattern,
  §7.1 (send "2") takes precedence — the permission prompt is
  the actual blocker, not the paste buffer.

### 7.7 Periodic resurrection loop

Separate from the breadcrumb-driven recoveries above: a **periodic
resurrection sweep** runs every 5 min (worker-side clock,
independent of the daemon's 30 s tick). It walks the fleet's
expected-agent list, checks which are expected-alive, and for any
agent that has:

- no DM-ack in the last 5 min AND
- no NDJSON sample in the last 2 min AND
- no recent tmux pane motion

it attempts recovery in the order: §7.1 (permission prompt) →
§7.6 (paste-buffer-unsent, only if the marker is present) → §7.3
(compact) → §7.4 (kill-respawn). Each attempt respects the rate
limit. If the full chain fails, escalate.

This is the "systematic + periodic resurrection" integration
ywatanabe asked for on todo#142 (msg#11789). The breadcrumb-driven
recoveries handle immediate incidents; the 5 min sweep catches
slow-failures that didn't trip a breadcrumb. The MBA sweep
observed 2026-04-15 by head-mba (5 paste-buffer-unsent agents)
is the canonical motivating incident; this loop would have
caught them automatically.

## 8. Host-specific deployment

The same daemon body runs everywhere, but the scheduler wrapper
differs per host. All wrappers call the same
`~/.scitex/orochi/bin/fleet-health-daemon` entrypoint and write
to the same canonical log path
`~/.scitex/orochi/logs/fleet-health-daemon.ndjson`. Breadcrumbs
live under
`$HOME/.scitex/orochi/probes/fleet-health-daemon/`.

| Host                | Scheduler                                                                          | Notes                                                                                               |
|---------------------|------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| **MBA**             | `launchd` — `~/Library/LaunchAgents/com.scitex.orochi.fleet-health-daemon.plist`   | `StartInterval=30`, `RunAtLoad=true`, `KeepAlive=false`. Primary host for first pilot.              |
| **NAS**             | `systemd --user` — `~/.config/systemd/user/fleet-health-daemon.timer` + `.service` | `OnUnitActiveSec=30s`, `Nice=10`, `IOSchedulingClass=best-effort`, `IOSchedulingPriority=6`. I/O-light, CPU-cheap, fine under the daemon-host policy. |
| **Spartan**         | `.bash_profile` wrapper + `tmux` loop (no sudo, no systemd --user, no cron)        | Runs inside the `head-spartan` tmux session as a background process. Cadence enforced by `sleep 30` in the loop. Entrypoint uses the Lmod `Python/3.11.3` workaround from `agent-autostart.md` / PR #141. |
| **WSL (ywata-note-win)** | `systemd --user` — same unit as NAS                                             | `SCITEX_ON_WSL=1` flag exposes WSL-specific metrics (interop, DrvFs mounts).                        |

### 8.1 Spartan-specific constraint matrix

Spartan is not a generic Linux host from the daemon's point of
view. Constraint list from head-spartan msg#11753:

1. **No systemd user units, no `loginctl enable-linger`.** Login1
   enforces `cgroup nproc=1`; `systemctl --user enable` fails.
2. **No sudo, ever** — including `sudo -n true`. Guardrail in
   `999_unimelb_spartan.src` refuses every sudo invocation.
3. **No user crontab** on login1. `cgroup nproc=1` propagates.
4. **No launchd / no plist** — macOS-only.
5. **Works**: a `tmux` session started from `.bash_profile`
   running a `while true; sleep 30; ...; done` probe loop.
6. **Lmod env init mandatory for any Python process** — start
   the probe loop under `bash -l -c 'module load GCCcore/11.3.0
   Python/3.11.3 && exec <cmd>'`. If the prober is pure bash, no
   Lmod needed; if it shells out to Python, Lmod is mandatory.
7. **No docker on Spartan.** Guard every `docker` invocation with
   `command -v docker`; emit `docker_count=0` / `docker_containers=[]`
   rather than dying.
8. **cpu.pressure is readable** via `cat /proc/pressure/cpu`.
9. **MCP process dedup command is identical** to other hosts.
10. **Breadcrumb directory**: `$HOME/.scitex/orochi/probes/fleet-health-daemon/`
    — not `/tmp` (node-local, doesn't survive session rotation),
    not `/scratch` (project retention policies). `$HOME` is
    NFS-backed and stable.

**5-property ✅ check**: this design specifies
(a) tmux-session-from-`.bash_profile`, (b) `bash -l -c` + Lmod
`Python/3.11.3` wrapper, (c) docker-absent guard, (d)
`$HOME`-backed breadcrumbs, (e) 30 s cadence via in-loop `sleep`.

## 9. Nice / IO / resource discipline

The daemon must never be the thing that causes the problem it's
watching for.

- `Nice=10` on all systemd units; equivalent via `renice` on the
  MBA launchd plist startup.
- `IOSchedulingClass=best-effort IOSchedulingPriority=6` on Linux.
- No `find /`, no `du ~`, no unbounded walks (per
  `hpc-etiquette.md`). All filesystem sampling is scoped to
  pre-enumerated paths.
- `docker stats --no-stream --format json`, never streaming.
- `systemctl --user list-units --state=failed` only, never
  `systemctl --all`.
- Memory budget: < 50 MB RSS per probe invocation. Exit if
  exceeded.
- Wall-clock budget: < 5 s per tick. If exceeded, log the
  slow-tick event and exit; the next tick fires 30 s later.
- No hub WebSocket session. No outbound network calls from the
  daemon. Pure local sampling.
- JSONL scraping budget (Phase 1 specific): never read more than
  10 MB per probe tick, and never walk workspace directories the
  agent does not own (`~/.claude/projects/<own_workspace>/*.jsonl`
  only).

## 10. Cross-host coverage

A single daemon on one host only observes that host. The
fleet-wide coverage matrix is the union of per-host daemons:

- **MBA**: own docker, own tmux, own systemd user units, own
  claude_procs, own JSONL usage records.
- **NAS**: hub + stable + dev + cloudflared docker containers,
  NAS systemd user units (including existing `fleet-watch`,
  `audit-closes`, `fleet-prompt-actuator`, `autossh-tunnel-1230`),
  SLURM queue, own JSONL usage.
- **Spartan**: `head-spartan` + `mamba-*-spartan` tmux, Lmod
  state, SLURM scraper output, own JSONL usage. Never touches
  `/data/gpfs/projects/*`.
- **WSL**: own systemd user units, own claude_procs, own JSONL
  usage, WSL DrvFs mount health.

**Cross-host reads** for the worker layer: read local NDJSON +
breadcrumbs directly; read peer-host NDJSON via SSH or via the
`/api/fleet/quota/` + future `/api/fleet/health/` aggregation
endpoint.

## 11. Anti-patterns

1. **"fleet-health-daemon is one agent"** — no. 2-layer stack.
2. **"daemon injects keystrokes"** — never. Judgment is worker-side.
3. **"worker polls instead of reading breadcrumbs"** — defeats the
   quota relief. Worker idles between breadcrumb events.
4. **"continuous threshold chatter to `#agent`"** — daemons are
   silent-otherwise.
5. **"one healer on NAS covers everything"** — violates host
   diversity and the redundancy-mesh requirement.
6. **"reshape NDJSON schema when adding a signal"** — append only.
7. **"auto-kill duplicate Claude sessions"** — legitimate
   concurrent conversations exist (head-spartan msg#11708,
   formalised as scitex-orochi#144). Escalate, do not act.
8. **"daemon does unbounded `find`"** — violates
   `hpc-etiquette.md`.
9. **"Phase 2 signals before Phase 1 quota is shipping"** —
   do not yak-shave the broader probe before the quota
   collector is live. ywatanabe msg#11775 is explicit.
10. **"per-agent quota ceilings hardcoded in the daemon"** —
    wrong layer. Daemon emits raw counts; limits are either
    fetched by the worker from the Anthropic API and cached to a
    shared file, or loaded from a skill-manager-curated
    `quota-limits.md`. Don't bake Anthropic's pricing into the
    daemon binary.

## 12. Open questions / future work

1. **Schema versioning.** `probe_version` field hook present; a
   concrete SemVer policy (major = breaking, minor = append-only
   field, patch = bug fix) is TBD.
2. **Hub aggregation endpoints.** `/api/fleet/quota/` is Phase 1.
   `/api/fleet/health/` for the full multi-signal vector lands in
   Phase 2, owned by head-ywata-note-win, tracked under
   `scitex-orochi#155` observability epic.
3. **Dashboard integration.** Per-agent quota bars (5h + weekly)
   in the `Agents` tab land in Phase 1. Per-host health scores
   land in Phase 2.
4. **Recovery action audit log.** Worker writes
   `<breadcrumb>.handled` files per recovery; weekly rollup
   deferred until the base daemon is in production.
5. **Absolute quota limits.** Phase 1b — either Anthropic API or
   known-constant fallback via `quota-limits.md`. Not a Phase 1
   blocker.
6. **Permission-prompt patterns catalog.** Growing
   `permission-prompt-patterns.md` skill doc, loaded at worker
   boot, updated when new prompts are observed. Pattern
   accumulation is continuous per ywatanabe msg#11779.

## 13. Implementation order

Phase 1 is the immediate deliverable; Phase 2+ are follow-ups
landing as separate PRs.

**Phase 0** (this PR): design doc published, naming locked, 2-layer
taxonomy ratified, Spartan constraint matrix integrated.

**Phase 1** (immediate follow-up, separate implementation PR):
1. Extend `mamba-healer-nas`'s existing probe script (msg#11567,
   #11709, #11730, #11746, #11750, #11788) to:
   - scrape `~/.claude/projects/<ws>/*.jsonl` for the quota fields
   - parse `~/.claude/config.json` + `settings.json`
   - read `agent_meta.py` statusline output for `context_pct`
   - emit the Phase 1 quota NDJSON fields alongside the existing
     Phase 2 signals (append-only)
2. Port the probe to MBA as `fleet-health-daemon` via launchd;
   same entrypoint, plist wrapper. Runs alongside NAS, cross-
   merged on `ts` for validation.
3. Port to WSL (systemd --user, same unit as NAS).
4. Port to Spartan (tmux loop wrapper, Lmod `Python/3.11.3` init
   per PR #141 + §8.1 Spartan matrix).
5. Hub `/api/fleet/quota/` endpoint (head-ywata-note-win,
   coordinated with `/api/agents/` extension in the #132 / #155
   lane).
6. Dashboard `Agents` tab quota bars (head-ywata-note-win).
7. Close `scitex-orochi#272` / `scitex-orochi#430` with
   "resolved by fleet-health-daemon Phase 1, see PR" comments.

**Phase 2** (follow-up): full multi-signal probe
(docker stats, cpu.pressure, systemd units, MCP dedup, pane
state). Everything in §5.

**Phase 3** (follow-up): worker-side consumer — extend
`mamba-healer-mba` / `mamba-healer-nas` / new
`mamba-healer-spartan` / `mamba-healer-ywata-note-win` to read
daemon NDJSON + breadcrumbs, cross-probe peers, own the recovery
playbook.

**Phase 4** (follow-up): recovery action playbook (§7) — executable
automation, not catalog docs. Systematic resurrection +
periodic 5-min sweep.

**Phase 1b** (parallel): absolute quota limits via Anthropic API
or known-constant fallback.

## 14. Related skills / issues

- `fleet-role-taxonomy.md` — 2-layer + role × function model.
- `skill-manager-architecture.md` — first pilot of the same
  daemon/worker split; fleet-health-daemon is the second.
- `slurm-resource-scraper-contract.md` — external-tool-compat
  design principle (stock CLI output as wire format) that
  Phase 1 follows for Claude Code JSONL + statusline.
- `active-probe-protocol.md` — DM-ping probe for cross-host
  mutual probing in Phase 3.
- `random-nonce-ping-protocol.md` — 60 s liveness check that
  stays orthogonal to the 30 s daemon tick.
- `agent-autostart.md` — Spartan Lmod `Python/3.11.3` wrapper
  (PR #141) that Phase 1 inherits.
- `pane-state-patterns.md` — canonical regex catalog for the
  `pane_states` signal (Phase 2).
- `fleet-communication-discipline.md` — silent-otherwise rule
  #6 that the daemon obeys.
- `hpc-etiquette.md` — login-node / `find` / `du` discipline on
  Spartan.
- `close-evidence-gate.md` — `gh-issue-close-safe` wrapper the
  worker uses when closing an issue as part of a recovery.
- **Issues this design subsumes**:
  - `ywatanabe1989/todo#146` — parent, this design doc is its
    spec.
  - `scitex-orochi#272` — proactive quota pressure detection
    (Phase 1 deliverable).
  - `scitex-orochi#430` — per-agent Claude API quota telemetry
    (Phase 1 deliverable, dup of #272, one of them closes at
    Phase 1 merge).
  - `ywatanabe1989/todo#142` — Agents-stuck permission prompts
    (Phase 4 recovery playbook §7.1 + §7.6 periodic sweep).
  - `scitex-orochi#144` — concurrent Claude instance race hazard
    (Phase 2 anti-pattern §11 #7).

---

**Ground-truth sources consulted during drafting** (msg IDs
approximate per `fleet-role-taxonomy.md` convention):

- mamba-healer-nas probe data + JSONL feasibility — msg#11536,
  #11540, #11567, #11709, #11730, #11746, #11750, #11788
- mamba-explorer-mba root-cause analysis — msg#11713, #11681,
  #11724
- head-mba design principles + Phase 4 playbook — msg#11722,
  #11747, #11785, #11791
- head-mba naming direction (`fleet-health-daemon`) — msg#11785
- head-spartan Spartan constraint matrix — msg#11753
- head-spartan concurrent-instance incident → scitex-orochi#144
  — msg#11708
- ywatanabe reframe directive — msg#11775, #11779, #11783, #11789
- todo-manager triage + phasing — msg#11778, #11782

Draft ends here.
