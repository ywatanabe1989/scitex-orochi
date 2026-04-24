<!-- ---
-- Timestamp: 2026-04-17 00:38:46
-- Author: ywatanabe
-- File: /home/ywatanabe/proj/scitex-orochi/src/scitex_orochi/_skills/scitex-orochi/00-agent-types/README.md
-- --- -->

# Agent Types — Guidelines Only

This directory is a **taxonomy for humans**, not a binding contract.
**Actual agents can be defined freely by the user.** These files describe common shapes the fleet tends to grow, nothing more.

## What these files are

- Descriptive guidelines for recurring agent shapes in the Orochi fleet
- Reference for naming conventions, escalation paths, and lifecycle patterns
- Documentation — not read or enforced by any server code

## What these files are NOT

- **Not a schema** — no code parses these files to configure agents
- **Not role-to-channel bindings** — channel subscriptions are assigned per-agent by the user at runtime (MCP tools / REST API / web UI), never derived from type
- **Not permission policies** — read/write access is stored in `ChannelMembership` and edited by admins, not inferred from role
- **Not exhaustive** — a fleet may have agents that don't fit any type here, or hybrids, or one-offs. That is fine.

## Catalog

| File | Type | Category |
|------|------|----------|
| `00-fleet-lead.md` | Lead | Communicator |
| `01-head.md` | Head | Communicator |
| `02-proj.md` | Proj | Dedicated Scope |
| `03-expert.md` | Expert | Dedicated Scope |
| `04-worker.md` | Worker | Repetitive Tasks |
| `05-daemon.md` | Daemon | Repetitive Tasks |
| `90-policies.md` | Anti-patterns, legacy migration, daemon host policy | Shared |
| `99-template.md` | Template for new types | Shared |

## Key principle

> Types are hints, not rules. The user decides what each agent is, what channels it joins, and what it can do.

If you find yourself editing server code to make it match a type definition here, stop — you have it backwards. The server is the source of truth for runtime behavior; these docs only describe patterns that have worked.

## When to add a new type file

- A shape repeats across three or more agents with stable properties
- A contributor asks "what's the convention for X?" more than once

## When not to add one

- For a single agent with unusual needs — just build the agent
- To enforce a rule — put the rule in server code or channel ACL, not here

<!-- EOF -->
