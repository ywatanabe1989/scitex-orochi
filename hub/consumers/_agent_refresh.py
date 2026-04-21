"""``agent.subs_refresh`` channel-layer event handler for AgentConsumer.

Fired from ``hub.signals`` post_save/post_delete on ``ChannelMembership``
(issue #282) so out-of-band subscription changes propagate to live WS
consumers without waiting for reconnect. Extracted from ``_agent.py``
to stay under the 512-line cap.
"""

from __future__ import annotations

from ._groups import _sanitize_group
from ._helpers import _load_agent_channel_subs


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
