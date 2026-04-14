"""WebSocket consumers for agent and dashboard connections."""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from hub.models import (
    Channel,
    DMParticipant,
    Message,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    normalize_channel_name,
)
from hub.channel_acl import check_write_allowed

log = logging.getLogger("orochi.consumers")


@database_sync_to_async
def _ensure_agent_member(workspace_id, agent_name):
    """Idempotently ensure a ``WorkspaceMember`` row exists for an agent.

    Mirrors the synthetic-user pattern from ``hub/views/auth.py`` —
    ``agent-<name>`` Django ``User`` + ``WorkspaceMember`` row. Required
    by spec v3 §2.3 so DMParticipant FKs have a stable target.

    Returns the ``WorkspaceMember`` instance (or ``None`` on failure).
    """
    import re

    from django.contrib.auth.models import User

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9_.\-]", "-", agent_name or "anonymous-agent")
    username = f"agent-{safe_name}"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@agents.orochi.local",
            "is_active": True,
            "is_staff": False,
        },
    )
    member, _ = WorkspaceMember.objects.get_or_create(
        user=user,
        workspace=workspace,
        defaults={"role": "member"},
    )
    return member


@database_sync_to_async
def _load_dm_channel_names(workspace_id, member_id):
    """Return canonical ``dm:`` channel names the given member participates in."""
    if member_id is None:
        return []
    return list(
        DMParticipant.objects.filter(
            member_id=member_id,
            channel__workspace_id=workspace_id,
            channel__kind=Channel.KIND_DM,
        ).values_list("channel__name", flat=True)
    )


@database_sync_to_async
def _is_dm_participant_by_member(channel_name, workspace_id, member_id):
    """Check whether ``member_id`` is a participant of the given DM channel."""
    if member_id is None:
        return False
    return DMParticipant.objects.filter(
        channel__workspace_id=workspace_id,
        channel__name=channel_name,
        channel__kind=Channel.KIND_DM,
        member_id=member_id,
    ).exists()


@database_sync_to_async
def _is_dm_participant_by_username(channel_name, workspace_id, username):
    """Check DM participation for a (possibly unauthenticated) dashboard user.

    ``username=None`` always returns ``False`` — unauthenticated dashboards
    can never read DMs.
    """
    if not username:
        return False
    return DMParticipant.objects.filter(
        channel__workspace_id=workspace_id,
        channel__name=channel_name,
        channel__kind=Channel.KIND_DM,
        member__user__username=username,
    ).exists()


@database_sync_to_async
def _resolve_workspace_token(token_str):
    """Resolve a workspace token string to workspace info dict, or None."""
    if not token_str:
        return None
    try:
        wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
        return {
            "workspace_id": wt.workspace_id,
            "workspace_name": wt.workspace.name,
        }
    except WorkspaceToken.DoesNotExist:
        return None


def _sanitize_group(name: str) -> str:
    """Sanitize a channel/group name for Django Channels.

    Channels requires names matching ^[a-zA-Z0-9._-]{1,99}$. The previous
    version only handled #, @, and space, which broke registration when
    channels included other characters (slashes, colons, unicode, etc.).
    """
    import re

    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", name)
    sanitized = sanitized.strip("-_.") or "x"
    return sanitized[:99]


# todo#405: auto-status-reply (`[agent] status: online`) belongs in fleet
# channels only. User-facing channels are the ywatanabe ↔ fleet interface
# (fleet-communication-discipline.md rule #8). Any channel not in this
# allowlist — including #general, #ywatanabe, project channels like
# #neurovista / #paper-*, and DMs — must stay free of fleet heartbeat noise.
_FLEET_CHANNELS = frozenset({
    "#agent",
    "#progress",
    "#audit",
    "#escalation",
    "#fleet",
    "#system",
})


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
        log.info(
            "Agent %s connected to workspace %s",
            self.agent_name,
            self.workspace_name,
        )

        # Broadcast presence to dashboard observers
        await self.channel_layer.group_send(
            self.workspace_group,
            {
                "type": "agent.presence",
                "agent": self.agent_name,
                "status": "connected",
            },
        )

        # System messages (connect/disconnect/register) removed from chat feed
        # — too noisy during restarts. Sidebar presence updates are sufficient.

    async def disconnect(self, code):
        if hasattr(self, "workspace_group"):
            # Mark agent offline in registry
            from hub.registry import unregister_agent

            agent_name = getattr(self, "agent_name", "?")
            unregister_agent(agent_name)

            # Broadcast departure before leaving group
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "agent.presence",
                    "agent": agent_name,
                    "status": "disconnected",
                },
            )

            # Disconnect system message removed — too noisy in chat feed
            await self.channel_layer.group_discard(
                self.workspace_group, self.channel_name
            )
            log.info("Agent %s disconnected", agent_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "register":
            # Agent registration — subscribe to specific channels
            payload = content.get("payload", {})
            channels = list(content.get("channels") or payload.get("channels", []) or [])
            # Spec v3 §3.1 — ensure DM channels auto-subscribed at connect
            # are also reflected in ``agent_meta["channels"]`` so the
            # 90158bc chat_message filter forwards DM events.
            for dm_name in getattr(self, "_dm_channel_names", []) or []:
                if dm_name not in channels:
                    channels.insert(0, dm_name)
            for ch_name in channels:
                group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
                await self.channel_layer.group_add(group, self.channel_name)

            # Store agent metadata for info display
            self.agent_meta = {
                "agent_id": payload.get("agent_id", self.agent_name),
                "project": payload.get("project", ""),
                "machine": payload.get("machine", ""),
                "role": payload.get("role", ""),
                "model": payload.get("model", ""),
                "workdir": payload.get("workdir", ""),
                "icon": payload.get("icon", ""),
                "icon_emoji": payload.get("icon_emoji", ""),
                "icon_text": payload.get("icon_text", ""),
                "color": payload.get("color", ""),
                "multiplexer": payload.get("multiplexer", ""),
                "channels": channels,
                "claude_md": payload.get("claude_md", ""),
            }

            # Persist in in-memory registry for REST API access
            from hub.registry import register_agent

            register_agent(self.agent_name, self.workspace_id, self.agent_meta)

            # Broadcast agent info to dashboard observers
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "agent.info",
                    "agent": self.agent_name,
                    "info": self.agent_meta,
                },
            )

            await self.send_json({"type": "registered", "channels": channels})

            # Register system message removed — too noisy in chat feed

        elif msg_type == "heartbeat":
            # Store resource metrics from agent heartbeat
            payload = content.get("payload", {})
            self.agent_metrics = {
                "cpu_count": payload.get("cpu_count"),
                "load_avg_1m": payload.get("load_avg_1m"),
                "mem_used_percent": payload.get("mem_used_percent"),
                "mem_total_mb": payload.get("mem_total_mb"),
                "disk_used_percent": payload.get("disk_used_percent"),
            }

            # Update in-memory registry
            from hub.registry import (
                set_current_task,
                set_subagent_count,
                update_heartbeat,
            )

            update_heartbeat(self.agent_name, self.agent_metrics)

            # Allow lightweight clients to piggyback narrative fields on
            # the heartbeat rather than sending separate task_update /
            # subagents_update frames.
            if "current_task" in payload:
                set_current_task(
                    self.agent_name, str(payload.get("current_task") or "")
                )
            if "subagent_count" in payload:
                try:
                    set_subagent_count(
                        self.agent_name, int(payload.get("subagent_count") or 0)
                    )
                except (TypeError, ValueError):
                    pass

            # Broadcast metrics update to dashboard observers
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "agent.info",
                    "agent": self.agent_name,
                    "info": getattr(self, "agent_meta", {}),
                    "metrics": self.agent_metrics,
                },
            )

        elif msg_type == "task_update":
            # Agent reports its current task — visible in the Activity tab.
            payload = content.get("payload", {})
            task = payload.get("task", "")
            from hub.registry import mark_activity, set_current_task

            set_current_task(self.agent_name, task)
            mark_activity(self.agent_name, action=task)
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "agent.info",
                    "agent": self.agent_name,
                    "info": getattr(self, "agent_meta", {}),
                    "metrics": getattr(self, "agent_metrics", {}),
                },
            )

        elif msg_type == "subagents_update":
            # Agent reports its current subagent tree.
            # payload = { "subagents": [ {name, task, status}, ... ] }
            payload = content.get("payload", {})
            from hub.registry import mark_activity, set_subagents

            set_subagents(self.agent_name, payload.get("subagents") or [])
            mark_activity(self.agent_name)
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "agent.info",
                    "agent": self.agent_name,
                    "info": getattr(self, "agent_meta", {}),
                    "metrics": getattr(self, "agent_metrics", {}),
                },
            )

        elif msg_type == "message":
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

            # Channel ACL enforcement — check before persisting or broadcasting.
            # check_write_allowed is a sync call (file-cached, sub-ms) so safe to
            # call directly in the async consumer.
            # check_write_allowed may touch the DB for DM channels, so
            # route through sync_to_async. For non-DM channels it's a
            # cached yaml lookup (sub-ms).
            from asgiref.sync import sync_to_async as _sta

            _allowed = await _sta(check_write_allowed)(
                self.agent_name, ch_name, self.workspace_id
            )
            if not _allowed:
                log.warning(
                    "[ACL] blocked write from %s to %s",
                    self.agent_name,
                    ch_name,
                )
                await self.send_json({
                    "type": "error",
                    "code": "acl_denied",
                    "message": f"You are not allowed to write to {ch_name}",
                })
                return

            # Attachments may arrive either nested in metadata (new clients)
            # or at the payload top-level (upload.js). Normalize into one
            # metadata dict so both persistence and broadcast carry them.
            metadata = dict(payload.get("metadata", {}) or {})
            if "attachments" in payload and "attachments" not in metadata:
                metadata["attachments"] = payload.get("attachments") or []

            # Update activity timestamp — this is a meaningful action,
            # distinct from a passive heartbeat.
            from hub.registry import mark_activity

            mark_activity(self.agent_name, action=text[:120])

            # Persist message
            msg = await self._save_message(
                channel_name=ch_name,
                sender=self.agent_name,
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

            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "id": msg["id"] if msg else None,
                    "sender": self.agent_name,
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
                await self.channel_layer.group_send(
                    self.workspace_group,
                    {
                        "type": "chat.message",
                        "id": msg["id"] if msg else None,
                        "sender": self.agent_name,
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
                    workspace_id=self.workspace_id,
                    channel=ch_name,
                    sender=self.agent_name,
                    content=text,
                    message_id=msg["id"] if msg else None,
                )
            except Exception:
                log.exception("push fan-out failed (agent path)")

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
            # Group channels: existing subscription filter.
            agent_channels = getattr(self, "agent_meta", {}).get("channels", [])
            if agent_channels and ch_name not in agent_channels:
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

    async def agent_presence(self, event):
        """Handle agent.presence from channel layer — ignore for agent sockets."""
        pass

    async def agent_info(self, event):
        """Handle agent.info from channel layer — ignore for agent sockets."""
        pass

    async def system_message(self, event):
        """Handle system.message from channel layer — ignore for agent sockets."""
        pass

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
        """Forward message edit events to agent WebSocket."""
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
        """Forward message delete events to agent WebSocket."""
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
        try:
            workspace = Workspace.objects.get(id=self.workspace_id)
            channel, _ = Channel.objects.get_or_create(
                workspace=workspace, name=normalize_channel_name(channel_name)
            )
            msg = Message.objects.create(
                workspace=workspace,
                channel=channel,
                sender=sender,
                sender_type="agent",
                content=content_text,
                metadata=metadata or {},
            )
            return {"id": msg.id, "ts": msg.ts.isoformat()}
        except Exception:
            log.exception("Failed to save message")
            return None


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for dashboard — authenticates with Django session."""

    async def connect(self):
        user = self.scope.get("user")
        authenticated_via_session = user and user.is_authenticated

        if authenticated_via_session:
            # Session auth succeeded -- resolve workspace from subdomain
            workspace_slug = self._get_subdomain_from_scope()
            if not workspace_slug:
                await self.close(code=4004)
                return
            workspace = await self._get_workspace(workspace_slug)
            if not workspace:
                await self.close(code=4004)
                return

            # Check membership
            has_access = await self._check_membership(user.id, workspace["id"])
            if not has_access:
                await self.close(code=4003)
                return

            self.workspace_id = workspace["id"]
            self.workspace_name = workspace["name"]
            self.user = user
        else:
            # Fallback: token-based auth (same as AgentConsumer)
            # Handles cases where session cookies are stripped (Cloudflare,
            # SECURE cookie mismatch, etc.)
            qs = parse_qs(self.scope["query_string"].decode())
            token_str = qs.get("token", [None])[0]
            result = await _resolve_workspace_token(token_str)
            if result is None:
                log.warning(
                    "Dashboard WS rejected: user=%s auth=%s token=%s",
                    user,
                    getattr(user, "is_authenticated", None),
                    "present" if token_str else "missing",
                )
                await self.close(code=4001)
                return

            self.workspace_id = result["workspace_id"]
            self.workspace_name = result["workspace_name"]
            # Create a lightweight user stand-in for send attribution
            self.user = await self._get_token_user(token_str)
            log.info(
                "Dashboard WS authenticated via token for workspace %s",
                self.workspace_name,
            )

        # Join workspace group to receive all messages
        self.workspace_group = f"workspace_{self.workspace_id}"
        await self.channel_layer.group_add(self.workspace_group, self.channel_name)

        await self.accept()
        log.info(
            "Dashboard user %s connected to workspace %s",
            getattr(self.user, "username", "token-user"),
            self.workspace_name,
        )

    def _get_subdomain_from_scope(self):
        """Extract workspace slug from Host header in WebSocket scope."""
        from django.conf import settings as django_settings

        headers = dict(self.scope.get("headers", []))
        host = headers.get(b"host", b"").decode().split(":")[0]
        base = django_settings.OROCHI_BASE_DOMAIN.split(":")[0]
        if host.endswith("." + base):
            subdomain = host[: -(len(base) + 1)]
            if "." not in subdomain:
                return subdomain
        return None

    async def disconnect(self, code):
        if hasattr(self, "workspace_group"):
            await self.channel_layer.group_discard(
                self.workspace_group, self.channel_name
            )

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "message":
            payload = content.get("payload", {})
            # Support channel/text inside payload (canonical) or at top level (legacy clients)
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

            msg = await self._save_message(
                channel_name=ch_name,
                sender=self.user.username,
                content_text=text,
                metadata=metadata,
            )

            is_dm = ch_name.startswith("dm:")
            kind = "dm" if is_dm else "group"

            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "id": msg["id"] if msg else None,
                    "sender": self.user.username,
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
                await self.channel_layer.group_send(
                    self.workspace_group,
                    {
                        "type": "chat.message",
                        "id": msg["id"] if msg else None,
                        "sender": self.user.username,
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
                    workspace_id=self.workspace_id,
                    channel=ch_name,
                    sender=self.user.username,
                    content=text,
                    message_id=msg["id"] if msg else None,
                )
            except Exception:
                log.exception("push fan-out failed (dashboard path)")

            # @mention auto-reply (issue #98): when a message contains @agentname,
            # hub immediately posts a brief system status for the mentioned agent
            # so the sender knows whether it's alive and what it's doing.
            #
            # todo#405: never auto-post `[agent] status: online / (no recent activity)`
            # into user-facing channels. User channels are the ywatanabe ↔ fleet
            # interface (per `fleet-communication-discipline.md` rule #8); status
            # replies belong in fleet channels only. `@all` from ywatanabe used to
            # explode into 12+ status replies flooding the feed.
            if (
                "@" in text
                and not is_dm
                and _is_fleet_channel(ch_name)
            ):
                await self._maybe_mention_reply(text, ch_name)

    async def _maybe_mention_reply(self, text: str, ch_name: str) -> None:
        """Post a brief system status reply when an @mention is detected (issue #98).

        Parses all @word tokens from the message. For each token that matches
        a known agent name in the registry, posts a system message with the
        agent's last recent_actions (up to 5 lines) and its online/offline status.
        """
        import re
        from hub.registry import get_agents

        mentioned = re.findall(r"@([\w\-\.]+)", text)
        if not mentioned:
            return

        all_agents = get_agents(self.workspace_id)
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
                activity = "\n".join(f"  {l}" for l in lines)
            else:
                activity = "  (no recent activity)"
            reply_text = (
                f"[{name}] status: {status}"
                + (f" | last seen: {last_seen}" if last_seen else "")
                + f"\nRecent activity:\n{activity}"
            )
            mention_msg = await self._save_message(
                channel_name=ch_name,
                sender="hub",
                content_text=reply_text,
                metadata={"source": "mention_reply", "agent": name},
            )
            # Only broadcast to the specific channel group (not workspace-wide).
            # Workspace-wide broadcast caused all agents to receive mention_reply
            # messages regardless of channel subscription, wasting tokens (#405).
            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_send(
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

    async def chat_message(self, event):
        """Forward channel-layer message to dashboard WebSocket.

        Spec v3 §3.3 — confidentiality filter for DM events. The
        dashboard joins ``workspace_<id>`` and will no longer receive
        DMs via that group (sender skips fanout), but it may still be
        bridged into ``channel_<ws>_<dm-name>`` groups. For defence in
        depth we re-check participation here based on the connected
        user's username. Unauthenticated / token-only dashboards
        (``self.user.username in {"", "dashboard", None}``) never see
        DMs — explicit opt-in via session is required.
        """
        ch_name = event.get("channel", "")
        is_dm = event.get("kind") == "dm" or ch_name.startswith("dm:")
        if is_dm:
            username = getattr(getattr(self, "user", None), "username", None)
            # Token-authenticated dashboards use a lightweight stand-in
            # (_TokenUser with username="dashboard") or an admin fallback;
            # they must not see DMs.
            if username in (None, "", "dashboard"):
                return
            allowed = await _is_dm_participant_by_username(
                channel_name=ch_name,
                workspace_id=self.workspace_id,
                username=username,
            )
            if not allowed:
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

    async def agent_presence(self, event):
        """Forward agent presence updates to dashboard WebSocket client."""
        await self.send_json(
            {
                "type": "agent_presence",
                "agent": event["agent"],
                "status": event["status"],
            }
        )

    async def agent_info(self, event):
        """Forward agent info/metrics updates to dashboard WebSocket client."""
        await self.send_json(
            {
                "type": "agent_info",
                "agent": event["agent"],
                "info": event.get("info", {}),
                "metrics": event.get("metrics", {}),
            }
        )

    async def reaction_update(self, event):
        """Forward reaction add/remove events to dashboard WebSocket client."""
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
        """Forward message edit events to dashboard WebSocket client."""
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
        """Forward message delete events to dashboard WebSocket client."""
        await self.send_json(
            {
                "type": "message_delete",
                "message_id": event["message_id"],
                "sender": event["sender"],
                "channel": event.get("channel", ""),
            }
        )

    async def channel_description(self, event):
        """Forward channel description updates to dashboard WebSocket client."""
        await self.send_json(
            {
                "type": "channel_description",
                "channel": event.get("channel", ""),
                "description": event.get("description", ""),
            }
        )

    async def system_message(self, event):
        """Forward system messages to dashboard WebSocket client."""
        import datetime

        await self.send_json(
            {
                "type": "system_message",
                "text": event.get("text", ""),
                "event": event.get("event", ""),
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        )

    async def thread_reply(self, event):
        """Forward thread reply events to dashboard WebSocket client."""
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
    def _get_token_user(self, token_str):
        """Return the first superuser or workspace admin as the acting user
        for token-authenticated dashboard sessions.  Falls back to a simple
        namespace object so send attribution still works."""
        try:
            wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
            # Try to find an admin member of this workspace
            from hub.models import WorkspaceMember

            member = (
                WorkspaceMember.objects.filter(workspace=wt.workspace, role="admin")
                .select_related("user")
                .first()
            )
            if member:
                return member.user
            # Fallback: any superuser
            from django.contrib.auth import get_user_model

            User = get_user_model()
            su = User.objects.filter(is_superuser=True).first()
            if su:
                return su
        except Exception:
            pass

        # Last resort: anonymous-like object with .username
        class _TokenUser:
            username = "dashboard"
            id = None
            is_authenticated = True

        return _TokenUser()

    @database_sync_to_async
    def _get_workspace(self, slug):
        try:
            ws = Workspace.objects.get(name=slug)
            return {"id": ws.id, "name": ws.name}
        except Workspace.DoesNotExist:
            return None

    @database_sync_to_async
    def _check_membership(self, user_id, workspace_id):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.get(id=user_id)
        # Superusers can access all workspaces
        if user.is_superuser:
            return True
        from hub.models import WorkspaceMember

        return WorkspaceMember.objects.filter(
            user_id=user_id, workspace_id=workspace_id
        ).exists()

    @database_sync_to_async
    def _save_message(self, channel_name, sender, content_text, metadata=None):
        try:
            workspace = Workspace.objects.get(id=self.workspace_id)
            channel, _ = Channel.objects.get_or_create(
                workspace=workspace, name=normalize_channel_name(channel_name)
            )
            msg = Message.objects.create(
                workspace=workspace,
                channel=channel,
                sender=sender,
                sender_type="human",
                content=content_text,
                metadata=metadata or {},
            )
            return {"id": msg.id, "ts": msg.ts.isoformat()}
        except Exception:
            log.exception("Failed to save message")
            return None
