"""Channel-layer group-name helpers, fleet-channel allowlist, and the
hub→agent ping loop used by :class:`hub.consumers.AgentConsumer`.

Pulled out of the original 1556-line ``hub/consumers.py`` so the
consumer modules stay focused on WS lifecycle. Public names below are
re-exported by ``hub/consumers/__init__.py``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

# Interval between hub→agent JSON pings. Agents echo back
# {"type":"pong","payload":{"ts":<sent_ts>}} so the hub can compute
# round-trip time and expose hub-side liveness on the Agents tab's PN
# lamp (todo#46). Kept below the 30s heartbeat-stale threshold so a
# drop is noticed by both ends before the registry marks offline.
PING_INTERVAL_SECONDS = 25
# Upper bound on a healthy RTT; above this the PN lamp degrades to yellow.
RTT_WARN_MS = 500

log = logging.getLogger("orochi.consumers")


async def _hub_ping_loop(consumer) -> None:
    """Send periodic hub→agent JSON pings so hub-side liveness is tracked.

    Runs for the lifetime of the WebSocket connection. Cancelled from
    ``AgentConsumer.disconnect``. Exceptions other than ``CancelledError``
    are logged and swallowed — a ping loop crash must not tear down the
    whole consumer.
    """
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL_SECONDS)
            try:
                await consumer.send_json({"type": "ping", "ts": time.time()})
            except Exception:  # noqa: BLE001
                log.exception("ping send failed for %s", consumer.agent_name)
                return
    except asyncio.CancelledError:
        raise


def _sanitize_group(name: str) -> str:
    """Sanitize a channel/group name for Django Channels.

    Channels requires names matching ^[a-zA-Z0-9._-]{1,99}$. The previous
    version only handled #, @, and space, which broke registration when
    channels included other characters (slashes, colons, unicode, etc.).
    """
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", name)
    sanitized = sanitized.strip("-_.") or "x"
    return sanitized[:99]


# todo#405: auto-status-reply (`[agent] status: online`) belongs in fleet
# channels only. User-facing channels are the ywatanabe ↔ fleet interface
# (fleet-communication-discipline.md rule #8). Any channel not in this
# allowlist — including #general, #ywatanabe, orochi_project channels like
# #neurovista / #paper-*, and DMs — must stay free of fleet heartbeat noise.
_FLEET_CHANNELS = frozenset(
    {
        "#agent",
        "#progress",
        "#audit",
        "#escalation",
        "#fleet",
        "#system",
    }
)


def _is_fleet_channel(ch_name: str) -> bool:
    """True if ch_name is a fleet-only coordination channel.

    Fleet channels may receive mention-reply status posts; user channels
    must not. Unknown channels default to user-facing (fail-closed) to
    preserve the user experience if someone adds a new channel without
    updating this allowlist.
    """
    if not ch_name:
        return False
    name = ch_name if ch_name.startswith("#") else f"#{ch_name}"
    return name in _FLEET_CHANNELS
