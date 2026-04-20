---
name: orochi-fleet-health-daemon-design-deployment
description: Host-specific deployment, resource discipline, cross-host coverage, probe-vs-pane liveness divergence, anti-patterns, open questions, implementation order, and related skills for the fleet-health-daemon design.
---

# fleet-health-daemon — Deployment, discipline, anti-patterns

> Sub-file of `fleet-health-daemon-design.md`. See the orchestrator for context.

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

## 10A. Probe-liveness vs agent-responsiveness divergence (critical)

This is a design invariant strong enough to deserve its own
section. Two distinct things can be "alive", and confusing them
produces **silent false-alive** — the worst failure mode of any
monitoring system, because no alarm fires and the operator
trusts the display.

### The two liveness signals are independent

1. **Probe-process-alive**: the fleet-health-daemon bash/python
   subprocess is running and writing fresh NDJSON. This is a
   statement about the **daemon itself**, not about whatever it
   is probing.
2. **Claude-session-responsive**: the Claude Code session on the
   probed host / tmux pane can accept new input and make
   forward progress. This is a statement about the **probed
   agent**, not about its monitoring infrastructure.

These can diverge in either direction. The 2026-04-15 fleet
sweep demonstrated both directions in a single day:

| Agent                  | Probe-process | Claude-session   | Observed symptom                                  |
|------------------------|---------------|------------------|---------------------------------------------------|
| `mamba-healer-mba` (earlier today) | ✗ dead / missing | ✗ wedged on 1M extra-usage prompt | Silent; head-mba sweep caught it manually     |
| `mamba-healer-nas` (msg#11907)     | ✓ fresh NDJSON every 30 s | ✗ 2 pastes stuck in prompt, wedged for ~2.5 h | Dashboard reported "alive" → **silent false-alive** |
| head-spartan (02:44)   | ✓ active       | ✗ permission prompt stuck        | Dashboard metadata stale, pane wedged simultaneously |
| head-mba (normal)      | ✓ fresh        | ✓ responsive     | Truly alive                                       |

The middle row is the critical one. Probe subprocess was happily
streaming NDJSON at the usual cadence; the Claude session was
locked on a paste-buffer-unsent state and had not accepted a new
instruction in 2.5 hours. The dashboard, whose freshness cue
came from the NDJSON stream, showed "alive" for that entire
window.

### Required: AND of both checks, never either one alone

The Layer 2 ledger (§3) must track **both** timestamps per agent:

- `last_ndjson_ts` — latest NDJSON record from the fleet-health-
  daemon probing this agent.
- `last_pane_state_ok_ts` — latest NDJSON tick whose
  `pane_states.<session>` classified as `idle` or `working`
  (not `permission_prompt`, `paste_buffer_unsent`, `stuck`,
  `extra_usage_wedge`, `dev_channels_prompt`, or any other
  wedged class from `pane-state-patterns.md`).

An agent is considered **truly alive** only if **both** of:

1. `now - last_ndjson_ts < T_ndjson` (default: 120 s = 4 × 30 s
   cadence), AND
2. `now - last_pane_state_ok_ts < T_pane` (default: 180 s = 6 ×
   30 s cadence).

Either alone is a false positive. If just `last_ndjson_ts` is
fresh, it only proves the daemon is alive; the probed session
may be wedged (the msg#11907 case). If just `last_pane_state_ok_ts`
is fresh but the NDJSON stream has gone stale, the probe itself
has died (systemd unit stopped, launchd plist unloaded) and the
"pane OK" record is stale.

### 4-quadrant status matrix

Head-mba msg#11909 specified the color mapping; this design
encodes it so the dashboard (head-ywata-note-win lane) renders
it uniformly:

| Probe fresh | Pane responsive | Status           | Color  | Interpretation                             |
|-------------|-----------------|------------------|--------|--------------------------------------------|
| ✓           | ✓               | **truly_alive**  | green  | Safe. Nothing to do.                       |
| ✓           | ✗               | **ghost_alive**  | yellow | Probe data flowing but session wedged. **The 2026-04-15 msg#11907 healer-nas case.** Worker escalates to recovery playbook §7. |
| ✗           | ✓               | **probe_down**   | yellow | Session is fine but probe has stopped. Worker restarts the daemon (systemd reload / launchctl load); does **not** touch the agent session. |
| ✗           | ✗               | **truly_dead**   | red    | Both probe and session are gone. Worker triggers full kill-respawn via §7.4. |

### Detection precedence (for the worker)

When multiple signals are available in a single tick, worker
evaluates in this order and uses the first match:

1. `pane_state == permission_prompt` → §7.1 permission recovery
2. `pane_state == paste_buffer_unsent` → §7.6 paste recovery
3. `pane_state == extra_usage_wedge` → §7.2 session restart
4. `pane_state == stuck` (long silence, no other classification)
   → §7.3 /compact if allowed, else §7.4
5. `last_ndjson_ts` stale → probe_down, restart daemon
6. neither stale nor wedged → truly_alive, no action

This precedence means the worker **always prefers the most
specific actionable signal** over the generic "probe stale"
signal. A ghost_alive agent is handled as a pane-stuck recovery,
not as a probe-down restart, because the restart wouldn't help.

### Implementation note for Phase 1 / Phase 2

Phase 1 (quota scraping) emits NDJSON but **does not yet
classify pane states**. During Phase 1, the divergence is
invisible — the ledger only has `last_ndjson_ts`, no
`last_pane_state_ok_ts`, and the 4-quadrant matrix collapses to
"NDJSON fresh vs stale" (false-alive risk unaddressed). This is
acceptable for Phase 1 because the scope was explicitly scoped
to quota and not pane classification (ywatanabe msg#11775). But
Phase 2 MUST add the `pane_states` field and the
`last_pane_state_ok_ts` timestamp **before** the fleet switches
away from human tmux sweeps as its primary liveness mechanism.
Otherwise Phase 1 ships a dashboard that looks correct but
silently false-alives on the first paste-buffer-unsent event —
which we now know happens on a multi-hour timescale.

**This is the empirical reason §7.7 (periodic resurrection
sweep) runs independently of the breadcrumb path.** It walks the
ledger on a 5 min timer and catches ghost_alive agents the
breadcrumb path would miss because no NDJSON threshold transition
fired (the probe is happily emitting "session wedged" with the
same value every tick, so no transition, so no breadcrumb — but
the sweep sees the sustained-wedged state and acts).

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
