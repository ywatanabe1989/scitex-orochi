"""Coverage for GET /api/me/subscriptions/ (#253).

A token-authed agent must see only its own ChannelMembership rows
inside the resolved workspace — never another agent's, never a
different workspace's, and never any other agent's auto-created stub.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import (
    Channel,
    ChannelMembership,
    Workspace,
    WorkspaceMember,
    WorkspaceToken,
)


class MySubscriptionsTokenAuthTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="sub-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="ci")

        # Two agents; each subscribed to a different set of channels.
        self.alpha = User.objects.create_user(username="agent-alpha", password="")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.alpha, role="member"
        )
        self.beta = User.objects.create_user(username="agent-beta", password="")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.beta, role="member")

        self.ch_a = Channel.objects.create(workspace=self.ws, name="#alpha-only")
        self.ch_shared = Channel.objects.create(workspace=self.ws, name="#shared")
        self.ch_b = Channel.objects.create(workspace=self.ws, name="#beta-only")
        ChannelMembership.objects.create(user=self.alpha, channel=self.ch_a)
        ChannelMembership.objects.create(user=self.alpha, channel=self.ch_shared)
        ChannelMembership.objects.create(
            user=self.beta,
            channel=self.ch_shared,
            permission=ChannelMembership.PERM_READ_ONLY,
        )
        ChannelMembership.objects.create(user=self.beta, channel=self.ch_b)

    def _bare_get(self, path):
        return self.client.get(path, HTTP_HOST="lvh.me")

    # ── Bare-domain endpoints ───────────────────────────────────────────

    def test_alpha_sees_only_alpha_subs_bare(self):
        url = (
            f"/api/workspace/sub-ws/me/subscriptions/"
            f"?token={self.token.token}&agent=alpha"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        names = sorted(r["channel"] for r in rows)
        self.assertEqual(names, ["#alpha-only", "#shared"])
        roles = {r["channel"]: r["role"] for r in rows}
        self.assertEqual(roles["#shared"], "read-write")
        self.assertEqual(roles["#alpha-only"], "read-write")
        for r in rows:
            self.assertIn("joined_at", r)
            self.assertIsNotNone(r["joined_at"])

    def test_beta_sees_only_beta_subs_bare(self):
        url = (
            f"/api/workspace/sub-ws/me/subscriptions/"
            f"?token={self.token.token}&agent=beta"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        names = sorted(r["channel"] for r in rows)
        self.assertEqual(names, ["#beta-only", "#shared"])
        roles = {r["channel"]: r["role"] for r in rows}
        self.assertEqual(roles["#shared"], "read-only")

    def test_flat_path_resolves_on_bare(self):
        """The bare /api/me/subscriptions/ shortcut also works."""
        url = (
            f"/api/me/subscriptions/?token={self.token.token}"
            f"&agent=alpha"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        names = sorted(r["channel"] for r in rows)
        self.assertEqual(names, ["#alpha-only", "#shared"])

    def test_invalid_token_returns_401_bare(self):
        url = "/api/workspace/sub-ws/me/subscriptions/?token=wks_NO&agent=alpha"
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 401, resp.content)

    def test_missing_agent_returns_400_bare(self):
        url = f"/api/workspace/sub-ws/me/subscriptions/?token={self.token.token}"
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_new_agent_sees_empty_list(self):
        """First-sight agent gets auto-provisioned and returns []."""
        url = (
            f"/api/workspace/sub-ws/me/subscriptions/"
            f"?token={self.token.token}&agent=fresh-one"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), [])

    # ── Subdomain (urls_workspace) route ────────────────────────────────

    def test_subdomain_route(self):
        url = (
            f"/api/me/subscriptions/?token={self.token.token}"
            f"&agent=beta"
        )
        resp = self.client.get(url, HTTP_HOST="sub-ws.lvh.me")
        self.assertEqual(resp.status_code, 200, resp.content)
        names = sorted(r["channel"] for r in resp.json())
        self.assertEqual(names, ["#beta-only", "#shared"])

    # ── Cross-workspace isolation ───────────────────────────────────────

    def test_cross_workspace_isolation(self):
        """Memberships in another workspace must not leak into the response."""
        other = Workspace.objects.create(name="other-ws")
        WorkspaceMember.objects.create(workspace=other, user=self.alpha, role="member")
        ch_other = Channel.objects.create(workspace=other, name="#secret")
        ChannelMembership.objects.create(user=self.alpha, channel=ch_other)

        url = (
            f"/api/workspace/sub-ws/me/subscriptions/"
            f"?token={self.token.token}&agent=alpha"
        )
        resp = self._bare_get(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        names = [r["channel"] for r in resp.json()]
        self.assertNotIn("#secret", names)
