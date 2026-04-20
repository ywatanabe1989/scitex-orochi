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


class DmRestApiTest(TestCase):
    """Coverage for /api/workspace/<slug>/dms/ and the /messages/ ACL fix."""

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="dm-ws")

        # Two human callers + one synthetic agent user, all members.
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="x")
        self.carol = User.objects.create_user(username="carol", password="x")
        self.agent_user = User.objects.create_user(
            username="agent-mamba-foo", password="x"
        )
        self.alice_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.alice
        )
        self.bob_m = WorkspaceMember.objects.create(workspace=self.ws, user=self.bob)
        self.carol_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.carol
        )
        self.agent_m = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.agent_user
        )

    def _login(self, user):
        self.client.force_login(user)

    # ---- POST /dms/ ----------------------------------------------------

    def test_post_dms_creates_canonical_channel(self):
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        # Canonical name is dm:<sorted principal keys>
        expected = "dm:" + "|".join(sorted(["human:alice", "human:bob"]))
        self.assertEqual(data["name"], expected)
        self.assertEqual(data["kind"], "dm")
        self.assertEqual(len(data["other_participants"]), 1)
        self.assertEqual(data["other_participants"][0]["identity_name"], "bob")

        ch = Channel.objects.get(workspace=self.ws, name=expected)
        self.assertEqual(ch.kind, "dm")
        self.assertEqual(ch.dm_participants.count(), 2)

    def test_post_dms_is_idempotent(self):
        self._login(self.alice)
        url = "/api/workspace/dm-ws/dms/"
        body = json.dumps({"recipient": "human:bob"})
        r1 = self.client.post(url, data=body, content_type="application/json")
        r2 = self.client.post(url, data=body, content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["name"], r2.json()["name"])
        self.assertEqual(
            Channel.objects.filter(
                workspace=self.ws, kind="dm", name=r1.json()["name"]
            ).count(),
            1,
        )
        self.assertEqual(
            DMParticipant.objects.filter(channel__name=r1.json()["name"]).count(), 2
        )

    def test_post_dms_rejects_non_member(self):
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:nobody"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_post_dms_routes_through_channel_clean(self):
        """The dm: prefix guard in Channel.clean() must run on create.

        Indirect test: create a DM, then try to create a *group* channel
        with the same dm: name — clean() must reject it. This proves the
        full_clean() path is wired up.
        """
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        canonical = resp.json()["name"]
        # Now build a group Channel with the same name and confirm
        # full_clean() rejects it (PR 1 guard).
        bad = Channel(workspace=self.ws, name=canonical, kind=Channel.KIND_GROUP)
        with self.assertRaises(ValidationError):
            bad.full_clean()

    def test_post_dms_agent_recipient(self):
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "agent:mamba-foo"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIn("agent:mamba-foo", data["name"])
        self.assertEqual(data["other_participants"][0]["type"], "agent")
        self.assertEqual(data["other_participants"][0]["identity_name"], "mamba-foo")

    # ---- GET /dms/ -----------------------------------------------------

    def test_get_dms_only_returns_callers_dms(self):
        # alice <-> bob
        self._login(self.alice)
        self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        # carol <-> bob (alice should NOT see this one)
        self.client.logout()
        self._login(self.carol)
        self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )

        # Alice's view
        self.client.logout()
        self._login(self.alice)
        resp = self.client.get("/api/workspace/dm-ws/dms/")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["dms"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["other_participants"][0]["identity_name"], "bob")

    # ---- /messages/ write-ACL fix (§8 / todo#258) ----------------------

    def test_messages_post_dm_non_participant_forbidden(self):
        # Create a DM between alice <-> bob
        self._login(self.alice)
        r = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        dm_name = r.json()["name"]
        self.client.logout()

        # Carol (not a participant) tries to post into the DM channel.
        self._login(self.carol)
        resp = self.client.post(
            "/api/workspace/dm-ws/messages/",
            data=json.dumps({"channel": dm_name, "text": "sneaky"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(Message.objects.filter(channel__name=dm_name).count(), 0)

    def test_messages_post_dm_participant_allowed(self):
        self._login(self.alice)
        r = self.client.post(
            "/api/workspace/dm-ws/dms/",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        dm_name = r.json()["name"]

        resp = self.client.post(
            "/api/workspace/dm-ws/messages/",
            data=json.dumps({"channel": dm_name, "text": "hi bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(Message.objects.filter(channel__name=dm_name).count(), 1)

    def test_messages_post_group_channel_unaffected(self):
        Channel.objects.create(workspace=self.ws, name="#general")
        self._login(self.alice)
        resp = self.client.post(
            "/api/workspace/dm-ws/messages/",
            data=json.dumps({"channel": "#general", "text": "hello"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)


# ── Web Push (todo#263) ─────────────────────────────────────────────────

from unittest.mock import MagicMock, patch

from hub import push as hub_push
from hub.models import PushSubscription
