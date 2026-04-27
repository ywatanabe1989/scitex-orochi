"""WebSocket consumer for the dashboard — Django-session authenticated.

Split out of the original 1556-line ``hub/consumers.py`` (see
``hub/consumers/__init__.py`` for the package overview). Public name
``DashboardConsumer`` is re-exported from ``hub.consumers``.
"""

from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from hub.models import Workspace, WorkspaceToken

from ._groups import _sanitize_group, log
from ._helpers import (
    _is_dm_participant_by_username,
    _load_dm_channel_names,
    _resolve_user_member_id,
    _resolve_workspace_token,
)
from ._persistence import save_message_sync


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
            # Fallback: token-based auth (same as AgentConsumer).
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
            self.user = await self._get_token_user(token_str)
            log.info(
                "Dashboard WS authenticated via token for workspace %s",
                self.workspace_name,
            )

        # Join workspace group to receive all messages
        self.workspace_group = f"workspace_{self.workspace_id}"
        await self.channel_layer.group_add(self.workspace_group, self.channel_name)

        # Spec v3 §3.1 — auto-subscribe to every DM channel this user is a
        # participant of. Symmetric with :class:`AgentConsumer`. Without
        # this, DMs broadcast to ``channel_<ws>_<dm-name>`` (and skipped
        # on the workspace group per spec §3.3) never reach the dashboard
        # WS, so users never see their own DMs animate or arrive —
        # todo 2026-04-19 "DM not working: functionally, visually".
        self.workspace_member_id = await _resolve_user_member_id(
            user_id=getattr(self.user, "id", None),
            workspace_id=self.workspace_id,
        )
        self._dm_channel_names = await _load_dm_channel_names(
            self.workspace_id, self.workspace_member_id
        )
        for _ch_name in self._dm_channel_names:
            _grp = _sanitize_group(f"channel_{self.workspace_id}_{_ch_name}")
            await self.channel_layer.group_add(_grp, self.channel_name)
        log.info(
            "Dashboard %s auto-subscribed to %d DM channels (member_id=%s)",
            getattr(self.user, "username", "token-user"),
            len(self._dm_channel_names),
            self.workspace_member_id,
        )

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
        # Also discard every DM channel group this dashboard joined so
        # the channel layer's membership doesn't leak references to a
        # dead consumer (symmetric with AgentConsumer).
        for _dm in getattr(self, "_dm_channel_names", []) or []:
            _grp = _sanitize_group(f"channel_{self.workspace_id}_{_dm}")
            try:
                await self.channel_layer.group_discard(_grp, self.channel_name)
            except Exception:
                pass

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")

        if msg_type == "message":
            from ._dashboard_message import handle_dashboard_message

            await handle_dashboard_message(self, content)

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

    async def dm_subscribe(self, event):
        """Handle ``dm.subscribe`` hint from ``_ensure_dm_channel``.

        When a DM channel is lazily created (e.g. agent→human first
        send while the human's dashboard is already open), the creator
        broadcasts this event on the workspace group. Every connected
        dashboard checks whether the current user is a participant; if
        so, self-joins the ``channel_<ws>_<dm>`` group so subsequent
        ``chat.message`` events reach this WS. Without this, the first
        DM from an agent to an already-logged-in user would not arrive
        until the user reconnected (page reload).
        """
        ch_name = event.get("channel", "")
        participants = event.get("participant_usernames", []) or []
        username = getattr(getattr(self, "user", None), "username", None)
        if not ch_name or not username:
            return
        if username in (None, "", "dashboard"):
            return
        if username not in participants:
            return
        grp = _sanitize_group(f"channel_{self.workspace_id}_{ch_name}")
        await self.channel_layer.group_add(grp, self.channel_name)
        if not hasattr(self, "_dm_channel_names"):
            self._dm_channel_names = []
        if ch_name not in self._dm_channel_names:
            self._dm_channel_names.append(ch_name)
        log.info(
            "Dashboard %s auto-joined new DM %s via dm.subscribe hint",
            username,
            ch_name,
        )

    # --- channel-layer events forwarded to the dashboard WebSocket -------

    async def agent_presence(self, event):
        await self.send_json(
            {
                "type": "agent_presence",
                "agent": event["agent"],
                "status": event["status"],
            }
        )

    async def agent_info(self, event):
        await self.send_json(
            {
                "type": "agent_info",
                "agent": event["agent"],
                "info": event.get("info", {}),
                "orochi_metrics": event.get("orochi_metrics", {}),
            }
        )

    async def agent_pong(self, event):
        """Forward hub→agent pong RTT to dashboard WebSocket client (todo#46)."""
        await self.send_json(
            {
                "type": "agent_pong",
                "agent": event["agent"],
                "rtt_ms": event.get("rtt_ms"),
                "ts": event.get("ts"),
            }
        )

    async def reaction_update(self, event):
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

    async def channel_description(self, event):
        await self.send_json(
            {
                "type": "channel_description",
                "channel": event.get("channel", ""),
                "description": event.get("description", ""),
            }
        )

    async def channel_identity(self, event):
        """Forward channel identity updates (description + icon + color)."""
        await self.send_json(
            {
                "type": "channel_identity",
                "channel": event.get("channel", ""),
                "description": event.get("description", ""),
                "icon_emoji": event.get("icon_emoji", ""),
                "icon_image": event.get("icon_image", ""),
                "icon_text": event.get("icon_text", ""),
                "color": event.get("color", ""),
            }
        )

    async def system_message(self, event):
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

    # --- DB-backed helpers ----------------------------------------------

    @database_sync_to_async
    def _get_token_user(self, token_str):
        """Return the first superuser or workspace admin as the acting user
        for token-authenticated dashboard sessions.  Falls back to a simple
        namespace object so send attribution still works."""
        try:
            wt = WorkspaceToken.objects.select_related("workspace").get(token=token_str)
            from hub.models import WorkspaceMember

            member = (
                WorkspaceMember.objects.filter(workspace=wt.workspace, role="admin")
                .select_related("user")
                .first()
            )
            if member:
                return member.user
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
        if user.is_superuser:
            return True
        from hub.models import WorkspaceMember

        return WorkspaceMember.objects.filter(
            user_id=user_id, workspace_id=workspace_id
        ).exists()

    @database_sync_to_async
    def _save_message(self, channel_name, sender, content_text, metadata=None):
        return save_message_sync(
            workspace_id=self.workspace_id,
            channel_name=channel_name,
            sender=sender,
            sender_type="human",
            content_text=content_text,
            metadata=metadata,
        )
