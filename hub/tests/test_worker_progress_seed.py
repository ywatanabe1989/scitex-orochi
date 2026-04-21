"""Tests for ``manage.py seed_worker_progress`` (todo#272).

Covers:
  - Creates the synthetic ``agent-worker-progress`` user + workspace
    member + read-write ChannelMembership rows for the three base
    channels (#progress, #heads, #ywatanabe).
  - Dynamically enumerates ``#proj-*`` channels that exist in the
    workspace at seed time (no hardcoded list).
  - New ``#proj-*`` channels added after a seed run are picked up on
    the next run (forward-compatibility).
  - Idempotent: a second run creates no extra rows.
  - ``#agent`` is never subscribed (server-side blocklist protection).
  - ``read-only`` memberships are promoted to ``read-write``.
  - Missing workspace raises ``CommandError``.
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

    def _agent_user(self):
        return User.objects.get(username="agent-worker-progress")

    # --- base channels ---------------------------------------------------

    def test_creates_user_member_and_base_memberships(self):
        output = self._run("--workspace", "default")
        self.assertIn("created user", output)
        user = self._agent_user()
        self.assertTrue(
            WorkspaceMember.objects.filter(user=user, workspace=self.ws).exists()
        )
        for name in ("#progress", "#heads", "#ywatanabe"):
            ch = Channel.objects.get(workspace=self.ws, name=name)
            m = ChannelMembership.objects.get(user=user, channel=ch)
            self.assertEqual(m.permission, ChannelMembership.PERM_READ_WRITE)

    # --- dynamic #proj-* enumeration -------------------------------------

    def test_enumerates_existing_proj_channels(self):
        # Pre-existing project channels in the DB at seed time.
        Channel.objects.create(workspace=self.ws, name="#proj-alpha")
        Channel.objects.create(workspace=self.ws, name="#proj-beta")
        # A lookalike that MUST NOT match the #proj- prefix.
        Channel.objects.create(workspace=self.ws, name="#project-other")

        self._run("--workspace", "default")
        user = self._agent_user()

        # #proj-* subscribed.
        for name in ("#proj-alpha", "#proj-beta"):
            ch = Channel.objects.get(workspace=self.ws, name=name)
            m = ChannelMembership.objects.get(user=user, channel=ch)
            self.assertEqual(m.permission, ChannelMembership.PERM_READ_WRITE)

        # Non-matching lookalike must NOT be subscribed.
        other = Channel.objects.get(workspace=self.ws, name="#project-other")
        self.assertFalse(
            ChannelMembership.objects.filter(user=user, channel=other).exists()
        )

    def test_does_not_create_proj_channels_it_does_not_see(self):
        # Fresh DB: no #proj-* rows. Seeding must NOT invent any.
        self._run("--workspace", "default")
        self.assertFalse(
            Channel.objects.filter(
                workspace=self.ws, name__startswith="#proj-"
            ).exists()
        )

    def test_picks_up_new_proj_channel_on_rerun(self):
        # First run, nothing project-related.
        self._run("--workspace", "default")
        user = self._agent_user()
        self.assertFalse(
            ChannelMembership.objects.filter(
                user=user, channel__name__startswith="#proj-"
            ).exists()
        )

        # Someone creates a new project channel after first seed.
        new_ch = Channel.objects.create(workspace=self.ws, name="#proj-gamma")

        # Second run should pick it up.
        self._run("--workspace", "default")
        self.assertTrue(
            ChannelMembership.objects.filter(user=user, channel=new_ch).exists()
        )

    # --- idempotency -----------------------------------------------------

    def test_idempotent_no_duplicates(self):
        Channel.objects.create(workspace=self.ws, name="#proj-alpha")

        self._run("--workspace", "default")
        before_users = User.objects.count()
        before_members = ChannelMembership.objects.count()
        before_channels = Channel.objects.count()

        output = self._run("--workspace", "default")
        self.assertIn("user exists", output)
        self.assertEqual(User.objects.count(), before_users)
        self.assertEqual(ChannelMembership.objects.count(), before_members)
        self.assertEqual(Channel.objects.count(), before_channels)

    # --- abolished #agent ------------------------------------------------

    def test_abolished_agent_channel_never_subscribed(self):
        # Even if a stray '#agent' Channel row exists (pre-abolition),
        # the seed command must not create a ChannelMembership for it.
        Channel.objects.create(workspace=self.ws, name="#agent")
        self._run("--workspace", "default")
        user = self._agent_user()
        agent_ch = Channel.objects.get(workspace=self.ws, name="#agent")
        self.assertFalse(
            ChannelMembership.objects.filter(
                user=user, channel=agent_ch
            ).exists()
        )

    # --- read-only → read-write promotion --------------------------------

    def test_upgrades_read_only_to_read_write(self):
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

    # --- error handling --------------------------------------------------

    def test_missing_workspace_raises(self):
        with self.assertRaises(CommandError):
            self._run("--workspace", "does-not-exist")
