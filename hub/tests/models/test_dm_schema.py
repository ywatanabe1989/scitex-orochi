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


class DMSchemaTest(TestCase):
    """Schema-only tests for DM support (scitex-orochi#60 PR 1).

    Covers the Channel.kind field, the dm: prefix guard on group
    channels (spec v3 §9 Q5), and the DMParticipant orochi_model's
    unique_together + cascade-delete semantics (spec v3 §2.2).
    """

    def setUp(self):
        self.ws = Workspace.objects.create(name="dm-ws")
        self.user_a = User.objects.create_user(username="alice", password="x")
        self.user_b = User.objects.create_user(username="bob", password="x")
        self.mem_a = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_a, role="member"
        )
        self.mem_b = WorkspaceMember.objects.create(
            workspace=self.ws, user=self.user_b, role="member"
        )

    def test_group_channel_rejects_dm_prefix(self):
        ch = Channel(workspace=self.ws, name="dm:alice|bob")  # default kind=group
        with self.assertRaises(ValidationError) as cm:
            ch.full_clean()
        self.assertIn("name", cm.exception.message_dict)

    def test_dm_channel_accepts_dm_prefix(self):
        ch = Channel(workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM)
        ch.full_clean()  # should not raise
        ch.save()
        self.assertEqual(ch.kind, "dm")

    def test_group_channel_default_kind_is_group(self):
        ch = Channel.objects.create(workspace=self.ws, name="#general")
        self.assertEqual(ch.kind, Channel.KIND_GROUP)

    def test_dm_participant_unique_together(self):
        ch = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_a,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DMParticipant.objects.create(
                    channel=ch,
                    member=self.mem_a,
                    principal_type=DMParticipant.PRINCIPAL_HUMAN,
                    identity_name="alice",
                )

    def test_dm_participant_cascade_on_channel_delete(self):
        ch = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_a,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_b,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="bob",
        )
        self.assertEqual(DMParticipant.objects.count(), 2)
        ch.delete()
        self.assertEqual(DMParticipant.objects.count(), 0)

    def test_dm_participant_cascade_on_member_delete(self):
        ch = Channel.objects.create(
            workspace=self.ws, name="dm:alice|bob", kind=Channel.KIND_DM
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_a,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="alice",
        )
        DMParticipant.objects.create(
            channel=ch,
            member=self.mem_b,
            principal_type=DMParticipant.PRINCIPAL_HUMAN,
            identity_name="bob",
        )
        self.mem_a.delete()
        remaining = list(DMParticipant.objects.all())
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].identity_name, "bob")
