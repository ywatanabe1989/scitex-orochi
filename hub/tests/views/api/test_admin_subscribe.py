"""Tests for admin-scoped agent subscribe/unsubscribe (issue #262 §9.1).

The MCP ``subscribe`` / ``unsubscribe`` tools route to these endpoints
when called with the optional ``target_agent`` argument. Only fleet
coordinators (workspace ``admin`` or ``staff`` role) may use them; every
other caller gets a structured ``permission_denied`` envelope.

PR #272 introduced the views in ``hub/views/api/_agents_subscribe.py``
but the test suite landed in this follow-up so the auth gate cannot
silently regress.
"""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import (
    Channel,
    ChannelMembership,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
)


class AdminSubscribeRestApiTest(TestCase):
    """Coverage for ``/api/agents/<target>/subscribe|unsubscribe/``."""

    # Subdomain that the WorkspaceSubdomainMiddleware recognizes as
    # ``adm-ws.lvh.me`` -> request.workspace=adm-ws. The token-auth
    # tests below pass ``HTTP_HOST=lvh.me`` (bare domain) instead since
    # they identify the workspace via the token, not the host.
    SUBDOMAIN_HOST = "adm-ws.lvh.me"

    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="adm-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="ci")

        # Admin (fleet coordinator) -- explicit ``admin`` role.
        self.admin_user = User.objects.create_user(username="alice-admin", password="x")
        WorkspaceMember.objects.create(
            workspace=self.ws,
            user=self.admin_user,
            role=WorkspaceMember.Role.ADMIN,
        )

        # Plain agent -- synthetic ``agent-<name>`` user without admin role.
        self.regular_agent_user = User.objects.create_user(
            username="agent-regular-1", password="x"
        )
        WorkspaceMember.objects.create(
            workspace=self.ws,
            user=self.regular_agent_user,
            role=WorkspaceMember.Role.MEMBER,
        )

        # Pre-existing #ops channel.
        self.channel = Channel.objects.create(workspace=self.ws, name="#ops")

    # ── happy path ────────────────────────────────────────────────────

    def test_admin_subscribe_creates_membership(self):
        """Logged-in admin can subscribe a peer agent -- DB row appears."""
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            "/api/agents/peer-mba/subscribe/",
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
            HTTP_HOST=self.SUBDOMAIN_HOST,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["target_agent"], "peer-mba")
        self.assertEqual(body["channel"], "#ops")
        self.assertEqual(body["action"], "subscribe")

        # The synthetic agent user + ChannelMembership row must exist.
        self.assertTrue(User.objects.filter(username="agent-peer-mba").exists())
        self.assertTrue(
            ChannelMembership.objects.filter(
                user__username="agent-peer-mba",
                channel=self.channel,
            ).exists()
        )

    def test_admin_unsubscribe_removes_membership(self):
        """Admin can also remove the row again."""
        # Pre-create the membership.
        peer_user = User.objects.create_user(username="agent-peer-mba", password="x")
        ChannelMembership.objects.create(user=peer_user, channel=self.channel)

        self.client.force_login(self.admin_user)
        resp = self.client.post(
            "/api/agents/peer-mba/unsubscribe/",
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
            HTTP_HOST=self.SUBDOMAIN_HOST,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            ChannelMembership.objects.filter(
                user=peer_user,
                channel=self.channel,
            ).exists()
        )

    def test_admin_subscribe_token_path(self):
        """Token + ``?agent=<admin>`` path also works (MCP sidecar shape).

        The token-path actor is the synthetic ``agent-<name>`` user
        auto-provisioned by ``resolve_workspace_and_actor``. We verify
        that a freshly-provisioned synthetic agent (which defaults to
        member role) is rejected, then promote it to admin and retry.
        """
        url = (
            f"/api/agents/peer-mba/subscribe/"
            f"?token={self.token.token}&agent=alice-admin"
        )
        resp = self.client.post(
            url,
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

        promoted = WorkspaceMember.objects.get(
            workspace=self.ws,
            user__username="agent-alice-admin",
        )
        promoted.role = WorkspaceMember.Role.ADMIN
        promoted.save()

        resp = self.client.post(
            url,
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(
            ChannelMembership.objects.filter(
                user__username="agent-peer-mba",
                channel=self.channel,
            ).exists()
        )

    # ── permission denial ─────────────────────────────────────────────

    def test_non_admin_gets_structured_permission_denied(self):
        """Non-admin agent (token-auth, member role) is rejected with 403."""
        url = (
            f"/api/agents/peer-mba/subscribe/"
            f"?token={self.token.token}&agent=regular-1"
        )
        resp = self.client.post(
            url,
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        body = resp.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], "permission_denied")
        self.assertIn("agent-scope tokens", body["error"]["reason"])
        self.assertIn("admin", body["error"]["hint"].lower())
        # No membership row created.
        self.assertFalse(
            ChannelMembership.objects.filter(
                user__username="agent-peer-mba",
                channel=self.channel,
            ).exists()
        )

    def test_non_admin_unsubscribe_also_blocked(self):
        url = (
            f"/api/agents/peer-mba/unsubscribe/"
            f"?token={self.token.token}&agent=regular-1"
        )
        resp = self.client.post(
            url,
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.json()["error"]["code"], "permission_denied")

    def test_unauthenticated_returns_401(self):
        resp = self.client.post(
            "/api/agents/peer-mba/subscribe/",
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
            HTTP_HOST=self.SUBDOMAIN_HOST,
        )
        self.assertEqual(resp.status_code, 401, resp.content)

    # ── input validation ──────────────────────────────────────────────

    def test_missing_channel_returns_invalid_input(self):
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            "/api/agents/peer-mba/subscribe/",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_HOST=self.SUBDOMAIN_HOST,
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "invalid_input")

    def test_bad_target_name_returns_invalid_input(self):
        self.client.force_login(self.admin_user)
        # URL routing only allows path-safe strings; a "bad/name" would
        # never reach the view. Test the in-view regex instead with a
        # name containing a disallowed character that can pass the URL
        # router (e.g. a tilde).
        resp = self.client.post(
            "/api/agents/peer~bad/subscribe/",
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
            HTTP_HOST=self.SUBDOMAIN_HOST,
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()["error"]["code"], "invalid_input")

    def test_bare_domain_route_resolves_via_token(self):
        """Same endpoint must be reachable on the bare domain (lvh.me).

        MCP sidecars hit the apex with ``?token=...&agent=<self>``; the
        workspace is resolved from the token, not from a subdomain. This
        is the canonical admin-call shape from a coordinator agent.
        """
        WorkspaceMember.objects.create(
            workspace=self.ws,
            user=User.objects.create_user(username="agent-alice-admin", password="x"),
            role=WorkspaceMember.Role.ADMIN,
        )
        url = (
            f"/api/agents/peer-mba/subscribe/"
            f"?token={self.token.token}&agent=alice-admin"
        )
        resp = self.client.post(
            url,
            data=json.dumps({"channel": "#ops"}),
            content_type="application/json",
            HTTP_HOST="lvh.me",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(
            ChannelMembership.objects.filter(
                user__username="agent-peer-mba",
                channel=self.channel,
            ).exists()
        )
