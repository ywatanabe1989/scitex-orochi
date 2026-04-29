"""Regression test: GET /api/agents/?token=... on bare domain must not 404.

When the request hits the bare domain (no subdomain middleware workspace),
the view must resolve the workspace from the token and return 200.

Covers the bug where WorkspaceToken was validated but the resolved workspace
was not attached to ``request``, causing ``get_workspace()`` to raise Http404.
"""

from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceToken


class AgentsListTokenBareTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="al-tok-ws")
        self.token = WorkspaceToken.objects.create(workspace=self.ws, label="ci")
        from hub.registry import _agents as _reg

        _reg.clear()

    def _bare_get(self, path):
        return self.client.get(path, HTTP_HOST="lvh.me")

    def test_token_auth_on_bare_domain_returns_200(self):
        """Token-authed GET /api/agents/ on bare domain should return 200, not 404."""
        resp = self._bare_get(f"/api/agents/?token={self.token.token}")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsInstance(resp.json(), list)

    def test_invalid_token_returns_401(self):
        resp = self._bare_get("/api/agents/?token=invalid")
        self.assertEqual(resp.status_code, 401)

    def test_no_token_no_session_returns_401(self):
        resp = self._bare_get("/api/agents/")
        self.assertEqual(resp.status_code, 401)
