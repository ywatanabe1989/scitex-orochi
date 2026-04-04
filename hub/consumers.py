"""WebSocket consumers for agent and dashboard connections."""

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from hub.models import Channel, Message, Workspace, WorkspaceToken

log = logging.getLogger("orochi.consumers")


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

    async def disconnect(self, code):
        if hasattr(self, "workspace_group"):
            await self.channel_layer.group_discard(
                self.workspace_group, self.channel_name
            )
            log.info("Agent %s disconnected", getattr(self, "agent_name", "?"))

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "register":
            # Agent registration — subscribe to specific channels
            payload = content.get("payload", {})
            channels = content.get("channels") or payload.get("channels", [])
            for ch_name in channels:
                group = f"channel_{self.workspace_id}_{ch_name}"
                await self.channel_layer.group_add(group, self.channel_name)
            await self.send_json({"type": "registered", "channels": channels})

        elif msg_type == "message":
            payload = content.get("payload", {})
            ch_name = payload.get("channel", "#general")

            # Persist message
            msg = await self._save_message(
                channel_name=ch_name,
                sender=self.agent_name,
                content_text=payload.get("text", ""),
                metadata=payload.get("metadata", {}),
            )

            # Broadcast to channel group
            group = f"channel_{self.workspace_id}_{ch_name}"
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "sender": self.agent_name,
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
                "channel": event["channel"],
                "text": event["text"],
                "ts": event.get("ts"),
                "metadata": event.get("metadata", {}),
            }
        )

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

        workspace_slug = self.scope["url_route"]["kwargs"]["workspace_slug"]
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

            msg = await self._save_message(
                channel_name=ch_name,
                sender=self.user.username,
                content_text=payload.get("text", ""),
            )

            group = f"channel_{self.workspace_id}_{ch_name}"
            await self.channel_layer.group_send(
                group,
                {
                    "type": "chat.message",
                    "sender": self.user.username,
                    "channel": ch_name,
                    "text": payload.get("text", ""),
                    "ts": msg["ts"] if msg else None,
                },
            )

            await self.channel_layer.group_send(
                self.workspace_group,
                {
                    "type": "chat.message",
                    "sender": self.user.username,
                    "channel": ch_name,
                    "text": payload.get("text", ""),
                    "ts": msg["ts"] if msg else None,
                },
            )

    async def chat_message(self, event):
        """Forward channel-layer message to dashboard WebSocket."""
        await self.send_json(
            {
                "type": "message",
                "sender": event["sender"],
                "channel": event["channel"],
                "text": event["text"],
                "ts": event.get("ts"),
                "metadata": event.get("metadata", {}),
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
    def _save_message(self, channel_name, sender, content_text):
        try:
            workspace = Workspace.objects.get(id=self.workspace_id)
            channel, _ = Channel.objects.get_or_create(
                workspace=workspace, name=channel_name
            )
            msg = Message.objects.create(
                workspace=workspace,
                channel=channel,
                sender=sender,
                content=content_text,
            )
            return {"id": msg.id, "ts": msg.ts.isoformat()}
        except Exception:
            log.exception("Failed to save message")
            return None
