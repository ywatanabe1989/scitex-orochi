"""Tests for /api/agent-groups/ CRUD endpoints (todo#428)."""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import AgentGroup, Workspace, WorkspaceMember


def _make_workspace(name="test-ag-ws"):
    return Workspace.objects.create(name=name)


def _make_user(username, ws=None, role="member"):
    u = User.objects.create_user(username=username, password="pw")
    if ws:
        WorkspaceMember.objects.create(workspace=ws, user=u, role=role)
    return u


class AgentGroupListTest(TestCase):
    def setUp(self):
        self.ws = _make_workspace("ag-list-ws")
        self.user = _make_user("alice", self.ws)
        self.host = f"{self.ws.name}.lvh.me"
        self.client = Client()
        self.client.force_login(self.user)

    def _get(self, path):
        return self.client.get(path, HTTP_HOST=self.host)

    def test_empty_list(self):
        resp = self._get("/api/agent-groups/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_returns_groups(self):
        AgentGroup.objects.create(
            workspace=self.ws, name="paper-team", is_builtin=False
        )
        resp = self._get("/api/agent-groups/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "paper-team")

    def test_unauthenticated_redirects(self):
        c = Client()
        resp = c.get("/api/agent-groups/", HTTP_HOST=self.host)
        self.assertIn(resp.status_code, (302, 401))


class AgentGroupCreateTest(TestCase):
    def setUp(self):
        self.ws = _make_workspace("ag-create-ws")
        self.user = _make_user("bob", self.ws)
        self.host = f"{self.ws.name}.lvh.me"
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, body):
        return self.client.post(
            "/api/agent-groups/create/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=self.host,
        )

    def test_create_group(self):
        resp = self._post({"name": "ui-team", "display_name": "UI Team"})
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "ui-team")
        self.assertEqual(data["display_name"], "UI Team")
        self.assertFalse(data["is_builtin"])
        self.assertTrue(AgentGroup.objects.filter(workspace=self.ws, name="ui-team").exists())

    def test_create_duplicate_returns_409(self):
        AgentGroup.objects.create(workspace=self.ws, name="ui-team")
        resp = self._post({"name": "ui-team"})
        self.assertEqual(resp.status_code, 409)

    def test_create_without_name_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)

    def test_create_with_members(self):
        target = _make_user("agent-head-mba", self.ws)
        resp = self._post({"name": "leads", "members": ["agent-head-mba"]})
        self.assertEqual(resp.status_code, 201)
        grp = AgentGroup.objects.get(workspace=self.ws, name="leads")
        self.assertIn(target, grp.members.all())


class AgentGroupDetailTest(TestCase):
    def setUp(self):
        self.ws = _make_workspace("ag-detail-ws")
        self.user = _make_user("carol", self.ws)
        self.host = f"{self.ws.name}.lvh.me"
        self.client = Client()
        self.client.force_login(self.user)
        self.grp = AgentGroup.objects.create(
            workspace=self.ws, name="eng", owner=self.user
        )

    def _patch(self, name, body):
        return self.client.patch(
            f"/api/agent-groups/{name}/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=self.host,
        )

    def _delete(self, name):
        return self.client.delete(
            f"/api/agent-groups/{name}/",
            HTTP_HOST=self.host,
        )

    def test_patch_display_name(self):
        resp = self._patch("eng", {"display_name": "Engineering"})
        self.assertEqual(resp.status_code, 200)
        self.grp.refresh_from_db()
        self.assertEqual(self.grp.display_name, "Engineering")

    def test_patch_unknown_group_returns_404(self):
        resp = self._patch("no-such-group", {"display_name": "x"})
        self.assertEqual(resp.status_code, 404)

    def test_delete_custom_group(self):
        resp = self._delete("eng")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(AgentGroup.objects.filter(workspace=self.ws, name="eng").exists())

    def test_delete_builtin_group_returns_403(self):
        AgentGroup.objects.create(workspace=self.ws, name="heads", is_builtin=True)
        resp = self._delete("heads")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(AgentGroup.objects.filter(workspace=self.ws, name="heads").exists())

    def test_delete_other_user_group_returns_403(self):
        other = _make_user("dave", self.ws)
        AgentGroup.objects.create(workspace=self.ws, name="others-group", owner=other)
        resp = self._delete("others-group")
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(AgentGroup.objects.filter(workspace=self.ws, name="others-group").exists())
