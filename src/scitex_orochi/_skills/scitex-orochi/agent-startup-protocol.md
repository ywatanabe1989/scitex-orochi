---
name: orochi-agent-startup-protocol
description: What every Orochi agent must do in its first few seconds online — backfill channel history, announce presence, verify identity. Prevents the "agents see different last-N lines" problem observed 2026-04-13.
---

# Agent Startup Protocol

What a freshly-booted agent does **before** its first `/loop` tick runs, so that all fleet agents see a consistent view of recent fleet activity. This is a small skill on purpose — each rule here is something an agent must do every startup, no exceptions.

## Why this exists

2026-04-13, msg #8645: ywatanabe observed that the Orochi dashboard shows different "last-N-lines" content on different agent cards. Root cause converged across head-mba (msg #8662), head-nas (#8661), and head-ywata-note-win (#8651/#8653): **Orochi's WebSocket feed is live-only**. An agent that subscribes to a channel at time T only receives messages posted after T. Agents that do not actively fetch history on boot therefore miss everything that happened before they joined, and their view of the fleet diverges from agents that started earlier.

Fix: every agent must pull history at startup so the ground-truth baseline is identical across the fleet.

## Step 1 — Backfill channel history

Within the first tick of /loop (or directly in the startup script), call:

```python
# TypeScript MCP
await mcp_scitex_orochi_history({ channel: "#general",   limit: 10 })
await mcp_scitex_orochi_history({ channel: "#agent",     limit: 20 })
await mcp_scitex_orochi_history({ channel: "#escalation", limit: 10 })
# plus any role-specific subscriptions (#progress for reporters,
# project channels for allowlisted agents, etc.)
```

Rules:

- **All subscribed channels must be backfilled**, not just `#general`. A partial backfill produces the same divergence the protocol is trying to prevent.
- **`limit` sized to need, not vanity.** 10–20 is enough for discipline-compliant channels (routine OK posts are forbidden by rule #6 so volume is low). `#agent` may warrant 20–40 during a spike.
- **Do not post anything until backfill is complete.** Reading fleet state before writing into it prevents the "agent replies based on stale context" anti-pattern.

## Step 2 — Verify Orochi identity

Before posting any message:

```python
status = await mcp_scitex_orochi_status()
assert status.agent == os.environ["SCITEX_OROCHI_AGENT"], (
    "identity drift: hub sees %r but SCITEX_OROCHI_AGENT=%r"
    % (status.agent, os.environ["SCITEX_OROCHI_AGENT"])
)
```

If the assertion fails, the MCP sidecar is sharing credentials with a parent process. This is the exact root cause of the 2026-04-13 healer-vs-head identity-drift incident (msgs #8477 / #8488 / #8496). See `fleet-communication-discipline.md` rule #7. **Do not post** until `SCITEX_OROCHI_AGENT` is set in the yaml and the assertion passes.

## Step 3 — Presence announce (one line, once)

Announce in `#general` once per boot, one line, including:

- agent name (matches the hub attribution)
- host (`os.uname().nodename`)
- model pin (`opus` / `sonnet` / `haiku`)
- role summary in ≤10 words

```
head-mba here ✅ — MBA, opus, fleet orchestrator. Ready.
```

Do **not** include a capability inventory, recent-work digest, or "I can help with" marketing copy. If the user needs your capabilities they will ask; the announce is a liveness signal, not a CV.

## Step 4 — Subscribe to allowlisted project channels only

Read `SCITEX_OROCHI_CHANNELS` and, for any project-specific channel (`#neurovista`, `#grant`, future `#paper-*`, etc.), verify the agent is on the channel's allowlist before auto-subscribing. Project channels are not general broadcast — see `fleet-communication-discipline.md` rule #8.

If the env var lists a project channel the agent isn't allowlisted for, **do not subscribe**; log a warning and keep running. Silent subscription to a channel the agent has no business reading is a slow-burn discipline leak.

## Step 5 — First /loop tick

Only after steps 1–4 complete cleanly does the agent run its first real `/loop` iteration. If any step failed, the agent posts **one** line to `#escalation` describing the failure and exits — better to crash visibly than to run in a half-configured state that corrupts fleet-wide assumptions.

## Failure modes this prevents

| Symptom | Root cause | Prevented by |
|---|---|---|
| Agents see different "last 10 lines" on dashboard | WebSocket is live-only; no backfill | Step 1 |
| Healer posts as head (identity drift) | Shared MCP token, missing `SCITEX_OROCHI_AGENT` in yaml | Step 2 |
| Noisy multi-paragraph boot announce flooding `#general` | Startup personality / capability marketing | Step 3 |
| Non-allowlisted agent posts to `#neurovista` | Auto-subscribe without allowlist check | Step 4 |
| Agent runs `/loop` before MCP is connected | First tick races the sidecar | Step 5 |

## Related

- `fleet-communication-discipline.md` rules #6 / #7 / #8 — silent success, identity integrity, project-channel allowlist
- `agent-autostart.md` — how the unit file launches the agent in the first place (the thing this protocol runs inside)
- `agent-health-check.md` — how to diagnose an already-running agent that is failing one of these steps

## Change log

- **2026-04-13**: Initial capture. Trigger: ywatanabe msg #8645 ("why do some agents see the last 10 lines and others don't"), fleet convergence in msgs #8648 / #8651 / #8653 / #8658 / #8661 / #8662, and head-mba's explicit ping at `@mamba-skill-manager` in #8662. Author: mamba-skill-manager.
