"""Tests for POST/GET /api/invitations/ and DELETE /api/invitations/<token>/."""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from hub.models import Workspace, WorkspaceInvitation, WorkspaceMember


def _ws_host(ws):
    return f"{ws.name}.lvh.me"


class InvitationAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.ws = Workspace.objects.create(name="inv-ws")
        self.admin = User.objects.create_user(username="admin", password="pass")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.admin, role=WorkspaceMember.Role.ADMIN
        )
        self.member = User.objects.create_user(username="member", password="pass")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.member, role=WorkspaceMember.Role.MEMBER
        )

    def _post(self, body, user="admin"):
        if user == "admin":
            self.client.login(username="admin", password="pass")
        elif user == "member":
            self.client.login(username="member", password="pass")
        return self.client.post(
            "/api/invitations/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_HOST=_ws_host(self.ws),
        )

    def _get(self, user="admin"):
        if user == "admin":
            self.client.login(username="admin", password="pass")
        return self.client.get(
            "/api/invitations/",
            HTTP_HOST=_ws_host(self.ws),
        )

    def test_admin_can_create_invitation(self):
        resp = self._post({"email": "guest@example.com"})
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn("token", data)
        self.assertIn("invite_url", data)
        self.assertIn("/invite/", data["invite_url"])
        self.assertEqual(data["email"], "guest@example.com")
        self.assertEqual(data["status"], "created")

    def test_invitation_created_in_db(self):
        self._post({"email": "stored@example.com"})
        self.assertTrue(
            WorkspaceInvitation.objects.filter(
                workspace=self.ws, email="stored@example.com", accepted=False
            ).exists()
        )

    def test_non_admin_member_gets_403(self):
        resp = self._post({"email": "guest@example.com"}, user="member")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_gets_401(self):
        self.client.logout()
        resp = self.client.post(
            "/api/invitations/",
            data=json.dumps({"email": "x@x.com"}),
            content_type="application/json",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(resp.status_code, 401)

    def test_missing_email_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_email_returns_400(self):
        resp = self._post({"email": "notanemail"})
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_invite_returns_existing(self):
        self._post({"email": "dup@example.com"})
        resp = self._post({"email": "dup@example.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "existing")
        self.assertEqual(
            WorkspaceInvitation.objects.filter(
                workspace=self.ws, email="dup@example.com"
            ).count(),
            1,
        )

    def test_list_invitations(self):
        self._post({"email": "a@example.com"})
        self._post({"email": "b@example.com"})
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        emails = [inv["email"] for inv in data["invitations"]]
        self.assertIn("a@example.com", emails)
        self.assertIn("b@example.com", emails)

    def test_delete_invitation_revokes_it(self):
        self.client.login(username="admin", password="pass")
        resp = self._post({"email": "revoke@example.com"})
        token = resp.json()["token"]
        del_resp = self.client.delete(
            f"/api/invitations/{token}/",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(
            WorkspaceInvitation.objects.filter(token=token, accepted=False).exists()
        )

    def test_delete_nonexistent_returns_404(self):
        self.client.login(username="admin", password="pass")
        resp = self.client.delete(
            "/api/invitations/nonexistent-token/",
            HTTP_HOST=_ws_host(self.ws),
        )
        self.assertEqual(resp.status_code, 404)
