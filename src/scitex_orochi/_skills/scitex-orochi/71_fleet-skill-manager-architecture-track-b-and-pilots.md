---
name: orochi-skill-manager-architecture-track-b-and-pilots
description: Track B (`worker-skill-manager-<host>`, agent-layer LLM-backed worker) plus parallel pilots (todo-sweep-daemon, slurm-resource-scraper) and the split rationale summary. (Split from 52_fleet-skill-manager-architecture-impl.md.)
---

> Sibling: [`52_fleet-skill-manager-architecture-track-a-daemon.md`](52_fleet-skill-manager-architecture-track-a-daemon.md) for Track A (skill-sync-daemon).

## Track B — `worker-skill-manager-<host>` (agent layer, primary host)

The existing Claude Code session, but with Track A responsibility
removed. After the split, Track B's job is purely on-demand:
respond to queries, draft new skills, review daemon-flagged
drift/dedupe candidates, curate taxonomy.

### Response SLA

| Source              | Target latency | Escalate if                                       |
|---------------------|----------------|---------------------------------------------------|
| DM from any agent   | ≤ 60 s         | miss → #escalation after 5 min                    |
| #heads @mention     | ≤ 60 s         | same (cross-head coordination)                    |
| #the operator direct   | ≤ 30 s         | miss → TTS escalation                             |
| #the operator fleet    | only if skills expertise is the blocker; otherwise silent (the operator thread is DM-ish, not fleet broadcast) |

> `#agent` was abolished 2026-04-21; cross-head @mentions now go to `#heads`, and task dispatch/ack uses DM.

### Response format (terse, in order)

1. **Canonical file path** — absolute path under one of the four
   skill locations.
2. **One-line summary** of what the skill actually enforces.
3. **Gap note** — if the question reveals a missing skill, say so
   explicitly and offer to draft one. Do not silently invent a
   new skill inline.

### Standing queues the worker services

- **Drift issues** opened by `skill-sync-daemon` under label
  `skill-drift` — review and close or escalate, do not let them
  accumulate.
- **Dedupe candidates** logged by the daemon — decide per
  candidate whether to merge (requires the operator or head-<host>
  sign-off), rename, or leave as-is with a note.
- **Export failures** signaled by
  `~/.scitex/orochi/skill-sync-daemon.fail` on either host —
  fetch the log, diagnose, clear the touch-file only after the
  root cause is fixed.

### Silent-otherwise discipline

Outside of query response, daemon-queue servicing, and the single
startup announce to `#the operator`, the Track B worker is silent.
No heartbeat. No "still idling". No "queues empty, nothing to
do." Those go to `~/.scitex/orochi/logs/skill-manager-worker.log`
(per head-<host> review, msg#11427 — explicit local log path).

### What Track B worker does **not** do

- Does **not** run the Track A scan itself. That's the daemon's
  job. If both daemon instances are down, the worker raises
  `#escalation` for the healer to resurrect them — the worker
  does **not** run the deterministic loop "temporarily" to cover.
- Does **not** close issues. `gh-issue-close-safe` + the
  close-evidence-gate auditor own that.
- Does **not** edit other agents' workspace files. Only the two
  shared skill trees + the dotfiles mirror (on primary host; standby host is
  idempotent-equivalent).
- Does **not** post heartbeat / keep-alive pings. Healer prober
  owns liveness.
- Does **not** decide merges unprompted. Flagged dedupe
  candidates require human or head-<host> sign-off before any merge.

## Parallel pilot #2 — `todo-sweep-daemon`

`worker-todo-manager-<host>` Track A is being daemonized
simultaneously on **primary host launchd** as a redundancy stress-test.
Same scaffolding as `skill-sync-daemon`, different input
interface (`gh issue` sweep + cross-ref index refresh + close-
evidence audit of the todo-repo mirror) instead of skill-tree
walking. Both daemons feed the same observability stream (log
line + optional `.fail` touch-file), and if either falls over,
the other keeps data flowing. This is **day-1 redundancy, not
retrofit** — the fleet gets two independent pilots of the same
split pattern landing in the same ratification commit so the
pattern is proven on more than one concrete case before it
becomes the default recommendation.

See `worker-todo-manager-<host>`'s own architecture doc (when
drafted) for the per-tick procedure on that side.

## Parallel pilot #3 — `slurm-resource-scraper`

A third pilot lands alongside this one in the same ratification PR:
`slurm-resource-scraper` on Spartan + standby host + secondary host, drafted by
head-<host> under the "external-tool-compat" design principle (use
stock SLURM CLI output — `sinfo`, `squeue`, `sacct`,
`scontrol --json`, `sreport` — as canonical wire format, emit
NDJSON with SLURM long-form column names, bash + systemd-timer,
no custom schema). See `infra-slurm-resource-scraper-contract.md` for
the full contract — it is the canonical example of the
external-tool-compat design principle for *all* metrics-collector
daemons in the fleet.

The scraper is the canonical example of the design-time
external-tool-compat principle for *all* metrics-collector
daemons in the fleet: never invent a bespoke JSON schema when a
widely-deployed external tool (SLURM, systemctl, docker,
cloudflared, autossh, etc.) already speaks a canonical one.
`host-self-describe`, `tunnel-health`, and future collectors
should copy this pattern.

## Split rationale summary

| Concern                      | Before (single session)                         | After (split)                                                     |
|------------------------------|-------------------------------------------------|-------------------------------------------------------------------|
| Quota cost of rollup loop    | 1 Claude session running 24/7 just to walk dirs | Zero — launchd on primary host + systemd on standby host, both quota-free           |
| Response latency for queries | Depends on whether the tick loop was mid-`export` | Always fast — worker session is idle between queries              |
| Failure isolation            | Rollup failure took down the query responder   | Daemon failure is signaled to the worker, worker stays up         |
| Single point of failure      | One host, one session                           | Two hosts, idempotent dual-run, miss-backfill within one cadence  |
| Observability                | Mixed chatter + real findings                   | Daemon log is machine-parseable; worker posts only when asked     |
| Host locality                | primary host (same as everything)                        | primary host primary (stability) + standby host warm-standby (24/7); host-diverse   |
| standby host visitor SLURM collision  | N/A (rollup was on primary host)                         | Avoided — standby is I/O-light, CPU-hot stays on primary host              |

## Related skills

- `00-agent-types.md` — the 2-layer + role × function model
  that makes this split the default shape for hybrid agents.
- `infra-slurm-resource-scraper-contract.md` — parallel pilot #3 and
  canonical example of external-tool-compat design principle for
  metrics-collector daemons.
- `silent-success.md` — rule #6 discipline that governs the
  worker's posting behavior.
- `fleet-communication-discipline.md` — #the operator vs DM vs
  #heads vs #progress rules the worker follows.
- `agent-startup-protocol.md` — 5-step boot sequence the Track B
  worker runs before entering its idle-respond loop.
- `fleet-close-evidence-gate.md` — the evidence standard the worker
  cites when asked "how do I close a skill-related issue
  properly?".
- `infra-deploy-workflow.md` — deployment distinctions (launchd
  reload on primary host / systemd reload on standby host for the daemon vs pane
  restart for the worker).
- `hpc-etiquette.md` — if the standby host-side standby ever needs to be
  rerouted through `sbatch`, this skill's login-node / SLURM
  discipline applies.
