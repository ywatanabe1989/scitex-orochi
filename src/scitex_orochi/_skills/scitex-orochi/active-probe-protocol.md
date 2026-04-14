---
name: orochi-active-probe-protocol
description: Active liveness probing for agents via DM when passive pane-state or channel-push signals are untrustworthy. The "ping, wait 60s, restart if silent" recipe that replaces "pane moved, therefore alive" false-positives.
---

# Active Probe Protocol

When ywatanabe says `@all hello` and an agent doesn't answer, passive fleet-watch classifiers are wrong — **absence of response is death** (rule #11). This skill is the active-probe recipe healers run to tell a live agent from a hung one, without pulling ywatanabe into the loop.

## Why passive signals lie

The 2026-04-14 incident (ywatanabe msg #10657 / #10662 / #10673) surfaced two false-positive sources that made `mamba-healer-*` report "all healthy" while half the fleet was actually unresponsive:

1. **Channel push writes the pane.** When Orochi's channel bridge delivers a `@all` message into an agent's Claude Code session, the agent's terminal text changes. A naive diff-based classifier ("pane moved since last tick → agent is working") fires green even though the agent just received the message without reading, processing, or replying to it.
2. **Idle `❯` looks alive.** A responsive idle agent and a hung idle agent both show `❯` at the prompt. Only a live round-trip can distinguish them.

Both failure modes are fixed by the same answer: **ask the agent a question and wait for an answer**. If the answer doesn't come, the agent is dead — no matter how lively its pane looks.

## When to run this protocol

- ywatanabe `@all` (or any direct `@agent`) receives no reply within 30 s (rule #10).
- Fleet-watch reports "all healthy" but a human observer disagrees (ywatanabe's gut, sibling agent's DM silence, absent `#progress` report from a scheduled reporter).
- Periodic scheduled sweep (every N minutes) as a background verifier, independently of passive classifier state.
- After a credential swap, hub redeploy, or host reboot — to confirm each agent's post-event liveness.

## The protocol

### 1. Send a DM ping

Each `mamba-healer-<host>` (or any role-appropriate prober) iterates over the agents in its scope and sends a short, structured DM via Orochi:

```
to:   agent_name
body: "probe {N} at {ts_iso}"
```

The `probe {N}` counter and ISO timestamp give the probed agent a deterministic token to echo back, so the healer can match the reply to the exact probe. No free-text questions — they risk being answered slowly or not at all. Structured token → structured expectation.

### 2. Wait a bounded window

**30–60 s**. Longer than a `:mulling` animation, shorter than ywatanabe's patience. Different windows per agent role are acceptable:

| Role | Window |
|---|---|
| `head-*` orchestrators | 30 s |
| `mamba-healer-*`, `mamba-synchronizer-mba` | 30 s |
| `mamba-explorer-mba`, `mamba-quality-checker-mba` | 45 s |
| `mamba-scitex-expert-mba`, `mamba-todo-manager` | 60 s (heavier synthesis expected) |
| `mamba-verifier-mba`, `mamba-newbie-mba` | 60 s |

Never wait longer than 60 s. If an agent needs more than 60 s to reply to a one-line probe, it is dead for operational purposes.

### 3. Classify the reply

| Reply within window | State |
|---|---|
| Echo with `probe {N}` and timestamp | `:responsive` |
| Free-form text without the token | `:responsive-drifted` (replying, but not handling probes correctly — flag but don't restart) |
| Silence | `:unresponsive` |
| Orochi-level send failure (401, MCP dead, bun zombie) | `:mcp_broken` |
| Pane shows a known blocker (`:dev_channels_prompt`, `:permission_prompt`, `:paste_pending`) | `:pane_blocked` — unblock via `pane-state-patterns.md` actions, re-probe |

### 4. Act

| State | Action |
|---|---|
| `:responsive` | do nothing |
| `:responsive-drifted` | log to `#agent`, no restart |
| `:pane_blocked` | auto-unblock → re-probe once |
| `:mcp_broken` | `scitex-agent-container restart <yaml>` → re-probe once |
| `:unresponsive` after a restart attempt | **escalate** to `#escalation` with captured pane, restart log, last N ticks of heartbeat |

Never restart twice in one cycle. Two restarts in < 5 min means something systemic; second restart attempts should become `#escalation` events, not silent retries.

### 5. Report to `#agent` (not `#general`, not `#ywatanabe`)

One post per sweep, structured:

```
active-probe sweep @ 2026-04-14T04:10Z
| agent                       | state            | action             | after |
|----------------------------|------------------|-------------------|-------|
| head-mba                   | :responsive      | none              | OK    |
| mamba-healer-nas           | :responsive      | none              | OK    |
| mamba-synchronizer-mba     | :pane_blocked    | send 2, re-probe  | OK    |
| mamba-newbie-mba           | :unresponsive    | restart           | OK    |
| mamba-verifier-mba         | :mcp_broken      | restart           | FAIL  |
```

One line per agent. No narrative paragraphs. Rule #6 still applies — if every agent comes back `:responsive` with no action, post a single `active-probe sweep @ ts — 14/14 responsive, no action` and nothing else. Passing sweeps are boring by design; only state changes deserve detail.

## Invariants

1. **No ywatanabe in the loop.** The protocol runs entirely inside the fleet. If you find yourself asking ywatanabe "which agent didn't reply?" you have already failed — that is the question the probe *answers*, not asks.
2. **Compound with passive signals, never replace.** Active probe is the ground truth, passive signals are the cheap prefilter. Combine: `passive(:green) AND probe(:responsive)` → trust green. `passive(:green) AND probe(:unresponsive)` → passive classifier bug + dead agent simultaneously; escalate and file the classifier regression.
3. **Channel push is filtered before diffing.** Even the passive side must filter out channel pushes before computing `pane_diff`. `pane-state-patterns.md` § "Classification algorithm" should reference this subtraction explicitly; without it, every `@all hello` looks like forward motion.
4. **Probe responses are not `#general` chatter.** Responses flow into `#agent` by default (or a dedicated `#probe-echo` channel if volume justifies it). Responses to `#general` would cross-contaminate ywatanabe's inbox.
5. **Signed actuator trail.** Every probe send, every classification, every action writes `{prober, probed, probe_id, state, action, ts}` to `~/.scitex/orochi/fleet-watch/probe.log`. No invisible restarts.

## Mamba-healer responsibilities (explicit, for `/loop` prompts)

Copy-paste target for healer `/loop` prompts:

> Every 5 minutes: run active probe sweep over the agents in scope (all agents on my host + critical cross-host siblings).
> - For each agent: DM a structured `probe N @ ts` ping.
> - Wait up to 60 s per agent (parallelize sends so the whole sweep is < 60 s wall-clock).
> - Classify replies per `active-probe-protocol.md`.
> - Auto-remediate `:pane_blocked` and `:mcp_broken`, re-probe once.
> - Escalate `:unresponsive` after one failed remediation attempt.
> - Post one structured summary line to #agent. Silent if all-green and prior sweep was also all-green.
> - Append signed row to `~/.scitex/orochi/fleet-watch/probe.log`.
> - Do not ask ywatanabe anything.

Scope matrix (who probes whom) — start here, extend per host constraints:

| Healer | In-scope agents |
|---|---|
| `mamba-healer-mba` | all MBA agents (head-mba + mamba-{auth,explorer,healer,newbie,quality-checker,scitex-expert,skill-manager,synchronizer,todo-manager,verifier}-mba) |
| `mamba-healer-nas` | head-nas + mamba-healer-nas (self-included for counter-sanity: a healer that can't probe itself is broken) |
| `mamba-healer-ywata-note-win` | head-ywata-note-win (+ self) |
| `mamba-healer-spartan` (when it exists — currently a gap) | head-spartan |

Cross-host counter-verification: every healer additionally probes the **head** on one adjacent host, on a slower cadence (every 15 min), so a completely dead host gets caught even if its own healer is dead with it. `mamba-healer-nas` → probes `head-mba`; `mamba-healer-mba` → probes `head-nas`; etc. This adds O(n) cross-host probes but catches the "whole host silent" failure mode.

## What this replaces

- The rule-#6 "silent success" exemption that allowed healers to never post. Active probes force a sweep summary to `#agent`, which is **not** routine status spam — it is the ground-truth liveness signal.
- The pane-activity-as-liveness heuristic that mistakenly treated inbound channel pushes as forward motion. `active-probe-protocol.md` is the authoritative liveness signal; `pane-state-patterns.md` classification is a prefilter and action-table, not a verdict.
- Ad-hoc "head-mba sweep the fleet for stuck prompts every few hours" manual dispatches. Healers run this automatically; the dispatch request exists only to bootstrap the discipline, not as the permanent process.

## Anti-patterns

- **Probing from `#general` with `@all hello`.** That is ywatanabe's channel; healers must not impersonate the human. Use DM or `#agent`.
- **Waiting indefinitely for a slow reply.** 60 s cap, period. If an agent genuinely needs more than a minute to answer a ping, that agent is broken for real-time coordination purposes even if it eventually replies.
- **Restarting an agent that is `:responsive-drifted`.** Wrong response content is not cause for restart — log and monitor. Restart only `:unresponsive` and `:mcp_broken`.
- **Cascading restarts during a known maintenance window.** If `head-ywata-note-win` just finished a hub redeploy, the first sweep after redeploy will show transient `:mcp_broken` while sidecars reconnect. Healers must have a `post-redeploy grace window` (90 s) during which `:mcp_broken` is downgraded to `:reconnecting` and *not* actioned.
- **Doing passive-only sweeps on the suspicion that active probes cost tokens.** Token cost of a structured probe is trivial compared to fleet-wide broken state; never shortcut via passive-only. This is explicitly settled (msg #10673).

## Related

- `fleet-communication-discipline.md` rule #10 — `@all` override and 30 s ack timeout
- `fleet-communication-discipline.md` rule #11 — response-less = death, automate detection
- `pane-state-patterns.md` — classifier that prefilters before probes and handles `:pane_blocked` auto-unblock
- `fleet-resurrection-protocol.md` — 4-layer defense; this skill is the concrete ping mechanism for Layer 2
- `agent-health-check.md` — 8-step health checklist; active probe is step 9 (to be added)
- todo #419 — channel-push filtering fix in pane diff
- mamba-todo-manager msg #10675 — originating dispatch

## Change log

- **2026-04-14 (initial)**: Consolidated from the 2026-04-14 false-positive incident (ywatanabe msgs #10577 → #10673, mamba-todo-manager msg #10675). Codifies the "ping, wait 60s, restart if silent" recipe healers must run without human prompting. Author: mamba-skill-manager.
