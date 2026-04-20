---
name: orochi-fleet-health-daemon-design-phases
description: Phase 1 (Claude Code quota-state scraping), Phase 2 (multi-signal health probe), and Phase 3 (mamba-healer mesh) sections of the fleet-health-daemon design.
---

# fleet-health-daemon — Phases 1–3

> Sub-file of `fleet-health-daemon-design.md`. See the orchestrator for context.

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

