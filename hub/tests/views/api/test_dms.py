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


# ── Token-auth on workspace-scoped routes (issues #258 + #254) ──────────


class DmTokenAuthTest(TestCase):
    """MCP sidecars hit the bare domain with ``?token=wks_...&agent=<name>``.

    These tests pin the token-auth path independently of any Django session
    cookie so the regression that took out ``dm_open`` / ``dm_list`` /
    ``channel_info`` cannot reappear silently.
    """

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="tok-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="ci")
        self.bob = User.objects.create_user(username="bob", password="x")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.bob)

    def test_post_dms_with_token_no_session(self):
        """POST /api/workspace/<slug>/dms/?token=...&agent=... opens a DM."""
        url = (
            f"/api/workspace/tok-ws/dms/"
            f"?token={self.token.token}&agent=mamba-foo"
        )
        resp = self.client.post(
            url,
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        # Canonical channel name with both principals.
        self.assertIn("agent:mamba-foo", data["name"])
        self.assertIn("human:bob", data["name"])
        # The synthetic agent user was auto-provisioned as a member.
        self.assertTrue(
            User.objects.filter(username="agent-mamba-foo").exists(),
            "token branch must auto-provision the agent's User row",
        )
        self.assertTrue(
            WorkspaceMember.objects.filter(
                workspace=self.ws, user__username="agent-mamba-foo"
            ).exists(),
            "token branch must auto-provision the WorkspaceMember row",
        )

    def test_get_dms_with_token_no_session(self):
        url_post = (
            f"/api/workspace/tok-ws/dms/?token={self.token.token}&agent=mamba-foo"
        )
        self.client.post(
            url_post,
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        resp = self.client.get(url_post)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()["dms"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["other_participants"][0]["identity_name"], "bob")

    def test_dms_token_invalid_returns_401(self):
        resp = self.client.post(
            "/api/workspace/tok-ws/dms/?token=wks_BADBADBAD&agent=mamba-foo",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_dms_token_missing_agent_returns_400(self):
        resp = self.client.post(
            f"/api/workspace/tok-ws/dms/?token={self.token.token}",
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_channels_get_with_token_no_session(self):
        """GET /api/channels/?token=...&name=#X — the channel_info path.

        Hits ``lvh.me`` (a bare-domain alias the middleware recognizes) so
        the request is dispatched against ``hub.urls_bare`` — which is
        exactly what MCP sidecars do when they call
        ``https://scitex-orochi.com/api/channels/?...``. Without the
        bare-domain route added in this PR the call 404s.
        """
        Channel.objects.create(workspace=self.ws, name="#general")
        resp = self.client.get(
            f"/api/channels/?token={self.token.token}&name=%23general",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        names = [c["name"] for c in data]
        self.assertIn("#general", names)

    def test_channels_get_invalid_token_returns_401(self):
        resp = self.client.get(
            "/api/channels/?token=wks_BADBADBAD", HTTP_HOST="lvh.me"
        )
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_workspace_scoped_channels_with_token(self):
        """GET /api/workspace/<slug>/channels/?token=... resolves on bare domain."""
        Channel.objects.create(workspace=self.ws, name="#proj-x")
        resp = self.client.get(
            f"/api/workspace/tok-ws/channels/?token={self.token.token}",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        names = [c["name"] for c in resp.json()]
        self.assertIn("#proj-x", names)

    def test_workspace_scoped_dms_resolves_on_bare_domain(self):
        """POST /api/workspace/<slug>/dms/?token=... on the bare domain works.

        Pin for issue #258 — the exact MCP request shape that previously
        404'd in production because the route wasn't mounted in
        ``hub.urls_bare``.
        """
        resp = self.client.post(
            (
                f"/api/workspace/tok-ws/dms/"
                f"?token={self.token.token}&agent=mamba-foo"
            ),
            data=json.dumps({"recipient": "human:bob"}),
            content_type="application/json",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIn("agent:mamba-foo", data["name"])
        self.assertIn("human:bob", data["name"])


# ── Web Push (todo#263) ─────────────────────────────────────────────────


