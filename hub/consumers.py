"""WebSocket consumers for agent and dashboard connections."""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from hub.models import Channel, Message, Workspace, WorkspaceToken

log = logging.getLogger("orochi.consumers")


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

        # Join workspace group for broadcasts
        self.workspace_group = f"workspace_{self.workspace_id}"
        await self.channel_layer.group_add(self.workspace_group, self.channel_name)

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
            channels = content.get("channels") or payload.get("channels", [])
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
            from hub.registry import update_heartbeat

            update_heartbeat(self.agent_name, self.agent_metrics)

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
            text = (
                payload.get("content")
                or payload.get("text")
                or content.get("text")
                or content.get("content")
                or ""
            )

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

            # Broadcast to channel group
            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "id": msg["id"] if msg else None,
                    "sender": self.agent_name,
                    "sender_type": "agent",
                    "channel": ch_name,
                    "text": text,
                    "ts": msg["ts"] if msg else None,
                    "metadata": payload.get("metadata", {}),
                },
            )

            # Also broadcast to workspace group (for dashboard observers)
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "chat.message",
                    "id": msg["id"] if msg else None,
                    "sender": self.agent_name,
                    "sender_type": "agent",
                    "channel": ch_name,
                    "text": text,
                    "ts": msg["ts"] if msg else None,
                    "metadata": payload.get("metadata", {}),
                },
            )

    async def chat_message(self, event):
        """Handle chat.message from channel layer — forward to WebSocket client."""
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
        """Ignore reaction events on agent sockets."""
        pass

    async def thread_reply(self, event):
        """Ignore thread events on agent sockets."""
        pass

    @database_sync_to_async
    def _save_message(self, channel_name, sender, content_text, metadata=None):
        try:
            workspace = Workspace.objects.get(id=self.workspace_id)
            channel, _ = Channel.objects.get_or_create(
                workspace=workspace, name=channel_name
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

            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "id": msg["id"] if msg else None,
                    "sender": self.user.username,
                    "sender_type": "human",
                    "channel": ch_name,
                    "text": text,
                    "ts": msg["ts"] if msg else None,
                    "metadata": metadata,
                },
            )

            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "chat.message",
                    "id": msg["id"] if msg else None,
                    "sender": self.user.username,
                    "sender_type": "human",
                    "channel": ch_name,
                    "text": text,
                    "ts": msg["ts"] if msg else None,
                    "metadata": metadata,
                },
            )

    async def chat_message(self, event):
        """Forward channel-layer message to dashboard WebSocket."""
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
                workspace=workspace, name=channel_name
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
