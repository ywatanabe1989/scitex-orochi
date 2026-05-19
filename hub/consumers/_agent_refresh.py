"""``agent.subs_refresh`` channel-layer event handler for AgentConsumer.

Fired from ``hub.signals`` post_save/post_delete on ``ChannelMembership``
(issue #282) so out-of-band subscription changes propagate to live WS
consumers without waiting for reconnect. Extracted from ``_agent.py``
to stay under the 512-line cap.

This module also hosts :func:`prehydrate_channels` (scitex-orochi#451),
the connect-time rehydration helper used by :class:`AgentConsumer` to
make group-channel delivery robust to missing ``register`` frames.
"""

from __future__ import annotations

from ._groups import _sanitize_group, log
from ._helpers import _load_agent_channel_subs, _load_agent_mention_only_channels


async def prehydrate_channels(consumer) -> None:
    """Rejoin persisted group channels + seed ``agent_meta`` at connect.

    scitex-orochi#451 — closes the orphan-on-reconnect deafness window.

    Background. On a WS reconnect, the authoritative sequence is:

        client  connects → server connect()              → joins DM groups
        client  sends register                             → server handle_register
                                                              → loads group subs from DB
                                                              → group_add(each)
                                                              → sets agent_meta["channels"]

    Between ``connect()`` completing and ``handle_register`` running,
    ``agent_meta`` is absent. The ``chat_message`` filter in
    :class:`AgentConsumer` requires ``agent_meta["channels"]`` to contain
    the target channel for group messages; without it every group
    message is silently dropped. If the client never sends ``register``
    (buggy reconnect logic, network blip between open and first send),
    the agent is silently deaf forever — it appears connected but
    receives no group-channel messages.

    This helper runs at the end of ``connect()`` and makes the server
    robust to both races: it pre-joins persisted group memberships from
    the DB and seeds ``agent_meta["channels"]`` with the union of DM
    channels + persisted group memberships. ``handle_register`` remains
    idempotent and will refresh the same state (plus the richer metadata
    payload) when the client's register frame arrives.

    ``consumer._registered`` is set to False here; ``handle_register``
    flips it True on success. The ``message``-frame dispatch guards on
    ``_registered`` so un-registered connections can't silently succeed
    at writes while missing replies (scitex-orochi#451 contract).
    """
    consumer._registered = False
    try:
        persisted = await _load_agent_channel_subs(
            consumer.workspace_id, consumer.agent_name
        )
    except Exception:  # noqa: BLE001 — DB hiccups at connect must not tear down
        log.exception(
            "connect: pre-hydrate group channels failed for %s",
            consumer.agent_name,
        )
        persisted = []

    try:
        consumer._mention_only_channels = await _load_agent_mention_only_channels(
            consumer.workspace_id, consumer.agent_name
        )
    except Exception:  # noqa: BLE001
        consumer._mention_only_channels = set()

    dm_names = list(getattr(consumer, "_dm_channel_names", []) or [])
    channels = list(dm_names) + [c for c in persisted if c not in dm_names]

    for ch_name in persisted:
        group = _sanitize_group(
            f"channel_{consumer.workspace_id}_{ch_name}"
        )
        await consumer.channel_layer.group_add(group, consumer.channel_name)

    # Seed a minimal agent_meta so chat_message's membership filter
    # works before ``handle_register`` runs. ``handle_register`` (which
    # is idempotent) will replace this dict with the full payload.
    consumer.agent_meta = {"channels": channels}


async def handle_agent_subs_refresh(consumer, event):
    """Re-sync ``consumer.agent_meta["channels"]`` + group joins from DB.

    Events whose ``workspace_id`` doesn't match this connection are
    ignored — the signal broadcasts globally via
    ``list_sibling_channels`` which is not workspace-scoped.
    """
    event_ws = event.get("workspace_id")
    if event_ws is not None and event_ws != consumer.workspace_id:
        return
    if event.get("agent") and event["agent"] != consumer.agent_name:
        return

    persisted = await _load_agent_channel_subs(
        consumer.workspace_id, consumer.agent_name
    )
    consumer._mention_only_channels = await _load_agent_mention_only_channels(
        consumer.workspace_id, consumer.agent_name
    )
    dm_names = list(getattr(consumer, "_dm_channel_names", []) or [])
    desired = list(dict.fromkeys(list(dm_names) + list(persisted)))
    current = list(
        getattr(consumer, "agent_meta", {}).get("channels", []) or []
    )

    desired_set = set(desired)
    current_set = set(current)
    to_add = desired_set - current_set
    # Never group_discard DM channels — those are auto-subscribed at
    # connect based on DMParticipant and must not be affected by a
    # refresh driven by a group-channel ChannelMembership change.
    to_remove = {
        ch for ch in (current_set - desired_set) if not ch.startswith("dm:")
    }

    for ch_name in to_add:
        group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
        await consumer.channel_layer.group_add(group, consumer.channel_name)
    for ch_name in to_remove:
        group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
        await consumer.channel_layer.group_discard(
            group, consumer.channel_name
        )

    if hasattr(consumer, "agent_meta"):
        consumer.agent_meta["channels"] = desired
    else:
        consumer.agent_meta = {"channels": desired}

    if to_add or to_remove:
        from hub.registry import register_agent

        register_agent(
            consumer.agent_name, consumer.workspace_id, consumer.agent_meta
        )
        await consumer.channel_layer.group_send(
            consumer.workspace_group,
            {
                "type": "agent.info",
                "agent": consumer.agent_name,
                "info": consumer.agent_meta,
            },
        )
