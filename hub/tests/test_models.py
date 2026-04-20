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


class WorkspaceModelTest(TestCase):
    def test_create_workspace(self):
        ws = Workspace.objects.create(name="test-ws", description="Test workspace")
        self.assertEqual(str(ws), "test-ws")

    def test_workspace_token_auto_generated(self):
        ws = Workspace.objects.create(name="test-ws")
        token = WorkspaceToken.objects.create(workspace=ws, label="agent-1")
        self.assertTrue(token.token.startswith("wks_"))
        self.assertEqual(len(token.token), 36)  # "wks_" + 32 hex chars

    def test_channel_unique_per_workspace(self):
        ws = Workspace.objects.create(name="test-ws")
        Channel.objects.create(workspace=ws, name="#general")
        with self.assertRaises(Exception):
            Channel.objects.create(workspace=ws, name="#general")

    def test_message_creation(self):
        ws = Workspace.objects.create(name="test-ws")
        ch = Channel.objects.create(workspace=ws, name="#general")
        msg = Message.objects.create(
            workspace=ws, channel=ch, sender="agent-1", content="Hello"
        )
        self.assertEqual(msg.sender, "agent-1")
        self.assertEqual(msg.content, "Hello")
        self.assertIsNotNone(msg.ts)


class ChannelNameNormalizeTest(TestCase):
    """Coverage for the todo#326 write-side normalization."""

    def test_normalize_helper_adds_hash(self):
        self.assertEqual(normalize_channel_name("general"), "#general")
        self.assertEqual(normalize_channel_name("progress"), "#progress")

    def test_normalize_helper_passthrough_canonical(self):
        self.assertEqual(normalize_channel_name("#general"), "#general")
        self.assertEqual(normalize_channel_name("#agent"), "#agent")

    def test_normalize_helper_passthrough_dm(self):
        self.assertEqual(
            normalize_channel_name("dm:agent:head|human:ywatanabe"),
            "dm:agent:head|human:ywatanabe",
        )

    def test_normalize_helper_strips_whitespace(self):
        self.assertEqual(normalize_channel_name("  general  "), "#general")

    def test_normalize_helper_rejects_empty(self):
        with self.assertRaises(ValueError):
            normalize_channel_name("")
        with self.assertRaises(ValueError):
            normalize_channel_name("   ")
        with self.assertRaises(ValueError):
            normalize_channel_name(None)

    def test_channel_save_normalizes_bare_name(self):
        ws = Workspace.objects.create(name="ws-norm")
        ch = Channel.objects.create(workspace=ws, name="general")
        ch.refresh_from_db()
        self.assertEqual(ch.name, "#general")

    def test_channel_save_passes_canonical_through(self):
        ws = Workspace.objects.create(name="ws-norm-2")
        ch = Channel.objects.create(workspace=ws, name="#agent")
        ch.refresh_from_db()
        self.assertEqual(ch.name, "#agent")

    def test_channel_save_does_not_touch_dm_kind(self):
        ws = Workspace.objects.create(name="ws-norm-3")
        # DM channels keep their dm: prefix even on save.
        ch = Channel.objects.create(
            workspace=ws,
            name="dm:agent:head|human:ywatanabe",
            kind=Channel.KIND_DM,
        )
        ch.refresh_from_db()
        self.assertEqual(ch.name, "dm:agent:head|human:ywatanabe")

    def test_get_or_create_with_bare_then_canonical_collapses(self):
        """The legacy duplication scenario: an agent posts to ``general``
        then another posts to ``#general``. With the save() normalizer
        and call-site normalize_channel_name(), both must converge on
        the same row."""
        ws = Workspace.objects.create(name="ws-collapse")
        a, _ = Channel.objects.get_or_create(
            workspace=ws, name=normalize_channel_name("general")
        )
        b, _ = Channel.objects.get_or_create(
            workspace=ws, name=normalize_channel_name("#general")
        )
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Channel.objects.filter(workspace=ws).count(), 1)
