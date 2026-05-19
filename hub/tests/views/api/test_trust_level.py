"""Tests for WorkspaceMember.trust_level field + PATCH /api/members/ (todo#410)."""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceMember


def _ws_host(ws):
    return f"{ws.name}.lvh.me"


class TrustLevelAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="tl-ws")
        self.admin = User.objects.create_user(username="admin", password="pass")
        self.admin_member = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.admin, role=WorkspaceMember.Role.ADMIN,
            trust_level=WorkspaceMember.TrustLevel.OWNER,
        )
        self.member = User.objects.create_user(username="guest", password="pass")
        self.guest_member = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.member, role=WorkspaceMember.Role.MEMBER,
            trust_level=WorkspaceMember.TrustLevel.GUEST,
        )

    def _get(self, user="admin"):
        self.client.login(username=user, password="pass")
        return self.client.get("/api/members/", HTTP_HOST=_ws_host(self.ws))

    def _patch(self, body, user="admin"):
        self.client.login(username=user, password="pass")
        return self.client.patch(
            "/api/members/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=_ws_host(self.ws),
        )

    # GET tests

    def test_get_includes_trust_level(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        entry = next(m for m in data if m["username"] == "admin")
        self.assertIn("trust_level", entry)
        self.assertEqual(entry["trust_level"], "owner")

    def test_get_guest_trust_level(self):
        resp = self._get()
        data = resp.json()
        entry = next(m for m in data if m["username"] == "guest")
        self.assertEqual(entry["trust_level"], "guest")

    # PATCH tests

    def test_admin_can_update_trust_level(self):
        resp = self._patch({"username": "guest", "trust_level": "collaborator"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["trust_level"], "collaborator")
        self.guest_member.refresh_from_db()
        self.assertEqual(self.guest_member.trust_level, "collaborator")

    def test_non_admin_cannot_update_trust_level(self):
        resp = self._patch({"username": "admin", "trust_level": "guest"}, user="guest")
        self.assertEqual(resp.status_code, 403)

    def test_invalid_trust_level_returns_400(self):
        resp = self._patch({"username": "guest", "trust_level": "superuser"})
        self.assertEqual(resp.status_code, 400)

    def test_missing_username_returns_400(self):
        resp = self._patch({"trust_level": "owner"})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_username_returns_404(self):
        resp = self._patch({"username": "nobody", "trust_level": "guest"})
        self.assertEqual(resp.status_code, 404)

    def test_all_valid_levels_accepted(self):
        for level in ("owner", "supervisor", "collaborator", "guest", "unknown"):
            resp = self._patch({"username": "guest", "trust_level": level})
            self.assertEqual(resp.status_code, 200, f"level {level!r} failed")

    # Model default

    def test_default_trust_level_is_collaborator(self):
        new_user = User.objects.create_user(username="newbie", password="pass")
        m = WorkspaceMember.objects.create(
            workspace=self.ws, user=new_user, role=WorkspaceMember.Role.MEMBER
        )
        self.assertEqual(m.trust_level, WorkspaceMember.TrustLevel.COLLABORATOR)
