"""Tests for ``manage.py seed_worker_progress`` (todo#272).

Verifies:
  - Creates the synthetic ``agent-worker-progress`` user + workspace
    member + read-write ChannelMembership rows for #progress, #heads,
    #ywatanabe.
  - Idempotent: a second run creates no extra rows.
  - ``#agent`` is explicitly skipped even if passed via --channels.
  - Missing workspace raises CommandError.
"""

from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from hub.models import Channel, ChannelMembership, Workspace, WorkspaceMember

User = get_user_model()


class SeedWorkerProgressTest(TestCase):
    def setUp(self) -> None:
        self.ws = Workspace.objects.create(name="default")

    def _run(self, *args, **opts) -> str:
        out = StringIO()
        call_command("seed_worker_progress", *args, stdout=out, **opts)
        return out.getvalue()

    def test_creates_user_member_memberships(self):
        output = self._run("--workspace", "default")
        self.assertIn("created user", output)
        user = User.objects.get(username="agent-worker-progress")
        self.assertTrue(
            WorkspaceMember.objects.filter(user=user, workspace=self.ws).exists()
        )
        for name in ("#progress", "#heads", "#ywatanabe"):
            ch = Channel.objects.get(workspace=self.ws, name=name)
            m = ChannelMembership.objects.get(user=user, channel=ch)
            self.assertEqual(m.permission, ChannelMembership.PERM_READ_WRITE)

    def test_idempotent_no_duplicates(self):
        self._run("--workspace", "default")
        before_users = User.objects.count()
        before_members = ChannelMembership.objects.count()
        before_channels = Channel.objects.count()
        # Second run.
        output = self._run("--workspace", "default")
        self.assertIn("user exists", output)
        self.assertEqual(User.objects.count(), before_users)
        self.assertEqual(ChannelMembership.objects.count(), before_members)
        self.assertEqual(Channel.objects.count(), before_channels)

    def test_skips_abolished_agent_channel(self):
        output = self._run(
            "--workspace",
            "default",
            "--channels",
            "#progress",
            "#agent",
            "#heads",
        )
        self.assertIn("skipping abolished channel", output)
        # #agent must NOT have any Channel row created, and certainly
        # no ChannelMembership for agent-worker-progress.
        self.assertFalse(
            Channel.objects.filter(workspace=self.ws, name="#agent").exists()
        )

    def test_upgrades_read_only_to_read_write(self):
        # Pre-existing read-only membership: seed must promote to RW.
        user, _ = User.objects.get_or_create(username="agent-worker-progress")
        WorkspaceMember.objects.create(user=user, workspace=self.ws)
        ch = Channel.objects.create(workspace=self.ws, name="#progress")
        ChannelMembership.objects.create(
            user=user, channel=ch, permission=ChannelMembership.PERM_READ_ONLY
        )
        output = self._run("--workspace", "default")
        self.assertIn("upgraded to read-write", output)
        refreshed = ChannelMembership.objects.get(user=user, channel=ch)
        self.assertEqual(refreshed.permission, ChannelMembership.PERM_READ_WRITE)

    def test_missing_workspace_raises(self):
        with self.assertRaises(CommandError):
            self._run("--workspace", "does-not-exist")
