"""Tests for the ``ChannelMembership.can_read`` / ``can_write`` bit-split.

Lead directive msg#16884. Covers the model-level bridge between the
legacy ``permission`` enum and the new boolean bits, and the data-
migration forward + reverse paths. Read-side / write-side / seed
behaviour live in sibling tests:

  - ``hub/tests/consumers/test_agent_subscription.py`` (+ new cases
    in this file) — ``can_read=False`` → no group join.
  - ``hub/tests/views/api/test_channel_members.py`` — REST body accepts
    bits.
  - ``hub/tests/test_worker_progress_seed.py`` — #ywatanabe seeded
    ``can_read=False, can_write=True``.
"""

from __future__ import annotations

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from hub.channel_acl import check_membership_allowed
from hub.models import Channel, ChannelMembership, Workspace


class ChannelMembershipBitsModelTest(TestCase):
    """Bridge between the legacy ``permission`` enum and the new bits."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="bits-ws")
        self.ch = Channel.objects.create(workspace=self.ws, name="#ops")
        self.user = User.objects.create(username="agent-bits-user")

    def test_defaults_are_read_write(self):
        m = ChannelMembership.objects.create(user=self.user, channel=self.ch)
        self.assertTrue(m.can_read)
        self.assertTrue(m.can_write)
        # Legacy-string bridge stays in sync on save().
        self.assertEqual(m.permission, ChannelMembership.PERM_READ_WRITE)

    def test_read_only_bits_set_legacy_enum(self):
        m = ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=True, can_write=False
        )
        self.assertEqual(m.permission, ChannelMembership.PERM_READ_ONLY)

    def test_write_only_bits_set_legacy_enum(self):
        m = ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=False, can_write=True
        )
        self.assertEqual(m.permission, ChannelMembership.PERM_WRITE_ONLY)

    def test_locked_out_bits_fall_back_to_read_only_label(self):
        # (False, False) has no legacy enum — save() maps it to the
        # most-restrictive label so legacy readers stay safe.
        m = ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=False, can_write=False
        )
        self.assertEqual(m.permission, ChannelMembership.PERM_READ_ONLY)

    def test_save_update_fields_auto_adds_permission(self):
        """Partial update of the bits must still sync the legacy enum.

        Without the ``update_fields`` fix-up in ``save()`` the enum
        silently desyncs on partial writes (``update_or_create``).
        """
        m = ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=True, can_write=True
        )
        m.can_write = False
        m.save(update_fields=["can_write"])
        m.refresh_from_db()
        self.assertFalse(m.can_write)
        self.assertEqual(m.permission, ChannelMembership.PERM_READ_ONLY)

    def test_update_or_create_on_bits(self):
        """``update_or_create`` (used by ``_persist_agent_subscription``)
        must flip the bits AND the legacy enum."""
        ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=True, can_write=True
        )
        ChannelMembership.objects.update_or_create(
            user=self.user,
            channel=self.ch,
            defaults={"can_read": False, "can_write": True},
        )
        m = ChannelMembership.objects.get(user=self.user, channel=self.ch)
        self.assertFalse(m.can_read)
        self.assertTrue(m.can_write)
        self.assertEqual(m.permission, ChannelMembership.PERM_WRITE_ONLY)

    def test_perm_to_bits_helper(self):
        self.assertEqual(
            ChannelMembership.perm_to_bits(ChannelMembership.PERM_READ_WRITE),
            (True, True),
        )
        self.assertEqual(
            ChannelMembership.perm_to_bits(ChannelMembership.PERM_READ_ONLY),
            (True, False),
        )
        self.assertEqual(
            ChannelMembership.perm_to_bits(ChannelMembership.PERM_WRITE_ONLY),
            (False, True),
        )
        # Unknown → permissive default.
        self.assertEqual(
            ChannelMembership.perm_to_bits("garbage-unknown"), (True, True)
        )

    def test_bits_to_perm_helper(self):
        self.assertEqual(
            ChannelMembership.bits_to_perm(True, True),
            ChannelMembership.PERM_READ_WRITE,
        )
        self.assertEqual(
            ChannelMembership.bits_to_perm(True, False),
            ChannelMembership.PERM_READ_ONLY,
        )
        self.assertEqual(
            ChannelMembership.bits_to_perm(False, True),
            ChannelMembership.PERM_WRITE_ONLY,
        )
        # Lockout → read-only label.
        self.assertEqual(
            ChannelMembership.bits_to_perm(False, False),
            ChannelMembership.PERM_READ_ONLY,
        )


class ChannelMembershipWriteAclTest(TestCase):
    """``check_membership_allowed`` uses the ``can_write`` bit."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="acl-ws")
        self.ch = Channel.objects.create(workspace=self.ws, name="#ops")
        self.user = User.objects.create(username="agent-acl-user")

    def test_can_write_true_allows(self):
        ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=True, can_write=True
        )
        self.assertTrue(
            check_membership_allowed(
                "agent-acl-user", "#ops", workspace_id=self.ws.id
            )
        )

    def test_can_write_false_denies(self):
        ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=True, can_write=False
        )
        self.assertFalse(
            check_membership_allowed(
                "agent-acl-user", "#ops", workspace_id=self.ws.id
            )
        )

    def test_write_only_allows_write(self):
        ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=False, can_write=True
        )
        self.assertTrue(
            check_membership_allowed(
                "agent-acl-user", "#ops", workspace_id=self.ws.id
            )
        )

    def test_locked_out_denies_write(self):
        ChannelMembership.objects.create(
            user=self.user, channel=self.ch, can_read=False, can_write=False
        )
        self.assertFalse(
            check_membership_allowed(
                "agent-acl-user", "#ops", workspace_id=self.ws.id
            )
        )


class ChannelMembershipReadFilterTest(TestCase):
    """``_load_agent_channel_subs`` excludes ``can_read=False`` rows."""

    def setUp(self):
        self.ws = Workspace.objects.create(name="read-filter-ws")
        self.readable = Channel.objects.create(workspace=self.ws, name="#readable")
        self.write_only = Channel.objects.create(
            workspace=self.ws, name="#write-only-ch"
        )
        self.user = User.objects.create(username="agent-reader")
        ChannelMembership.objects.create(
            user=self.user, channel=self.readable, can_read=True, can_write=True
        )
        ChannelMembership.objects.create(
            user=self.user,
            channel=self.write_only,
            can_read=False,
            can_write=True,
        )

    def test_write_only_excluded_from_subs(self):
        from asgiref.sync import async_to_sync

        from hub.consumers import _load_agent_channel_subs

        subs = async_to_sync(_load_agent_channel_subs)(self.ws.id, "reader")
        self.assertIn("#readable", subs)
        self.assertNotIn(
            "#write-only-ch",
            subs,
            "write-only (can_read=False) row must not appear in read-side subs",
        )


class ChannelMembershipMigrationDataTest(TransactionTestCase):
    """Data-preserving test: 0029 backfills bits from the enum.

    Uses ``MigrationExecutor`` to run the migration graph up to 0028
    (pre-bit-split), stamp data, run 0029, and assert the bits reflect
    the enum values. Then reverses 0029 and asserts the enum survives.
    """

    reset_sequences = True

    def test_forward_backfills_bits_from_permission(self):
        executor = MigrationExecutor(connection)
        # Roll back to the pre-bit-split schema.
        executor.migrate([("hub", "0028_alter_channelmembership_permission")])
        executor.loader.build_graph()
        old_state = executor.loader.project_state(
            [("hub", "0028_alter_channelmembership_permission")]
        ).apps
        OldWorkspace = old_state.get_model("hub", "Workspace")
        OldChannel = old_state.get_model("hub", "Channel")
        OldMembership = old_state.get_model("hub", "ChannelMembership")
        OldUser = old_state.get_model("auth", "User")

        ws = OldWorkspace.objects.create(name="mig-ws")
        ch_rw = OldChannel.objects.create(workspace=ws, name="#rw")
        ch_ro = OldChannel.objects.create(workspace=ws, name="#ro")
        ch_wo = OldChannel.objects.create(workspace=ws, name="#wo")
        u = OldUser.objects.create(username="agent-mig-user")
        OldMembership.objects.create(user=u, channel=ch_rw, permission="read-write")
        OldMembership.objects.create(user=u, channel=ch_ro, permission="read-only")
        OldMembership.objects.create(user=u, channel=ch_wo, permission="write-only")

        # Roll forward to 0029 — bits should be backfilled.
        executor.loader.build_graph()
        executor.migrate([("hub", "0029_channelmembership_can_read_can_write")])
        new_state = executor.loader.project_state(
            [("hub", "0029_channelmembership_can_read_can_write")]
        ).apps
        NewMembership = new_state.get_model("hub", "ChannelMembership")

        rw_row = NewMembership.objects.get(channel__name="#rw")
        self.assertTrue(rw_row.can_read)
        self.assertTrue(rw_row.can_write)

        ro_row = NewMembership.objects.get(channel__name="#ro")
        self.assertTrue(ro_row.can_read)
        self.assertFalse(ro_row.can_write)

        wo_row = NewMembership.objects.get(channel__name="#wo")
        self.assertFalse(wo_row.can_read)
        self.assertTrue(wo_row.can_write)

    def test_reverse_rebuilds_permission_from_bits(self):
        executor = MigrationExecutor(connection)
        executor.migrate(
            [("hub", "0029_channelmembership_can_read_can_write")]
        )
        new_state = executor.loader.project_state(
            [("hub", "0029_channelmembership_can_read_can_write")]
        ).apps
        Workspace = new_state.get_model("hub", "Workspace")
        Channel = new_state.get_model("hub", "Channel")
        Membership = new_state.get_model("hub", "ChannelMembership")
        User = new_state.get_model("auth", "User")

        ws = Workspace.objects.create(name="rev-ws")
        ch = Channel.objects.create(workspace=ws, name="#revert-target")
        u = User.objects.create(username="agent-rev-user")
        # Write-only bits, stale permission string (simulates a partial write
        # that the new save() bridge would have fixed on the app layer).
        Membership.objects.create(
            user=u,
            channel=ch,
            permission="read-write",
            can_read=False,
            can_write=True,
        )

        # Reverse 0029 — permission must be rebuilt from the bits before
        # the columns go away.
        executor.loader.build_graph()
        executor.migrate(
            [("hub", "0028_alter_channelmembership_permission")]
        )
        old_state = executor.loader.project_state(
            [("hub", "0028_alter_channelmembership_permission")]
        ).apps
        OldMembership = old_state.get_model("hub", "ChannelMembership")
        row = OldMembership.objects.get(channel__name="#revert-target")
        self.assertEqual(row.permission, "write-only")

        # Leave the DB in the forward state for subsequent tests.
        executor.loader.build_graph()
        executor.migrate(
            [("hub", "0029_channelmembership_can_read_can_write")]
        )
