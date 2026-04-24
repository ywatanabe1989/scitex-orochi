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
        """Non-admin members cannot subscribe HUMAN users to channels.

        Subscribing agent-* targets is allowed for any workspace member
        (drag-agent-to-channel UX, see commit d47397b); cross-human
        subscriptions still require admin/staff.
        """
        # Another human in the workspace.
        other_human = User.objects.create_user(username="human-target", password="x")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=other_human, role="member"
        )
        self.client.force_login(self.plain)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps({"channel": "#nope", "username": "human-target"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_can_subscribe_agent(self):
        """Non-admin members CAN subscribe agent-* targets.

        Codifies the drag-agent-to-channel relaxation (commit d47397b)
        so it doesn't silently regress.
        """
        self.client.force_login(self.plain)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps({"channel": "#drag-target", "username": "agent-worker-x"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

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

    def test_post_accepts_can_read_can_write_bits(self):
        """REST subscribe accepts ``can_read`` / ``can_write`` bits
        (lead msg#16884). Body shape takes precedence over the legacy
        ``permission`` enum when bits are present."""
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps(
                {
                    "channel": "#digest",
                    "username": "agent-worker-x",
                    "can_read": False,
                    "can_write": True,
                }
            ),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["can_read"])
        self.assertTrue(body["can_write"])
        self.assertEqual(body["permission"], "write-only")
        # DB reflects the bits.
        ch = self.Channel.objects.get(workspace=self.ws, name="#digest")
        row = self.ChannelMembership.objects.get(
            user=self.agent_user, channel=ch
        )
        self.assertFalse(row.can_read)
        self.assertTrue(row.can_write)

    def test_patch_flips_bits_in_place(self):
        """PATCH updates existing row bits (round-trip)."""
        self.client.force_login(self.admin)
        ch = self.Channel.objects.create(workspace=self.ws, name="#toggle")
        self.ChannelMembership.objects.create(
            user=self.agent_user, channel=ch, can_read=True, can_write=True
        )
        resp = self.client.patch(
            "/api/channel-members/",
            data=json.dumps(
                {
                    "channel": "#toggle",
                    "username": "agent-worker-x",
                    "can_read": True,
                    "can_write": False,
                }
            ),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["can_read"])
        self.assertFalse(body["can_write"])
        self.assertEqual(body["permission"], "read-only")
        row = self.ChannelMembership.objects.get(
            user=self.agent_user, channel=ch
        )
        self.assertEqual(row.permission, "read-only")

    def test_legacy_permission_enum_still_accepted(self):
        """Callers that still pass ``permission`` (no bits) keep working
        — bridge maps the enum to the right bit pair."""
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps(
                {
                    "channel": "#legacy-body",
                    "username": "agent-worker-x",
                    "permission": "write-only",
                }
            ),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["can_read"])
        self.assertTrue(body["can_write"])

    def test_get_includes_bits_in_member_rows(self):
        """GET /api/channel-members/?channel=… exposes bits alongside
        the deprecated ``permission`` enum."""
        self.client.force_login(self.admin)
        ch = self.Channel.objects.create(workspace=self.ws, name="#get-bits")
        self.ChannelMembership.objects.create(
            user=self.agent_user, channel=ch, can_read=False, can_write=True
        )
        resp = self.client.get(
            "/api/channel-members/?channel=%23get-bits",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        match = next(
            (r for r in rows if r["username"] == "agent-worker-x"), None
        )
        self.assertIsNotNone(match, "agent row missing in response")
        self.assertFalse(match["can_read"])
        self.assertTrue(match["can_write"])
        self.assertEqual(match["permission"], "write-only")

    def test_post_subscribe_abolished_agent_channel_returns_403(self):
        """``#agent`` was abolished 2026-04-21 (lead directive, PR #293
        follow-up). POST/PATCH must return 403 so the client gets a real
        signal — a silent 200 would let the bad client think it's
        subscribed and retry endlessly.
        """
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channel-members/",
            data=json.dumps(
                {"channel": "#agent", "username": "agent-worker-x"}
            ),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get("error"), "channel abolished")
        self.assertFalse(
            self.Channel.objects.filter(workspace=self.ws, name="#agent").exists()
        )
        self.assertFalse(
            self.ChannelMembership.objects.filter(user=self.agent_user).exists()
        )
