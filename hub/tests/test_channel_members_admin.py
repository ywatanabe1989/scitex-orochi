"""Tests for the Orochi hub Django app."""

import json  # noqa: F401
from unittest.mock import MagicMock, patch  # noqa: F401

from django.contrib.auth.models import User  # noqa: F401
from django.core.exceptions import ValidationError  # noqa: F401
from django.db import IntegrityError, transaction  # noqa: F401
from django.test import Client, TestCase  # noqa: F401

from hub import push as hub_push  # noqa: F401
from hub.models import (  # noqa: F401
    Channel,
    ChannelMembership,
    DMParticipant,
    Message,
    PushSubscription,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
    normalize_channel_name,
)


class ChannelMembersAdminApiTest(TestCase):
    """Phase 3 admin API — POST subscribe, DELETE unsubscribe, PATCH perm."""

    def setUp(self):
        from hub.models import Channel, ChannelMembership

        self.ChannelMembership = ChannelMembership
        self.Channel = Channel
        self.ws = Workspace.objects.create(name="admin-api-ws")
        # Route to urls_workspace via subdomain host header (middleware
        # matches <slug>.lvh.me against OROCHI_BASE_DOMAIN=lvh.me:8000).
        self.host = f"{self.ws.name}.lvh.me"
        self.admin = User.objects.create_user(
            username="admin", password="x", is_staff=True, is_superuser=True
        )
        self.plain = User.objects.create_user(username="plain", password="x")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.admin, role="admin")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.plain, role="member"
        )
        self.agent_user = User.objects.create_user(
            username="agent-worker-x", password=""
        )
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.agent_user, role="member"
        )

    def test_post_subscribes_agent_and_creates_channel(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps({"channel": "#phase3", "username": "agent-worker-x"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["created"])
        ch = self.Channel.objects.get(workspace=self.ws, name="#phase3")
        self.assertTrue(
            self.ChannelMembership.objects.filter(
                user=self.agent_user, channel=ch
            ).exists()
        )

    def test_post_subscribe_is_idempotent(self):
        self.client.force_login(self.admin)
        body = {"channel": "#idem", "username": "agent-worker-x"}
        r1 = self.client.post(
            "/api/channel-members/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        r2 = self.client.post(
            "/api/channel-members/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r1.json()["created"])
        self.assertFalse(r2.json()["created"])
        self.assertEqual(
            self.ChannelMembership.objects.filter(user=self.agent_user).count(), 1
        )

    def test_delete_unsubscribes_agent(self):
        self.client.force_login(self.admin)
        ch = self.Channel.objects.create(workspace=self.ws, name="#remove-me")
        self.ChannelMembership.objects.create(user=self.agent_user, channel=ch)
        resp = self.client.delete(
            "/api/channel-members/",
            data=json.dumps({"channel": "#remove-me", "username": "agent-worker-x"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["deleted"], 1)
        self.assertFalse(
            self.ChannelMembership.objects.filter(
                user=self.agent_user, channel=ch
            ).exists()
        )

    def test_non_admin_rejected(self):
        self.client.force_login(self.plain)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps({"channel": "#nope", "username": "agent-worker-x"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_missing_channel_is_idempotent(self):
        self.client.force_login(self.admin)
        resp = self.client.delete(
            "/api/channel-members/",
            data=json.dumps(
                {
                    "channel": "#never-existed",
                    "username": "agent-worker-x",
                }
            ),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["deleted"], 0)
