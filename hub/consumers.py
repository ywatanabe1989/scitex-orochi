"""WebSocket consumers for agent and dashboard connections."""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from hub.models import Channel, Message, Workspace, WorkspaceToken

log = logging.getLogger("orochi.consumers")


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

        result = await self._resolve_token(token_str)
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
                "machine": payload.get("machine", ""),
                "role": payload.get("role", ""),
                "model": payload.get("model", ""),
                "workdir": payload.get("workdir", ""),
                "icon": payload.get("icon", ""),
                "icon_emoji": payload.get("icon_emoji", ""),
                "icon_text": payload.get("icon_text", ""),
                "channels": channels,
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
            from hub.registry import set_current_task, mark_activity

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

        elif msg_type == "message":
            payload = content.get("payload", {})
            ch_name = payload.get("channel", "#general")

            # Update activity timestamp — this is a meaningful action,
            # distinct from a passive heartbeat.
            from hub.registry import mark_activity

            mark_activity(self.agent_name, action=payload.get("text", "")[:120])

            # Persist message
            msg = await self._save_message(
                channel_name=ch_name,
                sender=self.agent_name,
                content_text=payload.get("text", ""),
                metadata=payload.get("metadata", {}),
            )

            # Broadcast to channel group
            group = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "sender": self.agent_name,
                    "sender_type": "agent",
                    "channel": ch_name,
                    "text": payload.get("text", ""),
                    "ts": msg["ts"] if msg else None,
                    "metadata": payload.get("metadata", {}),
                },
            )

            # Also broadcast to workspace group (for dashboard observers)
            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "chat.message",
                    "sender": self.agent_name,
                    "sender_type": "agent",
                    "channel": ch_name,
                    "text": payload.get("text", ""),
                    "ts": msg["ts"] if msg else None,
                    "metadata": payload.get("metadata", {}),
                },
            )

    async def chat_message(self, event):
        """Handle chat.message from channel layer — forward to WebSocket client."""
        await self.send_json(
            {
                "type": "message",
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

    @database_sync_to_async
    def _resolve_token(self, token_str):
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
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

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

        # Join workspace group to receive all messages
        self.workspace_group = f"workspace_{self.workspace_id}"
        await self.channel_layer.group_add(self.workspace_group, self.channel_name)

        await self.accept()
        log.info(
            "Dashboard user %s connected to workspace %s", user.username, workspace_slug
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
            ch_name = payload.get("channel", "#general")
            # Support both "text" and "content" keys from frontend
            text = payload.get("content") or payload.get("text") or ""
            metadata = payload.get("metadata", {})

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
