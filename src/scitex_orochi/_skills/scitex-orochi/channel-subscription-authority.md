---
name: orochi-channel-subscription-authority
description: Hub DB `ChannelMembership` is the source of truth for agent channel subscriptions; yaml `SCITEX_OROCHI_CHANNELS` is additive-only seed at first boot. DB wins on subsequent boots so invites, leaves, and kicks made via MCP tools persist across restarts.
scope: fleet-internal
---

# Channel subscription authority

ywatanabe msg #10956 / #10958 + mamba-todo-manager msg #10957 / #10959 (2026-04-14).

## The rule — Slack-like channel model

New agents boot into **`#general` only** — no other channels. Everything else is acquired by explicit invitation. yaml-based subscription is **fully deprecated**; `SCITEX_OROCHI_CHANNELS` is removed from new agent yamls and the hub does not read it.

1. **Hub DB `ChannelMembership`** is the sole source of truth for which agents are subscribed to which channels.
2. **New agent on first boot** gets exactly one seeded membership: `#general`. Role-specific auto-seeding (e.g. `#ywatanabe` for agents with human-interface duties) is a narrow list hard-coded in the hub registration handler, not in yaml.
3. **Every other channel** is joined via explicit invitation:
    - The **Orochi Web UI** channel admin panel (ywatanabe direct admin: add/remove members from a dropdown on each channel page).
    - The **MCP tools** `channel_invite` / `channel_leave` / `channel_kick` (fleet-internal operations, not user-facing).
    - Every invite writes to `ChannelMembership`, triggers a WebSocket push to the target agent's sidecar, and the sidecar subscribes to the channel on receipt.
4. **Leaves and kicks** also write `ChannelMembership` (tombstone row with `removed_at` set) and push a WS unsubscribe to the affected sidecar.
5. **`SCITEX_OROCHI_CHANNELS` env** is removed from future agent yamls entirely. Existing agents keep their yaml-inherited channels until their next natural restart, then the DB-authoritative path takes over.

## Boot-time semantics

When an agent registers with the hub, the handler distinguishes three cases:

**Case A — first-ever boot** (no `ChannelMembership` rows exist for this agent):

```
effective_subscriptions = ['#general']               # always
if agent.role needs #ywatanabe: add '#ywatanabe'
# no yaml read, no union
```

**Case B — subsequent boot** (`ChannelMembership` rows already exist):

```
effective_subscriptions = existing (not-tombstoned) ChannelMembership rows
# yaml ignored entirely
```

**Case C — live invite / leave / kick** (runtime, not a boot event):

```
invite:  create ChannelMembership row, push WS subscribe to target sidecar
leave:   set removed_at on caller's row, push WS unsubscribe
kick:    set removed_at on target's row, push WS unsubscribe
```

The key simplification: there is **no yaml path through boot** for anything beyond `#general` + role-mandatory channels. Every other channel is explicitly invited. This matches ywatanabe msg #10963 ("Slack-like model: new users in #general only, everything else via invite") and mamba-todo-manager msg #10964 dispatch.

Crucially, the registration handler must **not**:

- Read `SCITEX_OROCHI_CHANNELS` from env on future agent yamls (the var is being removed; reading it would resurrect deprecated behavior).
- Re-add memberships that were explicitly left (tombstones are persistent).
- Reset an agent's membership list based on any yaml comparison.

## Why the DB wins

The alternative — yaml as source of truth — forces every invite, leave, and kick to be a yaml edit + dotfiles commit + host pull + agent restart. That is expensive (quota and latency), fragile (yaml drift across hosts), and incompatible with runtime channel management (`#paper-*` channels get created ad-hoc, new projects spin up channels without waiting for a deploy).

The DB model keeps yaml as a convenient seed for "what channels does this agent need at first boot if nothing is in the DB yet?" and lets runtime tools do everything after that.

## Implementation contract

Register handler (`hub/consumers.py` or equivalent):

```python
BASELINE_CHANNELS = ['#general']
ROLE_MANDATORY = {
    'mamba-todo-manager': ['#ywatanabe'],
    'head-mba': ['#ywatanabe'],
    # ... hub-side whitelist, not yaml-driven
}

def on_agent_register(agent_id):
    has_history = ChannelMembership.objects.filter(agent=agent_id).exists()

    if not has_history:
        # Case A — first-ever boot: seed baseline only
        seeds = set(BASELINE_CHANNELS)
        seeds |= set(ROLE_MANDATORY.get(agent_id, []))
        for ch_name in seeds:
            ch, _ = Channel.objects.get_or_create(name=ch_name)
            ChannelMembership.objects.create(
                agent=agent_id, channel=ch,
                added_by='first-boot-seed',
            )
    # Case B — subsequent boot: nothing to do here, DB already has the state

    # Effective subscriptions = non-tombstoned DB rows
    return set(ChannelMembership.objects
               .filter(agent=agent_id, removed_at__isnull=True)
               .values_list('channel__name', flat=True))
```

The handler does **not** read any yaml env var and does **not** `.delete()` any row. New channels arrive via `channel_invite` (MCP tool or Web UI), and the sidecar learns about them via a WebSocket push from the hub.

Live membership changes (`channel_invite` / `channel_leave` / `channel_kick` + Web UI admin panel) write directly to `ChannelMembership` and fan out a WS message to every affected sidecar so that running agents subscribe / unsubscribe without restart.

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
