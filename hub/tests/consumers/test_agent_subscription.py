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


class AgentChannelSubscriptionPersistenceTest(TestCase):
    """Server-authoritative channel subscription — persist to ChannelMembership
    and hydrate on register.
    """

    def setUp(self):
        from hub.models import Channel, ChannelMembership

        self.ChannelMembership = ChannelMembership
        self.Channel = Channel
        self.ws = Workspace.objects.create(name="sub-ws")

    def test_persist_subscribe_creates_membership(self):
        from asgiref.sync import async_to_sync
        from django.contrib.auth.models import User

        from hub.consumers import _persist_agent_subscription

        ok = async_to_sync(_persist_agent_subscription)(
            self.ws.id, "worker-a", "#alpha", True
        )
        self.assertTrue(ok)
        user = User.objects.get(username="agent-worker-a")
        ch = self.Channel.objects.get(workspace=self.ws, name="#alpha")
        self.assertTrue(
            self.ChannelMembership.objects.filter(user=user, channel=ch).exists()
        )

    def test_persist_unsubscribe_removes_membership(self):
        from asgiref.sync import async_to_sync

        from hub.consumers import _persist_agent_subscription

        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "worker-b", "#beta", True
        )
        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "worker-b", "#beta", False
        )
        ch = self.Channel.objects.get(workspace=self.ws, name="#beta")
        self.assertEqual(self.ChannelMembership.objects.filter(channel=ch).count(), 0)

    def test_hydrate_loads_persisted_subs(self):
        from asgiref.sync import async_to_sync

        from hub.consumers import (
            _load_agent_channel_subs,
            _persist_agent_subscription,
        )

        async_to_sync(_persist_agent_subscription)(self.ws.id, "worker-c", "#x", True)
        async_to_sync(_persist_agent_subscription)(self.ws.id, "worker-c", "#y", True)
        subs = async_to_sync(_load_agent_channel_subs)(self.ws.id, "worker-c")
        self.assertEqual(set(subs), {"#x", "#y"})

    def test_hydrate_returns_empty_for_unknown_agent(self):
        from asgiref.sync import async_to_sync

        from hub.consumers import _load_agent_channel_subs

        subs = async_to_sync(_load_agent_channel_subs)(self.ws.id, "never-registered")
        self.assertEqual(subs, [])

    def test_hydrate_scoped_per_workspace(self):
        from asgiref.sync import async_to_sync

        from hub.consumers import (
            _load_agent_channel_subs,
            _persist_agent_subscription,
        )

        ws2 = Workspace.objects.create(name="other-ws")
        async_to_sync(_persist_agent_subscription)(
            self.ws.id, "worker-d", "#self", True
        )
        async_to_sync(_persist_agent_subscription)(ws2.id, "worker-d", "#other", True)
        subs_self = async_to_sync(_load_agent_channel_subs)(self.ws.id, "worker-d")
        subs_other = async_to_sync(_load_agent_channel_subs)(ws2.id, "worker-d")
        self.assertEqual(subs_self, ["#self"])
        self.assertEqual(subs_other, ["#other"])
