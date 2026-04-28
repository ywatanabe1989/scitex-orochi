---
name: orochi-fleet-role-taxonomy-part-2
description: Orochi fleet taxonomy — 2-layer (process/agent) + 4 exclusive roles (lead / head / worker / daemon) + orthogonal function tags. Defining axis is "LLM-in-loop?". Daemons are quota-zero programmatic processes, not agents. Host-diverse daemon policy (not NAS-exclusive) because NAS is production-loaded with scitex-cloud visitor SLURM. Ratified 2026-04-14 msg#11475. (Part 2 of 3 — split from 31_fleet-role-taxonomy.md.)
---

> Part 2 of 3. See [`31_fleet-role-taxonomy.md`](31_fleet-role-taxonomy.md) for the orchestrator/overview.
## Two layers

### Process layer (no LLM, no quota)

- **One role only**: `daemon`
- **Runtime**: systemd timer / launchd / cron / plain bash loop.
  **Never** a Claude Code session.
- **Observability**: daemons report state by writing to
  `~/.scitex/orochi/logs/<daemon-name>.log` (host-local) and by
  leaving breadcrumbs in hub-visible places (touch-files, git
  commits, hub REST writes). The agent layer reads those
  artifacts; the daemon itself never holds a WebSocket session.
- **Failure mode**: daemon failures are surfaced into the agent
  layer by the healer-prober (agent layer), not by the daemon
  itself. Daemons do not self-escalate.

#### Daemon host policy (finalized msg#11493 + #11502)

The daemon layer is **host-diverse**, not NAS-exclusive. The
one-line rule:

> Choose the host by what the daemon *costs*, not by what's
> convenient.

| Host          | Accepts                                                       | Rejects                                              |
|---------------|---------------------------------------------------------------|------------------------------------------------------|
| **NAS**       | I/O-light, CPU-cheap daemons: lease / log tail / bastion standby / audit-closes / fleet-watch producer / slurm-resource-scraper / reverse-tunnel | CPU-hot direct-exec daemons — they compete with scitex-cloud SLURM visitor allocations via the kernel scheduler, even without going through SLURM |
| **MBA**       | CPU-hot daemons via launchd: bulk rsync, `scitex-dev skills export --clean`, index rebuild. Primary host for the `skill-sync-daemon` pilot (empirically most stable per msg#11464) | nothing categorical — MBA is the CPU-hot default      |
| **NAS (sbatch escape hatch)** | Heavy work that *needs* to live on NAS (e.g. reads NAS-local data) **must** be submitted as `sbatch` SLURM jobs, queued alongside visitor traffic, not run as a direct systemd-timer exec | direct systemd/launchd exec for anything CPU-hot     |
| **Spartan**   | Cheap daemons (metrics / self-describe / SLURM resource scraper). Heavy work via `sbatch`. Login-node policy (never compute on `login1`) still applies | anything that violates `hpc-etiquette.md`            |
| **WSL**       | Cheap daemons including a SLURM resource scraper — WSL has a local SLURM per ywatanabe msg#11487 | heavy work without `sbatch`                          |

#### Why NAS is not the exclusive daemon-host

Before the NAS SLURM reality came in (msg#11492/#11493), the
obvious shape was "NAS is 24/7, systemd-native, quota-free, put
every daemon there". The blocker: NAS is already running
`scitex-cloud` visitor session sandboxes under a real SLURM
scheduler — 6 concurrent `scitex_visitor-*_dotfiles` jobs, full
CPU/memory allocation (12/12 cores, 24GB), 59-min walltime caps,
`scitex-alloc-<hash>.sh` allocation scripts in flight. That is
production-ish traffic. A CPU-hot direct-exec systemd timer on
NAS competes with those allocations through the kernel scheduler
even if the timer never enters the SLURM queue — the visitor
sandbox's priority doesn't know about systemd user timers.

So NAS stays in the daemon layer, but only for I/O-light / CPU-
cheap things, and for anything heavy we use NAS's own SLURM as
the escape hatch (submit as `sbatch`, queue alongside visitor
jobs, respect walltime). CPU-hot direct-exec goes to MBA launchd
instead.

This also gives the fleet a natural redundancy: MBA primary +
NAS warm-standby for the pilot daemon (`skill-sync-daemon`), with
the standby running the same idempotent loop so a missed MBA
interval is backfilled on NAS's next tick. No shared lease
required (head-nas option (d), msg#11499).

#### The daemon inventory is partly discovery, not invention

An important realization from Phase 2: NAS is **already** running
programmatic daemons via systemd user timers. The PoC work is
primarily horizontal expansion + inventory + tagging, not
green-field implementation. Concretely, the following daemons
exist today and just need to be **tagged** under the new taxonomy:

- `audit-closes.timer` — the 30-min close-evidence auditor.
- `fleet-watch.timer` — per-host outbound reachability producer.
- `fleet-prompt-actuator.timer` — prompt unblocker.
- `scitex-slurm-perms.service` — credential/permission bootstrap,
  load-bearing.
- `autossh-tunnel-1230.service` — NAS → MBA bastion reverse SSH
  (port 1230 on MBA exposes NAS:22), load-bearing.
- `cloudflared-bastion-nas.service` — cloudflared bastion tunnel,
  currently flapping ("no recent network activity" ERR) — a
  reminder that NAS infrastructure is not a given.

This is good news for #133 execution: the pilot is not "build new
daemons" but "promote existing daemons to first-class citizens of
the taxonomy, add the few missing ones, wire them all to the
self-describe stream".

### Agent layer (LLM-backed)

Three exclusive roles, all backed by Claude Code sessions:

#### `lead` — cardinality exactly 1

The single interface to ywatanabe. Owns intent interpretation,
dispatch, and final escalation. Runs on the hub host (today: MBA,
so the lead seat is `head-mba`'s double duty). Dispatcher
responsibility collapses into `lead` — there is no separate
`dispatcher` role (msg#11425).

#### `head` — cardinality one per host

Per-host interface agent. Knows its host's local state (tmux,
disks, systemd, local credentials), speaks for that host to the
lead and (when routed) to ywatanabe. Heads do not speak for other
hosts.

Current holders: `head-mba`, `head-nas`, `head-spartan`,
`head-ywata-note-win`.

#### `worker` — cardinality many

Task-driven or resident LLM-backed agents. Workers do the agentic
work: priority decisions, free-text interpretation,
scitexification, incident classification, UI verification, etc.
Most `mamba-*` agents are workers.

Workers may be:
- **task-driven** (ephemeral: dispatched → completes → idles/exits)
- **resident** (long-running loop, but still LLM-in-loop — this is
  *not* a daemon; it's a worker that happens to be always-on)

Example: today's `mamba-skill-manager-mba` is a resident worker
with `function=[skill-sync]`. Its programmatic Track A has been
externalized into a separate daemon-layer process
(`skill-sync-daemon`). See `skill-manager-architecture.md`.

## Naming convention (ywatanabe msg#11464)

Agent internal IDs keep the suffix-based form for filesystem
directory separation — `head-mba`, `head-nas`, `head-spartan`,
`head-ywata-note-win`, `mamba-skill-manager-mba` etc. — because
`~/.scitex/orochi/workspaces/<id>/` needs a unique-per-agent path.

The **display form** (in dashboards, #heads posts, #ywatanabe
relays) is `role[:function]@host`, rendered by the hub-side
username filter. So `head-mba` renders as `head@mba`,
`mamba-skill-manager-mba` renders as `worker:skill-sync@mba`,
`mamba-healer-mba` renders as `worker:prober@mba`, etc. This is a
hub-side change, not an agent-side change — agents keep posting
with their internal ID and the hub rewrites on display. Tracked
under #133 observability.
