"""Push notification message hook for Orochi server.

When registered as a message hook, sends web push notifications
to all subscribers for each new channel message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from scitex_orochi._push import (
    PushStore,
    get_vapid_keys_path,
    load_vapid_keys,
    send_push_to_all,
)

if TYPE_CHECKING:
    from scitex_orochi._models import Message

log = logging.getLogger("orochi.push_hook")


def create_push_hook(push_store: PushStore) -> Any:
    """Create a message hook that sends push notifications.

    Returns an async callable suitable for OrochiServer._message_hooks.
    VAPID keys are loaded once on first use and cached in memory.
    """
    _cached_keys: dict[str, Any] = {}

    async def push_message_hook(msg: Message) -> None:
        """Send push notification for a channel message."""
        if "keys" not in _cached_keys:
            loaded = load_vapid_keys(get_vapid_keys_path())
            if loaded is None:
                return  # VAPID keys not configured, skip silently
            _cached_keys["keys"] = loaded
        keys = _cached_keys["keys"]

        content = msg.content or ""
        if not content:
            return  # No content to notify about

        channel = msg.channel or "#general"
        sender = msg.sender or "unknown"

        # Truncate long messages for notification body
        body = content[:200] + ("..." if len(content) > 200 else "")

        payload = {
            "title": f"{sender} in {channel}",
            "body": body,
            "tag": f"orochi-{channel}",
            "url": "/",
        }

        vapid_claims: dict[str, str | int] = {"sub": "mailto:admin@orochi.local"}

        await send_push_to_all(
            push_store=push_store,
            payload=payload,
            vapid_private_key=keys["private_key"],
            vapid_claims=vapid_claims,
        )

    return push_message_hook
