"""WebSocket consumer for AI agents — workspace-token authenticated.

Split out of the original 1556-line ``hub/consumers.py`` (see
``hub/consumers/__init__.py`` for the package overview). Public name
``AgentConsumer`` is re-exported from ``hub.consumers`` so existing
``from hub.consumers import AgentConsumer`` imports keep working.

Per-frame logic lives in sibling modules to keep this file under the
512-line cap:

  - ``_agent_handlers`` -- register / subscribe / pong / heartbeat /
    task_update / subagents_update dispatch
  - ``_agent_message``  -- the ``message`` frame handler (ACL,
    persistence, fan-out)
"""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from ._agent_handlers import (
    handle_echo_pong,
    handle_heartbeat,
    handle_pong,
    handle_register,
    handle_subagents_update,
    handle_subscription,
    handle_task_update,
)
from ._echo import _hub_echo_loop
from ._groups import _hub_ping_loop, _sanitize_group, log
from ._helpers import (
    _ensure_agent_member,
    _is_dm_participant_by_member,
    _load_dm_channel_names,
    _resolve_workspace_token,
)
from ._persistence import save_message_sync


class AgentConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for AI agents — authenticates with workspace token."""

    async def connect(self):
        qs = parse_qs(self.scope["query_string"].decode())
        token_str = qs.get("token", [None])[0]

        result = await _resolve_workspace_token(token_str)
        if result is None:
            await self.close(code=4001)
            return

        self.workspace_id = result["workspace_id"]
        self.workspace_name = result["workspace_name"]
        self.agent_name = qs.get("agent", ["anonymous"])[0]

        # Spec v3 §2.3 — idempotently ensure a WorkspaceMember row exists
        # for this agent so DMParticipant FKs have a stable target.
        self.workspace_member = await _ensure_agent_member(
            workspace_id=self.workspace_id,
            agent_name=self.agent_name,
        )
        self.workspace_member_id = (
            self.workspace_member.id if self.workspace_member else None
        )

        # Join workspace group for broadcasts
        self.workspace_group = f"workspace_{self.workspace_id}"
        await self.channel_layer.group_add(self.workspace_group, self.channel_name)

        # Spec v3 §3.1 — auto-subscribe to all DM channels the agent is
        # a participant of. The canonical DM channel name is stored on
        # ``agent_meta["channels"]`` (populated/extended at register time)
        # so the chat_message filter below forwards DM events correctly.
        self._dm_channel_names = await _load_dm_channel_names(
            self.workspace_id, self.workspace_member_id
        )
        for ch_name in self._dm_channel_names:
            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()

        # scitex-orochi#144 fix path 4: track this WebSocket as one of N
        # active connections under self.agent_name, so the registry can
        # surface concurrent-instance situations without altering identity.
        from hub.registry import register_connection

        active_sessions = register_connection(self.agent_name, self.channel_name)

        log.info(
            "Agent %s connected to workspace %s (active_sessions=%d)",
            self.agent_name,
            self.workspace_name,
            active_sessions,
        )
        if active_sessions > 1:
            log.warning(
                "Concurrent-instance hazard: %s now has %d active sessions "
                "(scitex-orochi#144). Dispatch to @%s may race; coordinators "
                "should prefer DM-routing.",
                self.agent_name,
                active_sessions,
                self.agent_name,
            )

        # Broadcast presence to dashboard observers, including the new
        # active_sessions field so the Agents tab can surface a warning
        # icon when sessions > 1.
        await self.channel_layer.group_send(
            self.workspace_group,
            {
                "type": "agent.presence",
                "agent": self.agent_name,
                "status": "connected",
                "active_sessions": active_sessions,
            },
        )

        # todo#46 — start hub→agent JSON ping loop so dashboard can show
        # live RTT and flag hub-side drops without waiting for the 30s
        # heartbeat-stale timeout.
        self._ping_task = asyncio.create_task(_hub_ping_loop(self))
        # #259 — start hub→agent echo round-trip loop. Independent task
        # so a transport hiccup in one loop can't starve the other.
        # Cancelled in disconnect() alongside _ping_task.
        self._echo_task = asyncio.create_task(_hub_echo_loop(self))

    async def disconnect(self, code):
        # Stop the ping task first so we don't race with the WS close.
        ping_task = getattr(self, "_ping_task", None)
        if ping_task is not None:
            ping_task.cancel()
        echo_task = getattr(self, "_echo_task", None)
        if echo_task is not None:
            echo_task.cancel()
        if hasattr(self, "workspace_group"):
            # scitex-orochi#144 fix path 4: drop only THIS connection from
            # the per-agent set, not the whole agent record. The agent only
            # transitions to offline when its last sibling connection drops.
            from hub.registry import unregister_connection

            agent_name = getattr(self, "agent_name", "?")
            remaining = unregister_connection(agent_name, self.channel_name)
            if remaining > 0:
                log.info(
                    "Agent %s disconnected one session; %d sibling "
                    "session(s) still active (scitex-orochi#144).",
                    agent_name,
                    remaining,
                )

            # Broadcast departure before leaving group, including remaining
            # session count so the dashboard can update the warning state.
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "agent.presence",
                    "agent": agent_name,
                    "status": "disconnected" if remaining == 0 else "connected",
                    "active_sessions": remaining,
                },
            )

            await self.channel_layer.group_discard(
                self.workspace_group, self.channel_name
            )
            log.info("Agent %s disconnected", agent_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "register":
            await handle_register(self, content)
        elif msg_type in ("subscribe", "unsubscribe"):
            await handle_subscription(
                self, content, subscribe=(msg_type == "subscribe")
            )
        elif msg_type == "pong":
            await handle_pong(self, content)
        elif msg_type == "echo_pong":
            await handle_echo_pong(self, content)
        elif msg_type == "heartbeat":
            await handle_heartbeat(self, content)
        elif msg_type == "task_update":
            await handle_task_update(self, content)
        elif msg_type == "subagents_update":
            await handle_subagents_update(self, content)
        elif msg_type == "message":
            from ._agent_message import handle_agent_message

            await handle_agent_message(self, content)

    async def chat_message(self, event):
        """Handle chat.message from channel layer — forward to WebSocket client.

        Spec v3 §3.2/§3.3 — DM events are forwarded only if this
        connection's principal (``WorkspaceMember``) is a participant of
        the DM channel. Group events keep the 90158bc agent_meta filter.
        """
        ch_name = event.get("channel", "")
        is_dm = event.get("kind") == "dm" or ch_name.startswith("dm:")

        if is_dm:
            allowed = await _is_dm_participant_by_member(
                channel_name=ch_name,
                workspace_id=self.workspace_id,
                member_id=getattr(self, "workspace_member_id", None),
            )
            if not allowed:
                return
        else:
            # Group channels: subscription filter. Subscription is strictly
            # opt-in: no membership → no group receipt. Per-DM delivery is
            # still governed by the DM-participant check above.
            agent_channels = getattr(self, "agent_meta", {}).get("channels", [])
            if ch_name not in agent_channels:
                return
        await self.send_json(
            {
                "type": "message",
                "id": event.get("id"),
                "sender": event["sender"],
                "sender_type": event.get("sender_type", "human"),
                "channel": event["channel"],
                "text": event["text"],
                "ts": event.get("ts"),
                "metadata": event.get("metadata", {}),
            }
        )

    # --- channel-layer events ignored on the agent socket ----------------

    async def agent_presence(self, event):
        pass

    async def agent_info(self, event):
        pass

    async def agent_pong(self, event):
        pass

    async def system_message(self, event):
        pass

    # --- channel-layer events forwarded to the agent WebSocket -----------

    async def reaction_update(self, event):
        """Forward reaction add/remove events to agent WebSocket.

        Agents need to know when a human reacts to one of their messages
        so reactions can serve as lightweight acknowledgements (e.g.
        thumbs-up to mean "received, no further action needed") without
        having to write a full reply.
        """
        await self.send_json(
            {
                "type": "reaction_update",
                "message_id": event["message_id"],
                "emoji": event["emoji"],
                "reactor": event["reactor"],
                "action": event["action"],
            }
        )

    async def message_edit(self, event):
        await self.send_json(
            {
                "type": "message_edit",
                "message_id": event["message_id"],
                "sender": event["sender"],
                "channel": event.get("channel", ""),
                "text": event["text"],
                "edited_at": event.get("edited_at"),
            }
        )

    async def message_delete(self, event):
        await self.send_json(
            {
                "type": "message_delete",
                "message_id": event["message_id"],
                "sender": event["sender"],
                "channel": event.get("channel", ""),
            }
        )

    async def thread_reply(self, event):
        """Forward thread reply events to agent WebSocket.

        The MCP sidecar rewrites thread_reply into a message with parent
        context, so agents can recognise and respond to threaded replies.
        """
        await self.send_json(
            {
                "type": "thread_reply",
                "parent_id": event["parent_id"],
                "reply_id": event["reply_id"],
                "sender": event["sender"],
                "sender_type": event.get("sender_type", "human"),
                "channel": event.get("channel", ""),
                "text": event.get("text", ""),
                "ts": event.get("ts"),
                "metadata": event.get("metadata", {}),
            }
        )

    @database_sync_to_async
    def _save_message(self, channel_name, sender, content_text, metadata=None):
        return save_message_sync(
            workspace_id=self.workspace_id,
            channel_name=channel_name,
            sender=sender,
            sender_type="agent",
            content_text=content_text,
            metadata=metadata,
        )
