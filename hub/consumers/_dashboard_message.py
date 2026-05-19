"""``message``-frame handler + @mention auto-reply for the dashboard.

Pulled out of ``_dashboard.py`` so the consumer module stays under the
512-line cap. Mirrors the structure of ``_agent_message`` for the
agent-side ``message`` frame.
"""

from __future__ import annotations

import re

from hub.models import Workspace

from ._groups import _is_fleet_channel, _sanitize_group, log


async def handle_dashboard_message(consumer, content):
    """Process an inbound ``message`` frame from a DashboardConsumer client."""
    payload = content.get("payload", {})
    # Support channel/text inside payload (canonical) or at top level.
    ch_name = payload.get("channel") or content.get("channel") or "#general"
    # Normalize group channel names: ensure # prefix (#326)
    if not ch_name.startswith("dm:") and not ch_name.startswith("#"):
        ch_name = "#" + ch_name
    text = (
        payload.get("content")
        or payload.get("text")
        or content.get("text")
        or content.get("content")
        or ""
    )

    # Normalize top-level attachments into metadata (upload.js path).
    metadata = dict(payload.get("metadata", {}) or {})
    if "attachments" in payload and "attachments" not in metadata:
        metadata["attachments"] = payload.get("attachments") or []

    # Lazy-create DM channel + participants on first send from
    # the dashboard WS path so human↔agent DMs work without a
    # pre-flight POST /api/dms/. Mirrors the AgentConsumer and
    # REST api_messages paths.
    if ch_name.startswith("dm:"):
        from asgiref.sync import sync_to_async as _sta

        from hub.views.api import _ensure_dm_channel

        await _sta(_ensure_dm_channel)(
            await _sta(Workspace.objects.get)(id=consumer.workspace_id),
            ch_name,
        )

        # Self-subscribe to the DM group so our own echo + any
        # reply reaches this dashboard. Without this, a brand-new
        # DM created by this send would not deliver back on the
        # same WS (the connect-time auto-subscribe only covered
        # DMs that existed at connect).
        _dm_grp = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
        await consumer.channel_layer.group_add(_dm_grp, consumer.channel_name)
        if not hasattr(consumer, "_dm_channel_names"):
            consumer._dm_channel_names = []
        if ch_name not in consumer._dm_channel_names:
            consumer._dm_channel_names.append(ch_name)

    msg = await consumer._save_message(
        channel_name=ch_name,
        sender=consumer.user.username,
        content_text=text,
        metadata=metadata,
    )

    is_dm = ch_name.startswith("dm:")
    kind = "dm" if is_dm else "group"

    group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
    await consumer.channel_layer.group_send(
        group,
        {
            "type": "chat.message",
            "id": msg["id"] if msg else None,
            "sender": consumer.user.username,
            "sender_type": "human",
            "channel": ch_name,
            "kind": kind,
            "text": text,
            "ts": msg["ts"] if msg else None,
            "metadata": metadata,
        },
    )

    # Spec v3 §3.3 — skip workspace fanout for DM channels.
    if not is_dm:
        await consumer.channel_layer.group_send(
            consumer.workspace_group,
            {
                "type": "chat.message",
                "id": msg["id"] if msg else None,
                "sender": consumer.user.username,
                "sender_type": "human",
                "channel": ch_name,
                "kind": kind,
                "text": text,
                "ts": msg["ts"] if msg else None,
                "metadata": metadata,
            },
        )

    # Web Push fan-out (todo#263).
    try:
        from hub.push import send_push_to_subscribers_async

        send_push_to_subscribers_async(
            workspace_id=consumer.workspace_id,
            channel=ch_name,
            sender=consumer.user.username,
            content=text,
            message_id=msg["id"] if msg else None,
        )
    except Exception:
        log.exception("push fan-out failed (dashboard path)")

    # Cross-channel @mention push (msg#15767). Best-effort; wrapped in
    # sync_to_async because the helper touches the ORM + channel layer
    # synchronously. No-ops for DM channels and mention-less messages.
    try:
        from asgiref.sync import sync_to_async as _sta2

        from hub.mentions import expand_mentions_and_notify

        await _sta2(expand_mentions_and_notify)(
            workspace_id=consumer.workspace_id,
            source_channel=ch_name,
            source_msg_id=msg["id"] if msg else None,
            sender_username=consumer.user.username,
            text=text,
        )
    except Exception:
        log.exception("mention push fan-out failed (dashboard path)")

    # @mention auto-reply (issue #98): when a message contains @agentname,
    # hub immediately posts a brief system status for the mentioned agent
    # so the sender knows whether it's alive and what it's doing.
    #
    # todo#405: never auto-post `[agent] status: online / (no recent activity)`
    # into user-facing channels. User channels are the ywatanabe ↔ fleet
    # interface (per `fleet-communication-discipline.md` rule #8); status
    # replies belong in fleet channels only. `@all` from ywatanabe used to
    # explode into 12+ status replies flooding the feed.
    if "@" in text and not is_dm and _is_fleet_channel(ch_name):
        await _maybe_mention_reply(consumer, text, ch_name)


async def _maybe_mention_reply(consumer, text: str, ch_name: str) -> None:
    """Post a brief system status reply when an @mention is detected (issue #98).

    Parses all @word tokens from the message. For each token that matches
    a known agent name in the registry, posts a system message with the
    agent's last recent_actions (up to 5 lines) and its online/offline
    status.
    """
    from hub.registry import get_agents

    mentioned = re.findall(r"@([\w\-\.]+)", text)
    if not mentioned:
        return

    all_agents = get_agents(consumer.workspace_id)
    agents = {a["name"]: a for a in all_agents}
    all_names = list(agents.keys())

    # Expand group mentions to individual agent names
    GROUP_PATTERNS = {
        "heads": lambda n: n.startswith("head-"),
        "healers": lambda n: n.startswith("mamba-healer"),
        "mambas": lambda n: n.startswith("mamba-"),
        "all": lambda n: True,
        "agents": lambda n: True,
    }
    expanded: list[str] = []
    for token in mentioned:
        if token in GROUP_PATTERNS:
            expanded.extend(n for n in all_names if GROUP_PATTERNS[token](n))
        else:
            expanded.append(token)
    mentioned = list(dict.fromkeys(expanded))  # deduplicate, preserve order

    for name in mentioned:
        info = agents.get(name)
        if not info:
            continue
        status = info.get("status", "unknown")
        recent = info.get("recent_actions") or []
        lines = list(recent)[-5:]  # last 5 actions
        last_seen = info.get("last_seen", "")
        if lines:
            activity = "\n".join(f"  {line}" for line in lines)
        else:
            activity = "  (no recent activity)"
        reply_text = (
            f"[{name}] status: {status}"
            + (f" | last seen: {last_seen}" if last_seen else "")
            + f"\nRecent activity:\n{activity}"
        )
        mention_msg = await consumer._save_message(
            channel_name=ch_name,
            sender="hub",
            content_text=reply_text,
            metadata={"source": "mention_reply", "agent": name},
        )
        # Only broadcast to the specific channel group (not workspace-wide).
        # Workspace-wide broadcast caused all agents to receive mention_reply
        # messages regardless of channel subscription, wasting tokens (#405).
        group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
        await consumer.channel_layer.group_send(
            group,
            {
                "type": "chat.message",
                "id": mention_msg["id"] if mention_msg else None,
                "sender": "hub",
                "sender_type": "system",
                "channel": ch_name,
                "kind": "group",
                "text": reply_text,
                "ts": mention_msg["ts"] if mention_msg else None,
                "metadata": {"source": "mention_reply", "agent": name},
            },
        )
