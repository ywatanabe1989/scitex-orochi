"""Token-auth coverage for GET /api/channel-members/ (#252).

The MCP ``channel_members`` tool hits the bare domain with
``?token=wks_...&agent=<name>``; without these tests the token branch
on GET would silently regress the same way DM endpoints did in #258.
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


class ChannelMembersTokenAuthTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="cm-tok-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="ci")

        # One human, one agent — both subscribed to #general.
        self.human = User.objects.create_user(username="alice", password="x")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.human, role="member"
        )
        self.agent = User.objects.create_user(username="agent-worker-x", password="")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.agent, role="member"
        )
        self.ch = Channel.objects.create(workspace=self.ws, name="#general")
        ChannelMembership.objects.create(user=self.human, channel=self.ch)
        ChannelMembership.objects.create(user=self.agent, channel=self.ch)

    def _bare_get(self, path):
        """GET against the bare-domain URLconf via lvh.me host."""
        return self.client.get(path, HTTP_HOST="lvh.me")

    # ── Bare-domain (urls_bare) routes ──────────────────────────────────

    def test_get_with_token_no_session_bare(self):
        url = (
            f"/api/channel-members/?token={self.token.token}"
            f"&agent=worker-x&channel=%23general"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        names = sorted(r["username"] for r in rows)
        self.assertIn("alice", names)
        self.assertIn("agent-worker-x", names)

    def test_get_workspace_scoped_with_token_bare(self):
        url = (
            f"/api/workspace/cm-tok-ws/channel-members/"
            f"?token={self.token.token}&agent=worker-x&channel=%23general"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        self.assertTrue(any(r["username"] == "agent-worker-x" for r in rows))

    def test_get_invalid_token_returns_401_bare(self):
        url = (
            "/api/channel-members/?token=wks_BADBADBAD"
            "&agent=worker-x&channel=%23general"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_get_token_missing_agent_returns_400_bare(self):
        url = (
            f"/api/channel-members/?token={self.token.token}"
            f"&channel=%23general"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_get_token_unknown_channel_returns_404_bare(self):
        url = (
            f"/api/channel-members/?token={self.token.token}"
            f"&agent=worker-x&channel=%23ghost"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 404, resp.content)

    # ── Subdomain (urls_workspace) route still session-gates writes ─────

    def test_post_with_token_no_session_rejected(self):
        """POST/PATCH/DELETE remain session-only; token-auth GET only."""
        url = f"/api/channel-members/?token={self.token.token}&agent=worker-x"
        resp = self.client.post(
            url,
            data=json.dumps({"channel": "#general", "username": "agent-worker-x"}),
            content_type="application/json",
            HTTP_HOST="cm-tok-ws.lvh.me",
        )
        self.assertEqual(resp.status_code, 401, resp.content)
