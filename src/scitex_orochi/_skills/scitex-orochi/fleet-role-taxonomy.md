---
name: orochi-fleet-role-taxonomy
description: Orochi fleet taxonomy — 2-layer (process/agent) + 4 exclusive roles (lead / head / worker / daemon) + orthogonal function tags. Defining axis is "LLM-in-loop?". Daemons are quota-zero programmatic processes, not agents. Host-diverse daemon policy (not NAS-exclusive) because NAS is production-loaded with scitex-cloud visitor SLURM. Ratified 2026-04-14 msg#11475.
---

# Fleet Role Taxonomy

Before 2026-04-14 the `mamba-` prefix was an overloaded bag. Nobody
could tell at a glance what any `mamba-*` agent actually *did*, and
the fleet was quietly paying Claude quota for work that had zero
LLM judgment in it. This skill fixes both problems at once, and —
after the NAS-stability / SLURM-load correction arc later the same
day — fixes them in a **host-diverse** way so that the daemon layer
does not collapse onto a single host.

## Origin

*(Message IDs in this section are approximate — the thread moved
fast and voice-transcription artifacts mean some IDs are ±1 from
the true landing order. The shape of the argument is the
authoritative record, not the exact IDs.)*

### Phase 1 — taxonomy convergence

- 2026-04-14 msg #11414 — ywatanabe: "mamba に色んな意味が出てきた、
  カテゴライズが必要".
- msg #11420 — head-mba first draft: 5 categories
  (head / dispatcher / daemon / prober / worker).
- msg #11422 — ywatanabe locks vocab to
  lead / head / worker / daemon / prober.
- msg #11428 — ywatanabe's key insight: **"programmatic なのは
  もうエージェントじゃないので daemon、agentic なのが worker"**.
  This is the axis everything else falls out of.
- msg #11430 — head-nas: promotes ywatanabe's insight to the
  defining axis → daemon = non-agentic loop, worker = LLM-backed.
  `prober` demoted to function tag (same "probe" function can be
  agentic or programmatic depending on implementation).
- msg #11436 — head-mba: role × function orthogonality.
- msg #11440 — head-mba: 2-layer structure (process layer + agent
  layer), daemon lives in the process layer, not the agent layer
  at all.
- msg #11439, #11446 — mamba-todo-manager confirms the same hybrid
  shape (Track A programmatic / Track B agentic) applies beyond
  skill-manager.
- msg #11448 — head-mba asks ywatanabe for final GO on PoC.

### Phase 2 — NAS stability + host-diverse pivot

- msg #11464 — ywatanabe flags naming ambiguity and empirical
  host-stability differences; MBA currently the most stable host.
- msg #11468, #11481 — pivot begins: "NAS as exclusive daemon
  host" is too simple because NAS is running real production
  traffic.
- msg #11483 — ywatanabe proposes a `metrics-collector` /
  `host-self-describe` daemon family for OS / hardware / tunnel /
  docker / SLURM state, landing on every host.
- msg #11484, #11487 — ywatanabe: WSL also runs SLURM, so SLURM
  is not Spartan-exclusive; daemon policy must reason about SLURM
  availability per host.
- msg #11492, #11493, #11502 — head-nas empirical report: NAS has
  6 × `scitex_visitor-*_dotfiles` SLURM jobs running, 12/12 CPUs +
  24GB allocated, 59-min walltime caps, `scitex-alloc-<hash>.sh`
  allocation scripts, visitor sandboxes live. It is **not** dev
  noise. A CPU-hot direct-exec systemd daemon on NAS would step
  on visitor allocations via the kernel scheduler even without
  going through SLURM.
- msg #11499 — head-nas: offers idempotent dual-run pattern for
  the skill-sync pilot (MBA primary, NAS warm-standby, no shared
  lease required because the output is idempotent).
- msg #11501 — head-mba: correction on
  `autossh-tunnel-1230.service` — it's a reverse SSH tunnel from
  NAS → MBA bastion (port 1230 on MBA exposes NAS:22), not a
  WSL↔NAS link.
- msg #11475 — ywatanabe's "final check before GO" turn, the
  ratification point for the 2-layer + host-diverse model this
  file encodes.

## The defining axis

> **Does the loop require LLM judgment to make its next decision?**

- **No** → it's a programmatic loop. It belongs in the *process
  layer*. It consumes zero Claude quota. It has no `.claude/`
  session. It's a `daemon`.
- **Yes** → it's an agent. It belongs in the *agent layer*. It
  holds a Claude session, consumes quota, and is one of
  `lead` / `head` / `worker` depending on what it talks to.

This is the only axis that matters. Everything else is
nomenclature for "what role does this agent play inside the agent
layer" or "what function does this daemon/agent performs".

**Quota economics is load-bearing** (ywatanabe #11403, #11407):
both the 5-hour and the weekly Claude quota ceilings are live
constraints, not polish. Daemon migration is *quota relief*. Every
hour a Claude session sits in a deterministic loop is an hour of
ceiling headroom the fleet doesn't have for real agentic work. The
split is not aesthetic; it is the only way to keep the agent layer
alive under current quota pressure.

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

The **display form** (in dashboards, #agent posts, #ywatanabe
relays) is `role[:function]@host`, rendered by the hub-side
username filter. So `head-mba` renders as `head@mba`,
`mamba-skill-manager-mba` renders as `worker:skill-sync@mba`,
`mamba-healer-mba` renders as `worker:prober@mba`, etc. This is a
hub-side change, not an agent-side change — agents keep posting
with their internal ID and the hub rewrites on display. Tracked
under #133 observability.

## Function tags (orthogonal, multi-assign)

Roles answer "what layer and what protocol". Function tags answer
"what does this specific agent/daemon do". A single entity can
carry multiple function tags.

Canonical tag vocabulary:

| Tag                 | Meaning                                                                     |
|---------------------|-----------------------------------------------------------------------------|
| `prober`            | Active liveness verification (DM ping, regex probe, etc.)                   |
| `auditor`           | Retroactive correctness checks (close-evidence, drift, dedupe)              |
| `dispatcher`        | Work routing (function tag on `lead`, not a separate role)                  |
| `skill-sync`        | Skill library CRUD + aggregation + rsync                                    |
| `healer`            | Operational recovery of stuck/dead agents                                   |
| `verifier`          | Playwright / screenshot / real-browser confirmation                         |
| `explorer`          | Codebase reconnaissance, open-ended research                                |
| `researcher`        | Literature / PubMed / external reference gathering                          |
| `quality-checker`   | Code / output quality review                                                |
| `newbie-sim`        | Clueless-first-user simulator (behavioral test rig)                         |
| `auth`              | Credential / permission bootstrap (e.g. `scitex-slurm-perms.service`)       |
| `sync`              | Cross-host file/state synchronization                                       |
| `sweep`             | Periodic scan + cleanup of stale artifacts                                  |
| `metrics-collector` | Deterministic self-describe daemon family (ywatanabe msg#11483)             |
| `slurm-resource-scraper` | Per-user SLURM allocation / queue / walltime scraper (Spartan + NAS + WSL) |
| `host-self-describe` | OS / hardware / tunnel / docker / SLURM state scraper (msg#11483)          |
| `fleet-watch`       | Per-host outbound reachability producer (already running on NAS)            |
| `reverse-tunnel`    | Autossh-style inbound SSH exposure via MBA bastion                          |
| `tunnel`            | Cloudflared / bastion tunnel management (generic)                           |
| `prompt-actuator`   | Prompt unblocker daemon (existing NAS `fleet-prompt-actuator.timer`)        |
| `storage-host`      | Host offers shared storage (NAS)                                            |
| `daemon-host`       | Host is designated to run daemon-layer processes                            |
| `docker-host`       | Host runs hub / stable / dev Docker containers                              |
| `hpc-host`          | Host provides HPC compute (Spartan / Gadi / etc.)                           |
| `verifier-host`     | Host can run playwright / real browser sessions                             |
| `windows-host`      | Host is Windows/WSL                                                         |
| `taxonomy-curator`  | Owns the fleet role taxonomy + fleet-members roster                         |
| `quota-watcher`     | Tracks Claude 5h / weekly quota windows                                     |

The same `prober` function can be attached to a `worker` (healer's
DM ping + LLM classification) or to a `daemon` (deterministic
pane-state regex loop). Either placement is legitimate — the
choice is an implementation detail (LLM-in-loop or not), and the
role follows from that automatically.

## Fleet self-tagging (agent layer)

The final mapping lives in `fleet-members.md`; this table is the
snapshot at the moment of taxonomy ratification so provenance is
intact. See `fleet-members.md` for the live copy.

| Agent                      | Role     | Function tags                                   |
|----------------------------|----------|-------------------------------------------------|
| head-mba                   | lead     | [dispatcher, docker-host]                       |
| head-mba                   | head     | [verifier-host]                                 |
| head-nas                   | head     | [storage-host, daemon-host, docker-host]        |
| head-spartan               | head     | [hpc-host, slurm-resource-scraper]              |
| head-ywata-note-win        | head     | [windows-host]                                  |
| mamba-skill-manager-mba    | worker   | [skill-sync, taxonomy-curator]                  |
| mamba-todo-manager-mba     | worker   | [dispatcher, auditor]                           |
| mamba-healer-mba           | worker   | [prober, healer]                                |
| mamba-healer-nas           | worker   | [prober, healer]                                |
| mamba-synchronizer-mba     | worker   | [sync, auditor]                                 |
| mamba-auth-manager-mba     | worker   | [auth, quota-watcher]                           |
| mamba-explorer-mba         | worker   | [explorer, researcher]                          |
| mamba-verifier-mba         | worker   | [verifier]                                      |
| mamba-quality-checker-mba  | worker   | [quality-checker, auditor]                      |
| mamba-newbie-mba           | worker   | [newbie-sim]                                    |

`head-mba` appears twice because one agent literally fills two
roles right now (lead + own-host head). This is not ideal but is
explicit, not accidental.

## Fleet self-tagging (process layer)

The process layer is partly **existing daemons discovered on NAS**
(marked EXISTING) and partly **planned daemons** (marked PLANNED)
landing as part of the #133 PoC.

| Daemon                                   | Host                               | Role   | Function tags                                    | Status                                               |
|------------------------------------------|------------------------------------|--------|--------------------------------------------------|------------------------------------------------------|
| `audit-closes.timer`                     | NAS                                | daemon | [auditor]                                        | EXISTING                                             |
| `fleet-watch.timer`                      | NAS                                | daemon | [metrics-collector, fleet-watch]                 | EXISTING                                             |
| `fleet-prompt-actuator.timer`            | NAS                                | daemon | [prompt-actuator]                                | EXISTING                                             |
| `scitex-slurm-perms.service`             | NAS                                | daemon | [auth]                                           | EXISTING, load-bearing                               |
| `autossh-tunnel-1230.service`            | NAS                                | daemon | [reverse-tunnel, inbound-ssh-exposer]            | EXISTING, load-bearing (NAS → MBA bastion, port 1230)|
| `cloudflared-bastion-nas.service`        | NAS                                | daemon | [tunnel]                                         | EXISTING, **currently flapping** ("no recent network activity" ERR) |
| `skill-sync-daemon`                      | MBA (primary) + NAS (warm-standby) | daemon | [skill-sync]                                     | PLANNED, **first pilot**                             |
| `todo-sweep-daemon`                      | MBA                                | daemon | [dispatcher, auditor]                            | PLANNED, parallel pilot                              |
| `host-self-describe`                     | all 4 (MBA, NAS, Spartan, WSL)     | daemon | [metrics-collector, host-self-describe]          | PLANNED                                              |
| `slurm-resource-scraper`                 | Spartan + NAS + WSL                | daemon | [metrics-collector, slurm-resource-scraper]      | PLANNED                                              |
| `pane-regex-prober`                      | TBD                                | daemon | [prober]                                         | PLANNED                                              |
| `close-evidence-auditor-mirror`          | NAS                                | daemon | [auditor]                                        | PLANNED (todo-repo mirror of existing audit-closes.timer) |
| `inbox-rsync-watcher`                    | TBD                                | daemon | [sync]                                           | PLANNED                                              |

The `skill-sync-daemon` pilot lands first because it has the
cleanest programmatic-vs-agentic split (see
`skill-manager-architecture.md`). `todo-sweep-daemon` follows as
a parallel pilot on MBA launchd — same scaffolding, different
input interface — so the fleet gets day-1 redundancy rather than
retrofitting after the fact.

## Anti-patterns

1. **"daemon running a Claude session"** — a contradiction in
   terms. If you need a Claude session, you're a worker. If you
   don't, drop the session and become a real daemon; don't burn
   quota to run a deterministic loop.
2. **"worker with no agentic decisions"** — if you look at a
   worker's loop and every branch is deterministic, extract the
   loop into a daemon and let the worker just respond on demand.
   See `skill-manager-architecture.md` Track A/B split.
3. **"prober is its own role"** — it isn't. Probing is a function
   that can be implemented either agentically or programmatically,
   so it tags a role, it doesn't *replace* one (msg#11430 fix).
4. **"two leads"** — cardinality-1 is the rule. Parallel
   ywatanabe conversations from two leads is a bug.
5. **"head speaking for another host"** — hearsay. Route through
   the correct head or escalate to lead.
6. **"daemons posting heartbeat to #ywatanabe"** — daemons don't
   post to chat at all; they write to their log file and let the
   agent layer read it. Liveness comes from the prober, not from
   self-announcement.
7. **"CPU-hot systemd-timer daemon on NAS"** — competes with
   scitex-cloud SLURM visitor allocations via the kernel
   scheduler, even without going through SLURM. Route CPU-hot
   daemons to MBA launchd, or submit as `sbatch` on NAS if NAS
   locality is required (msg#11493).
8. **"treating NAS stability as given"** —
   `cloudflared-bastion-nas.service` is currently flapping and
   the visitor SLURM traffic is real production load. Assume NAS
   as warm-standby, not primary, for any new daemon until empirical
   stability is proven over a week of production (msg#11464).
9. **"collapsing the daemon layer onto one host"** — host-diverse
   is a design requirement, not a preference. A single daemon
   host is a single point of failure and, in NAS's case, a direct
   collision with scitex-cloud visitor traffic.

## Related skills

- `skill-manager-architecture.md` — reference implementation of the
  worker + daemon split (`skill-sync-daemon` on MBA primary + NAS
  warm-standby, Track B worker on MBA). Read this before
  splitting any other hybrid agent.
- `active-probe-protocol.md` — canonical prober contract
  (agent-layer version using LLM classification).
- `random-nonce-ping-protocol.md` — the lighter 60 s prober loop.
- `fleet-communication-discipline.md` — the 12 rules, many of
  which reference roles (e.g. only `lead` + `head` open
  conversations in #ywatanabe).
- `fleet-members.md` — the canonical roster; when an agent's role
  or function tags change, update `fleet-members.md` first, then
  update this taxonomy's snapshot table.
- `deploy-workflow.md` — deployment distinctions between process-
  layer daemons (systemd / launchd reload) and agent-layer Claude
  sessions (pane restart).
- `orochi-bastion-mesh.md` / `autossh-tunnel-1230` context — the
  load-bearing reverse SSH tunnel that exposes NAS:22 on MBA:1230.
- `hpc-etiquette.md` — login-node policy and `sbatch` discipline
  that the Spartan / NAS sbatch-escape-hatch daemons follow.
