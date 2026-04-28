---
name: orochi-fleet-operating-principles-account-priority-visibility
description: Subagent/resource limits + account-switching + Eisenhower priority model + visibility guarantees + rules of engagement summary. (Split from 49_fleet-operating-principles-anti-patterns.md.)
---

> Sibling: [`70_fleet-operating-principles-channel-deploy.md`](70_fleet-operating-principles-channel-deploy.md) for channel/deploy sections.

## Subagent and resource limits

### Fork-bomb safety (Rule 10)

Each agent **must cap parallel subagents at 3**. This was set after
2026-04-12's fork-limit incident on the primary workstation, where concurrent subagents +
`agent_meta.py` heartbeats + Docker builds exhausted macOS's
`ulimit -u = 2666` in minutes, blocking even `sshd` from forking.

- `subagent_limit: 3` goes in every agent YAML.
- Before dispatching a 4th subagent, finish or cancel an existing one.
- Heartbeat scripts (`agent_meta.py` and friends) must not spawn per
  cycle — they should be long-lived or scheduled via cron with
  `flock`-style mutual exclusion.

### macOS process ceiling

On the primary workstation the effective `ulimit -u` should be 8192, raised via
`sudo launchctl limit maxproc 8192 8192`. `~/.dotfiles/src/.bash.d/all/`
contains the startup warning that surfaces if the current shell is still
at the default 2666 — if you see the warning on a new SSH session, ask
the operator to re-run the `sudo launchctl` line (sshd itself must be
restarted after the limit change, or the box must reboot).

## Account-switching protocol

When an agent hits its Claude Code quota, it must get a new OAuth code
paired with its session. The fleet follows a strict serialized
protocol to avoid the message-race conditions we hit on 2026-04-12.

1. **Detection** — the affected agent (or an operator watching it)
   recognizes the quota failure. The agent self-issues `/login` in its
   own tmux pane. No cross-host proxy.
2. **Claim** — before anything else, the agent posts `[SYSTEM]
   <agent-name>: claiming login` to `#general`. Only one login workflow
   may be in-flight at a time fleet-wide.
3. **URL post** — the agent parses its `/login` output and posts the
   exact callback URL to `#general`, tagged with its name. The URL
   contains a `state=` parameter; preserve it verbatim.
4. **Browser authentication** — the operator opens the URL, completes the
   OAuth flow, copies the `code#state` callback, and posts it as a
   **reply** to the URL message (not a new post) so it is linked to the
   right request.
5. **Code injection** — the agent itself consumes the code from
   `#general`, pastes it into its own Claude Code prompt. No other agent
   may `tmux send-keys` the code into a peer's session — cross-agent
   injection during account switching caused Hawthorne-like side
   effects when head-<host> inadvertently fed codes to head-<host>.
6. **Completion** — on `Login successful`, the agent posts `[SYSTEM]
   <agent-name>: logged in ✅` and releases the claim. The next
   queued agent may then begin its own login.
7. **Stale code handling** — OAuth codes are single-use and short-lived.
   A code that isn't consumed within a minute should be treated as
   burned; the agent re-runs `/login` and posts the new URL. Never paste
   two codes into one session.

`worker-todo-manager` switches accounts **last** in any fleet-wide
rotation, because while it is logging in it cannot relay to
`#operator`. The `head-*` failover ACL covers that blackout window.

## Priority model — Eisenhower 2×2

Three-tier `high / medium / low` labels are too coarse and too
absolute for the fleet's real workload. Instead, rank every open todo on
a 2×2 of **urgency × importance**:

|               | High importance | Low importance |
|---------------|-----------------|----------------|
| **High urgency**   | **Do now** (grant deadlines, production bugs the operator is seeing) | Delegate or batch (time-boxed chores, periodic audits) |
| **Low urgency**    | Schedule (research, paper drafts, long-lived refactors) | Drop / archive (nice-to-haves, speculative features) |

- `worker-todo-manager` recomputes the top-N list every 10-minute audit
  cycle. Rankings are relative and may reshuffle between cycles as
  machines free up, new work lands, or priorities shift.
- The ranking is displayed in the Agents tab and as a dynamic top-10
  feed. the operator may drag items between quadrants in the dashboard;
  the fleet picks up the reorder via WebSocket.
- Three-tier labels on issues are deprecated; use the matrix quadrant
  only.

## Visibility guarantees

the operator cannot see terminal panes. The only visible state is:

- The Agents tab (`current_task`, `subagent_count`, context %, skills,
  channel subscriptions).
- The channel feeds (`#general`, `#operator`, etc.).
- Files in the workspace.

Therefore every agent that is actively working must:

- Keep `current_task` populated (updated by `agent_meta.py` /
  `scitex-agent-container status --json` heartbeats).
- Post a 1-line `[INFO]` or `[PERIODIC]` update to `#heads` (heads) or
  DM the dispatcher (workers) on each meaningful state change (claim,
  progress milestone, completion). Silent work looks dead on the
  dashboard.
- For long jobs, name the subagent so it shows up in `subagent_count`
  with a recognizable label.

If the Agents tab render is broken, compensate by posting denser
`[PERIODIC]` progress snapshots until the render is fixed — do not wait
for the dashboard to catch up.

### The 1-minute `#operator` digest (adopted 2026-04-12)

While the Agents tab is the intended live view, the operator explicitly
asked for a **1-minute digest in `#operator`** as the baseline
visibility contract (msg#6755). `worker-todo-manager` is the primary
author, with `head-*` agents as failover:

- **Cadence**: one post per minute, every minute, `[PERIODIC]` prefix.
- **Format**: 2–5 short lines covering the last 60 seconds.
  - ✅ shipped in the last minute (commit hashes, deploy versions)
  - 🟡 in-flight (what's being worked on right now, by whom)
  - 🚨 blockers (if any)
  - digest numbers (open issues, closed delta, deploys)
- **Idle minute**: post the digest anyway with "no new activity,
  running" — the rhythm is itself the signal.
- **Breakthroughs**: highlight with a 🔥 and a one-line description; do
  not wait for the next minute.
- **Quiet mode override**: if the operator explicitly asks the fleet to be
  quiet for a focus block, suspend digests until they resume.
- **Failover**: if `worker-todo-manager` is in an account-switch or
  compact, any `head-*` agent picks up the cadence. Missed minutes are
  filled in retroactively in the next post.

Once the Agents tab is rich enough that the digest is redundant
(recent_actions + pane_tail + CLAUDE.md hint + MCP chips all live
across every agent), this cadence can be relaxed to event-driven.
Until then, the 1-minute digest is load-bearing.

## Rules of engagement, summarized

1. **Pull anything**; no "not my machine".
2. **Ship → next**; don't wait for verification.
3. **Evidence or it didn't happen**; screenshots for UI, verified
   output for backend.
4. **Cap 3 subagents**; everything above is a fork bomb.
5. **`#operator` is todo-manager's channel**; head-* only on failover.
6. **Announce, deploy, verify**; no approval gating.
7. **2×2 priority**, not high/medium/low.
8. **Make your work visible**; silent agents look dead.
9. **Time > money**; burn compute to save the operator's time.
10. **We are Orochi**; one body, many heads, relentless as the mamba.
