"""``message``-frame handler for :class:`hub.consumers.AgentConsumer`.

Extracted from the original 1556-line ``hub/consumers.py`` to keep
``_agent.py`` under the 512-line cap. The handler is a free function
that receives the consumer as its first argument so it can use the
consumer's bound state (workspace id, agent name, ``_save_message``)
without becoming a method.
"""

from __future__ import annotations

from hub.channel_acl import check_membership_allowed, check_write_allowed
from hub.models import Workspace

from ._groups import _sanitize_group, log


async def handle_agent_message(consumer, content):
    """Process an inbound ``message`` frame from an AgentConsumer client.

    Mirrors the v3 spec rules: lazy-create DM channels + participants,
    enforce channel ACLs, normalize attachment metadata, persist the
    message via the consumer's ``_save_message`` method, then fan out
    to the channel group (and the workspace group, except for DMs).
    """
    payload = content.get("payload", {})
    # Support channel/text inside payload (canonical) or at top level (legacy TS clients)
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

    # Lazy-create DM channel + participants so first-time DMs
    # work from the WS path too — check_write_allowed() denies
    # writes to dm: channels that have no Channel row yet, and
    # the sending agent must be recorded as a participant for
    # its own write to be allowed. Mirrors the REST path in
    # hub/views/api.py::api_messages.
    from asgiref.sync import sync_to_async as _sta

    if ch_name.startswith("dm:"):
        from hub.views.api import _ensure_dm_channel

        await _sta(_ensure_dm_channel)(
            await _sta(Workspace.objects.get)(id=consumer.workspace_id),
            ch_name,
        )

    # Channel ACL enforcement — check before persisting or broadcasting.
    # check_write_allowed is a sync call (file-cached, sub-ms) so safe to
    # call directly in the async consumer.
    # check_write_allowed may touch the DB for DM channels, so
    # route through sync_to_async. For non-DM channels it's a
    # cached yaml lookup (sub-ms).
    _allowed = await _sta(check_write_allowed)(
        consumer.agent_name, ch_name, consumer.workspace_id
    )
    if not _allowed:
        log.warning(
            "[ACL] blocked write from %s to %s",
            consumer.agent_name,
            ch_name,
        )
        await consumer.send_json(
            {
                "type": "error",
                "code": "acl_denied",
                "message": f"You are not allowed to write to {ch_name}",
            }
        )
        return

    # Issue #276 — close the WS write-path ACL gap. AgentConsumer
    # authenticates as the synthetic ``agent-<name>`` user; the
    # membership gate requires an explicit ChannelMembership row for
    # non-DM channels so agents cannot write to channels they were
    # never subscribed to.
    _member_allowed = await _sta(check_membership_allowed)(
        f"agent-{consumer.agent_name}", ch_name, consumer.workspace_id
    )
    if not _member_allowed:
        log.warning(
            "[ACL] blocked non-member write from %s to %s",
            consumer.agent_name,
            ch_name,
        )
        await consumer.send_json(
            {
                "type": "error",
                "code": "not_a_member",
                "message": f"You are not a member of {ch_name}",
            }
        )
        return

    # Attachments may arrive either nested in metadata (new clients)
    # or at the payload top-level (upload.js). Normalize into one
    # metadata dict so both persistence and broadcast carry them.
    metadata = dict(payload.get("metadata", {}) or {})
    if "attachments" in payload and "attachments" not in metadata:
        metadata["attachments"] = payload.get("attachments") or []

    # Update activity timestamp — this is a meaningful action,
    # distinct from a passive heartbeat.
    from hub.registry import mark_activity, mark_echo_alive

    mark_activity(consumer.agent_name, action=text[:120])

    # msg#15538 — auto-green the 4th LED (ECHO) on any inbound agent
    # message. Previously the LED only turned green after the hub→agent
    # nonce round-trip in ``_hub_echo_loop`` succeeded; if the agent's
    # MCP-client couldn't reply to the nonce the LED stayed amber / red
    # even though the agent was obviously orochi_alive — it had just sent a
    # chat message. ``mark_echo_alive`` advances the same
    # ``last_nonce_echo_at`` timestamp the nonce-probe setter writes,
    # so the existing LED renderer (no frontend change needed) sees the
    # hot timestamp regardless of nonce-probe success. The two
    # mechanisms together are a strictly stronger liveness signal.
    mark_echo_alive(consumer.agent_name)

    # Persist message
    msg = await consumer._save_message(
        channel_name=ch_name,
        sender=consumer.agent_name,
        content_text=text,
        metadata=metadata,
    )

    # Broadcast to channel group. Use the *merged* metadata
    # (which now includes top-level payload.attachments hoisted
    # in by the normalization above) — NOT payload.metadata,
    # which lacks them. Without this fix, ywatanabe at msg#6722
    # ("レンダリングされてないしね") saw agent-uploaded images
    # vanish from the live feed because the WS broadcast carried
    # an empty attachments list, even though the DB row had
    # them and a page reload would have shown them.
    # Spec v3 §3.3 — DM channels are identified by the reserved
    # ``dm:`` name prefix (guarded at Channel.clean()) and must
    # NOT hit the workspace_<id> fanout group, because dashboards
    # join that group without per-channel filtering.
    is_dm = ch_name.startswith("dm:")
    kind = "dm" if is_dm else "group"

    group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
    await consumer.channel_layer.group_send(
        group,
        {
            "type": "chat.message",
            "id": msg["id"] if msg else None,
            "sender": consumer.agent_name,
            "sender_type": "agent",
            "channel": ch_name,
            "kind": kind,
            "text": text,
            "ts": msg["ts"] if msg else None,
            "metadata": metadata,
        },
    )

    # Also broadcast to workspace group (for dashboard observers).
    # Skip this entirely for DMs — dashboards reach DM participants
    # through the channel_<ws>_<dm-name> group only.
    if not is_dm:
        await consumer.channel_layer.group_send(
            consumer.workspace_group,
            {
                "type": "chat.message",
                "id": msg["id"] if msg else None,
                "sender": consumer.agent_name,
                "sender_type": "agent",
                "channel": ch_name,
                "kind": kind,
                "text": text,
                "ts": msg["ts"] if msg else None,
                "metadata": metadata,
            },
        )

    # Web Push fan-out (todo#263). Best-effort, in a daemon
    # thread so the WS path never blocks on network I/O.
    try:
        from hub.push import send_push_to_subscribers_async

        send_push_to_subscribers_async(
            workspace_id=consumer.workspace_id,
            channel=ch_name,
            sender=consumer.agent_name,
            content=text,
            message_id=msg["id"] if msg else None,
        )
    except Exception:
        log.exception("push fan-out failed (agent path)")

    # Cross-channel @mention push (msg#15767). Best-effort; failures
    # must never break the parent write. The helper no-ops on DM
    # channels and on messages without mention tokens.
    try:
        from hub.mentions import expand_mentions_and_notify

        await _sta(expand_mentions_and_notify)(
            workspace_id=consumer.workspace_id,
            source_channel=ch_name,
            source_msg_id=msg["id"] if msg else None,
            sender_username=f"agent-{consumer.agent_name}",
            text=text,
        )
    except Exception:
        log.exception("mention push fan-out failed (agent path)")
