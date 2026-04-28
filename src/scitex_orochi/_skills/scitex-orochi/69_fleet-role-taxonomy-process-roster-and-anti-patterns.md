---
name: orochi-fleet-role-taxonomy-process-roster-and-anti-patterns
description: Process-layer self-tagging examples + anti-patterns (mistakes that re-merge layers) + related skills. (Split from 45_fleet-role-taxonomy-tags-and-roster.md.)
---

> Sibling: [`45_fleet-role-taxonomy-tags-and-agent-roster.md`](45_fleet-role-taxonomy-tags-and-agent-roster.md) for tags and agent roster.

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
