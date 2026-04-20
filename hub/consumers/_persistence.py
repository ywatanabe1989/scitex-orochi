"""Shared message-persistence helper for both AgentConsumer and
DashboardConsumer.

Both consumers had their own ``_save_message`` ``@database_sync_to_async``
method that did exactly the same thing apart from ``sender_type``. The
shared sync function lives here; each consumer wraps it in
``database_sync_to_async`` at class-definition time so the two existing
``self._save_message(...)`` call sites stay drop-in compatible.
"""

from __future__ import annotations

from hub.models import (
    Channel,
    Message,
    MessageThread,
    Workspace,
    normalize_channel_name,
)

from ._groups import log


def save_message_sync(
    workspace_id: int,
    channel_name: str,
    sender: str,
    sender_type: str,
    content_text: str,
    metadata: dict | None = None,
):
    """Persist one message + optional thread association. Sync — wrap with
    ``database_sync_to_async`` at the call site.
    """
    try:
        workspace = Workspace.objects.get(id=workspace_id)
        norm_name = normalize_channel_name(channel_name)
        channel, _ = Channel.objects.get_or_create(
            workspace=workspace,
            name=norm_name,
            defaults={
                "kind": (
                    Channel.KIND_DM
                    if norm_name.startswith("dm:")
                    else Channel.KIND_GROUP
                )
            },
        )
        msg = Message.objects.create(
            workspace=workspace,
            channel=channel,
            sender=sender,
            sender_type=sender_type,
            content=content_text,
            metadata=metadata or {},
        )
        # Create thread association if reply_to is specified
        reply_to = (metadata or {}).get("reply_to")
        if reply_to:
            try:
                parent_msg = Message.objects.get(id=int(reply_to))
                MessageThread.objects.create(parent=parent_msg, reply=msg)
            except (Message.DoesNotExist, ValueError, TypeError):
                log.warning("reply_to=%s not found, skipping thread", reply_to)
        return {"id": msg.id, "ts": msg.ts.isoformat()}
    except Exception:
        log.exception("Failed to save message")
        return None
