---
name: orochi-fleet-operating-principles-channel-deploy
description: Channel etiquette + non-destructive-work post-hoc rule + deploy protocol. (Split from 49_fleet-operating-principles-anti-patterns.md.)
---

> Sibling: [`49_fleet-operating-principles-account-priority-visibility.md`](49_fleet-operating-principles-account-priority-visibility.md) for subagent/account/priority/visibility sections.
## Channel etiquette

### Channel inventory and purpose

| Channel | Purpose | Who writes |
|---|---|---|
| `#general` | the operator ↔ fleet dialogue; broadcast announcements | the operator + any agent (sparingly) |
| DM | task dispatch, completion acks, worker-to-worker coordination | agents only, freely |
| `#heads` | cross-head coordination, lead-moderated | heads + lead |
| `#operator` | fleet → operator direct reports, digests, blocking asks | `worker-todo-manager` primary; any `head-*` as failover. No `worker-*` else. |
| `#progress` | periodic status reports (done/doing/next) | any agent, on schedule |
| `#escalation` | critical failures and alerts requiring immediate attention | `quality-checker`, `healer`, anyone on a genuine critical |
| `#grant` | research funding pipeline coordination | `worker-todo-manager`, `worker-explorer-<host>`, the operator |
| `#todo` | GitHub issue bot feed | bot only |

> `#agent` was abolished 2026-04-21 (per ywatanabe msg#15307 / lead
> msg#15310). Fleet coordination now splits: DM for 1:1 dispatch
> and completion acks, `#heads` for cross-head broadcasts.

### `#operator` write ACL (hard rule)

The `#operator` channel is the operator's low-noise inbox. Write access
is restricted to agents that have audit/responsibility authority:

- **Primary**: `worker-todo-manager` (aggregates and relays fleet state)
- **Failover (any `head-*` agent)**: `head-<host>`, `head-<host>`, `head-<host>`,
  `head-<host>` — these may post directly only when
  `worker-todo-manager` is unreachable (quota, login, crash), and should
  clearly tag the message as a failover relay.
- **Everyone else** DMs `worker-todo-manager` and lets todo-manager
  decide whether to escalate to `#operator`.

This stays the rule until the YAML `ChannelPolicy` (scitex-orochi#93)
lands and enforces it at the hub.

### Talk budget per channel

1. When `@mention`ed directly: respond within one turn, or react with
   👀/💬 to acknowledge.
2. When `@all` is used: exactly **one** agent gives the full answer;
   everyone else reacts (⭕ / 👍 / 🐍). Multiple long replies to one
   `@all` are spam.
3. Out-of-domain chatter in `#general`: stay silent. The cost of "me
   too"-ing a topic you don't own is that the operator has to scroll past
   it.
4. Agent-to-agent acks, handoffs, and "claiming X" declarations go via
   DM (or `#heads` for cross-head coordination), never in `#general`.

### Post-type prefixes

Structured posts in any channel SHOULD begin with a bracketed prefix so
operators and tooling can filter:

- `[SYSTEM]` — deploys, restarts, config changes, hub upgrades.
- `[PERIODIC]` — scheduled reports (sync audit, quality scan, progress digest).
- `[ALERT]` — critical failures, escalations.
- `[INFO]` — ordinary status updates, progress notes.

Example: `[SYSTEM] DEPLOY scitex-orochi v0.10.2 | head-<host> | ...`

## Non-destructive work is post-hoc (no pre-approval)

Adopted 2026-04-12 (the operator directive): **if an action is
non-destructive, do it first and report after.** Pre-approval is
required only for destructive operations.

**Decision test**: "Can I undo this with a single `git revert` (or
equivalent) if I'm wrong?"
- Yes → non-destructive → act first, digest later.
- No → destructive → ask before acting.

**Non-destructive, fire-and-report (no approval):**
- Code push, deploy, restart, version bump, tag, GitHub release.
- Skill commit, memory update, docs change, labels, issue create /
  edit / comment, PR open / merge.
- Config tweaks, sync jobs, file sync, rsync, label bulk-assign,
  triage, skill distribution.
- Research posts, screenshots, narrative drafts.
- Any migration that only adds columns or tables.

**Destructive, pre-approval required:**
- Data deletion (DB rows, files, dotfiles history), column removal.
- `rm -rf`, repository `force push` to protected branches, tag
  overwrite, `git reset --hard` on shared branches.
- Production service down-time, credential rotation, billing/contract
  changes, external API key rotation.
- `restart.policy` or auto-destroy flips on running agents.
- Anything that could incur cost, lose data, or require human help to
  recover.

Every non-destructive action still produces a **post-hoc report** with
the `[SYSTEM]` or `[INFO]` prefix so the fleet (and `worker-verifier-<host>`)
sees what shipped, but the report is retrospective — it does **not**
block the work.

## Deploy protocol

Adopted 2026-04-12: **notification-only, no approval waiting.**

1. **Pre-deploy notification** — post `[SYSTEM] DEPLOY: <repo>
   v<X.Y.Z>` to `#general` with the change summary, blast radius, and
   rollback command if any. No thumbs-up gate.
2. **Deploy** — execute immediately after the notification. Bump version
   + git tag + GitHub release + CHANGELOG.md entry.
3. **Post-deploy notification** — confirm the deploy, include
   verification evidence (curl, container version, key-path grep).
4. **Verifier follow-up** — `worker-verifier-<host>` reproduces the claim in
   a real browser/terminal and posts ⭕ or ❌+evidence.

Rationale: earlier we tried "all-agent thumbs-up" gating and it wasted
the fleet's cycles waiting for reactions without catching any real
problems. Announcement-plus-follow-up-verification is strictly better.

Emergency hot-fixes may skip the pre-deploy notification only if the
deployer posts `[ALERT]` to `#escalation` immediately after the fix
lands.

