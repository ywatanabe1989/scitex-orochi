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


class ChannelRenameApiTest(TestCase):
    """Channel rename endpoints — unblocks todo#71 drag-to-move + folder rename."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="rename-ws")
        self.host = f"{self.ws.name}.lvh.me"
        self.admin = User.objects.create_user(
            username="admin", password="x", is_staff=True, is_superuser=True
        )
        self.plain = User.objects.create_user(username="plain", password="x")
        WorkspaceMember.objects.create(workspace=self.ws, user=self.admin, role="admin")
        WorkspaceMember.objects.create(
            workspace=self.ws, user=self.plain, role="member"
        )
        self.ch = Channel.objects.create(workspace=self.ws, name="#proj/old-name")

    # ---- single-channel rename ---------------------------------------

    def test_rename_success_returns_id_and_new_name(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "proj/ripple-wm-v2"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["id"], self.ch.id)
        self.assertEqual(body["name"], "#proj/ripple-wm-v2")
        self.ch.refresh_from_db()
        self.assertEqual(self.ch.name, "#proj/ripple-wm-v2")

    def test_rename_accepts_hash_prefix_in_body(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "#proj/renamed"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "#proj/renamed")

    def test_rename_rejects_non_admin(self):
        self.client.force_login(self.plain)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "proj/new"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 403)

    def test_rename_missing_channel_returns_404(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channels/999999/rename/",
            data=json.dumps({"new_name": "proj/x"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 404)

    def test_rename_rejects_collision(self):
        Channel.objects.create(workspace=self.ws, name="#proj/taken")
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "proj/taken"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", resp.json()["error"])

    def test_rename_rejects_invalid_characters(self):
        self.client.force_login(self.admin)
        for bad in ("UPPER", "has space", "has!bang", "-starts-with-dash"):
            resp = self.client.post(
                f"/api/channels/{self.ch.id}/rename/",
                data=json.dumps({"new_name": bad}),
                content_type="application/json",
                HTTP_HOST=self.host,
            )
            self.assertEqual(
                resp.status_code,
                400,
                f"expected 400 for {bad!r}, got {resp.status_code}",
            )

    def test_rename_rejects_too_long(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "a" * 81}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 400)

    def test_rename_rejects_dm(self):
        dm = Channel.objects.create(
            workspace=self.ws,
            name="dm:human:admin|human:plain",
            kind=Channel.KIND_DM,
        )
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{dm.id}/rename/",
            data=json.dumps({"new_name": "proj/anything"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("DM", resp.json()["error"])

    def test_rename_rejects_dm_prefix_as_target(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "dm:foo"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 400)

    def test_rename_noop_is_idempotent(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            f"/api/channels/{self.ch.id}/rename/",
            data=json.dumps({"new_name": "proj/old-name"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "#proj/old-name")

    # ---- bulk prefix rename ------------------------------------------

    def test_rename_prefix_renames_all_matching(self):
        Channel.objects.create(workspace=self.ws, name="#proj/a")
        Channel.objects.create(workspace=self.ws, name="#proj/b")
        # Channel outside the prefix is untouched.
        Channel.objects.create(workspace=self.ws, name="#general")
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channels/rename-prefix/",
            data=json.dumps({"old_prefix": "proj/", "new_prefix": "projects/"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        new_names = {c.name for c in Channel.objects.filter(workspace=self.ws)}
        self.assertIn("#projects/old-name", new_names)
        self.assertIn("#projects/a", new_names)
        self.assertIn("#projects/b", new_names)
        self.assertIn("#general", new_names)
        self.assertNotIn("#proj/old-name", new_names)

    def test_rename_prefix_atomic_on_collision(self):
        Channel.objects.create(workspace=self.ws, name="#proj/a")
        # Pre-existing target that would collide.
        Channel.objects.create(workspace=self.ws, name="#projects/a")
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channels/rename-prefix/",
            data=json.dumps({"old_prefix": "proj/", "new_prefix": "projects/"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 400)
        # Atomic: neither the original nor the sibling channel was touched.
        self.assertTrue(
            Channel.objects.filter(workspace=self.ws, name="#proj/old-name").exists()
        )
        self.assertTrue(
            Channel.objects.filter(workspace=self.ws, name="#proj/a").exists()
        )

    def test_rename_prefix_rejects_non_admin(self):
        self.client.force_login(self.plain)
        resp = self.client.post(
            "/api/channels/rename-prefix/",
            data=json.dumps({"old_prefix": "proj/", "new_prefix": "projects/"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 403)

    def test_rename_prefix_empty_old_prefix_rejected(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channels/rename-prefix/",
            data=json.dumps({"old_prefix": "", "new_prefix": "projects/"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 400)

    def test_rename_prefix_no_matches_returns_empty_list(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            "/api/channels/rename-prefix/",
            data=json.dumps({"old_prefix": "nonexistent/", "new_prefix": "whatever/"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["renamed"], [])

    def test_rename_prefix_skips_dm_channels(self):
        Channel.objects.create(
            workspace=self.ws,
            name="dm:human:admin|human:plain",
            kind=Channel.KIND_DM,
        )
        self.client.force_login(self.admin)
        # Use a prefix that would start-match the bare dm name if DMs
        # were included; the endpoint must filter them out.
        resp = self.client.post(
            "/api/channels/rename-prefix/",
            data=json.dumps({"old_prefix": "dm", "new_prefix": "notdm"}),
            content_type="application/json",
            HTTP_HOST=self.host,
        )
        # Either renames zero rows, or returns a validation error; either
        # way the DM row must not be mutated.
        self.assertIn(resp.status_code, (200, 400))
        self.assertTrue(
            Channel.objects.filter(
                workspace=self.ws, name="dm:human:admin|human:plain"
            ).exists()
        )
