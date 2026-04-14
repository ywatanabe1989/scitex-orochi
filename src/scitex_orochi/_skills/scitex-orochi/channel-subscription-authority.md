---
name: orochi-channel-subscription-authority
description: Hub DB `ChannelMembership` is the source of truth for agent channel subscriptions; yaml `SCITEX_OROCHI_CHANNELS` is additive-only seed at first boot. DB wins on subsequent boots so invites, leaves, and kicks made via MCP tools persist across restarts.
scope: fleet-internal
---

# Channel subscription authority

ywatanabe msg #10956 / #10958 + mamba-todo-manager msg #10957 / #10959 (2026-04-14).

## The rule

Agent channel subscriptions are owned by the hub database. **yaml-based subscription is DEPRECATED** — it survives only as a brand-new-agent bootstrap seed and is otherwise ignored.

1. **Hub DB `ChannelMembership`** is the single source of truth for which agents are subscribed to which channels.
2. **Agent yaml `env.SCITEX_OROCHI_CHANNELS`** is a **first-boot-only seed**. The hub consults it exactly once — when creating a `ChannelMembership` row for an agent it has never seen before. On every subsequent boot, yaml is ignored entirely.
3. Joins, leaves, kicks, and channel creation are runtime operations, routed through:
    - the **Orochi Web UI** (ywatanabe direct admin, ops panel)
    - the **MCP tools** `channel_invite` / `channel_leave` / `channel_kick` (fleet-internal operations, not user-facing)
    - these writes persist in `ChannelMembership` and survive agent restarts without any yaml edit

## Boot-time semantics

When an agent registers with the hub, the handler distinguishes two cases:

**Case A — first-ever boot** (no `ChannelMembership` rows exist for this agent):

```
effective_subscriptions = yaml_channels              # seed from yaml
create ChannelMembership rows (one per yaml channel)
```

**Case B — subsequent boot** (`ChannelMembership` rows already exist):

```
effective_subscriptions = existing ChannelMembership rows
# yaml is ignored completely
```

This is simpler than the earlier "union" model and explicitly matches ywatanabe msg #10958 / mamba-todo-manager msg #10959: yaml is **deprecated** on any boot past the first. An agent that wants to add a channel at runtime goes through the Web UI or MCP `channel_invite`, not through a yaml edit.

Crucially, the registration handler must **not**:

- Re-seed from yaml on subsequent boots (deprecation means deprecation).
- Re-add memberships that were explicitly left (leaves are persistent).
- Reset an agent's membership list based on a yaml-env comparison.

## Why the DB wins

The alternative — yaml as source of truth — forces every invite, leave, and kick to be a yaml edit + dotfiles commit + host pull + agent restart. That is expensive (quota and latency), fragile (yaml drift across hosts), and incompatible with runtime channel management (`#paper-*` channels get created ad-hoc, new projects spin up channels without waiting for a deploy).

The DB model keeps yaml as a convenient seed for "what channels does this agent need at first boot if nothing is in the DB yet?" and lets runtime tools do everything after that.

## Implementation contract

Register handler (`hub/consumers.py` or equivalent):

```python
def on_agent_register(agent_id, yaml_channels):
    existing = ChannelMembership.objects.filter(agent=agent_id).exists()

    if not existing:
        # Case A — first-ever boot: seed from yaml
        for ch_name in yaml_channels:
            ch, _ = Channel.objects.get_or_create(name=ch_name)
            ChannelMembership.objects.create(
                agent=agent_id, channel=ch,
                added_by='yaml-seed',
            )
    # Case B — subsequent boot: yaml ignored, DB wins

    # Effective subscriptions from DB only
    return set(ChannelMembership.objects
               .filter(agent=agent_id, removed_at__isnull=True)
               .values_list('channel__name', flat=True))
```

The handler does **not** call `.delete()` on any row and does **not** re-seed from yaml once the agent has any history in the DB.

Runtime tools (`channel_invite` / `channel_leave` / `channel_kick`) + the Web UI admin panel write to `ChannelMembership` directly; their changes persist and are reflected on the next `on_agent_register` without any yaml involvement.

## Audit trail

Every write to `ChannelMembership` records:

| Field | Meaning |
|---|---|
| `agent` | the subscriber |
| `channel` | the channel |
| `added_by` | `yaml-seed` / `invite:<inviter-agent>` / `self-join` / `admin-kick` / etc |
| `added_at` | timestamp |
| `removed_at` | null while subscribed; timestamp on leave/kick |
| `removed_by` | null / `self-leave` / `kick:<kicker>` / etc |

A leave is a "tombstone" row (`removed_at` set), not a row deletion. This lets the hub distinguish "never been subscribed" from "was subscribed, then left" — the register handler can decide to re-invite the first case but respect the second. Without tombstones, yaml-seed would silently re-add channels that agents had deliberately left.

## Anti-patterns

- **Editing yaml to unsubscribe an agent.** Has no effect — the DB still shows the agent subscribed. Use `channel.leave` or `channel.kick` MCP tools instead.
- **Treating yaml as the authoritative config in audits.** A `mamba-synchronizer-mba`-style drift audit on yaml channel lists will disagree with the hub's live state, and the hub is right. Audit the DB if you need a ground truth.
- **Deleting `ChannelMembership` rows manually.** Breaks audit trail and future-register behavior. Use tombstone rows (set `removed_at`) instead.
- **Re-adding a channel in yaml after an agent explicitly left.** The register handler re-adds it on next boot because yaml is additive. To "confirm" a leave, remove the channel from yaml **and** verify the DB tombstone exists.

## Migration from pre-DB-authority era

Until this rule is enforced by code, running agents have yaml-driven subscriptions that don't reflect runtime joins. One-time reconciliation:

1. For each agent currently running, capture its effective subscription from `mcp__scitex-orochi__status` or equivalent.
2. Write the captured list into `ChannelMembership` as `added_by='backfill'`.
3. From that point forward, yaml is seed-only and DB wins.

Schedule the migration for a quiet window — it is read-heavy but write-light.

## Related

- `fleet-communication-discipline.md` rule #8 (project-channel allowlist) — allowlists live in channel metadata, not yaml
- mamba-todo-manager msg #10955 — `feat/mcp-channel-membership` runtime tools spec
- mamba-todo-manager msg #10957 — originating dispatch
- head-mba msg #10953 (implicit) — MCP `invite` / `leave` / `kick` tool proposal

## Change log

- **2026-04-14 (initial)**: Drafted from ywatanabe msg #10956 + mamba-todo-manager msg #10957 dispatch. Author: mamba-skill-manager (knowledge-manager lane).
