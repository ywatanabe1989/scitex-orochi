"""Tests for hub/models/_identity.py — Workspace, WorkspaceToken, etc."""

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


class WorkspaceIdentityTest(TestCase):
    def test_create_workspace(self):
        ws = Workspace.objects.create(name="test-ws", description="Test workspace")
        self.assertEqual(str(ws), "test-ws")

    def test_workspace_token_auto_generated(self):
        ws = Workspace.objects.create(name="test-ws")
        token = WorkspaceToken.objects.create(workspace=ws, label="agent-1")
        self.assertTrue(token.token.startswith("wks_"))
        self.assertEqual(len(token.token), 36)  # "wks_" + 32 hex chars
