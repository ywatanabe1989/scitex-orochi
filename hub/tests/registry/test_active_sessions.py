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


class ActiveSessionCounterTests(TestCase):
    """Tests for per-agent active WebSocket session tracking.

    Background: a single SCITEX_OROCHI_AGENT identity may have multiple
    WebSocket connections at once (today's incident: head-spartan twice).
    Before #144, the first-to-disconnect of N siblings marked the agent
    offline, even though other sessions were still alive. After #144,
    the agent transitions to offline only when the LAST connection drops.
    """

    def setUp(self):
        # Reset registry state per test
        from hub.registry import _agents, _connections

        _agents.clear()
        _connections.clear()

    def test_register_connection_increments_count(self):
        from hub.registry import (
            active_session_count,
            register_agent,
            register_connection,
        )

        register_agent("head-spartan", 1, {})
        self.assertEqual(active_session_count("head-spartan"), 0)

        n = register_connection("head-spartan", "conn-A")
        self.assertEqual(n, 1)
        self.assertEqual(active_session_count("head-spartan"), 1)

        n = register_connection("head-spartan", "conn-B")
        self.assertEqual(n, 2)
        self.assertEqual(active_session_count("head-spartan"), 2)

    def test_register_connection_idempotent(self):
        from hub.registry import active_session_count, register_connection

        register_connection("agent-X", "conn-A")
        register_connection("agent-X", "conn-A")
        register_connection("agent-X", "conn-A")
        self.assertEqual(active_session_count("agent-X"), 1)

    def test_disconnect_one_of_many_keeps_agent_online(self):
        from hub.registry import (
            _agents,
            register_agent,
            register_connection,
            unregister_connection,
        )

        register_agent("head-spartan", 1, {})
        register_connection("head-spartan", "conn-A")
        register_connection("head-spartan", "conn-B")
        self.assertEqual(_agents["head-spartan"]["status"], "online")

        # Disconnect ONE sibling
        remaining = unregister_connection("head-spartan", "conn-A")
        self.assertEqual(remaining, 1)

        # Agent must still be online — symmetric pre-#144 bug regression
        self.assertEqual(_agents["head-spartan"]["status"], "online")

    def test_disconnect_last_marks_offline(self):
        from hub.registry import (
            _agents,
            register_agent,
            register_connection,
            unregister_connection,
        )

        register_agent("head-spartan", 1, {})
        register_connection("head-spartan", "conn-A")

        remaining = unregister_connection("head-spartan", "conn-A")
        self.assertEqual(remaining, 0)
        self.assertEqual(_agents["head-spartan"]["status"], "offline")
        self.assertIn("offline_since", _agents["head-spartan"])

    def test_get_agents_exposes_active_sessions(self):
        from hub.registry import (
            get_agents,
            register_agent,
            register_connection,
        )

        register_agent("head-spartan", 1, {})
        register_connection("head-spartan", "conn-A")
        register_connection("head-spartan", "conn-B")

        agents = get_agents(workspace_id=1)
        # find our agent
        found = next((a for a in agents if a["name"] == "head-spartan"), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["active_sessions"], 2)

    def test_get_agents_active_sessions_zero_when_no_connections(self):
        from hub.registry import get_agents, register_agent

        register_agent("solo-agent", 1, {})
        agents = get_agents(workspace_id=1)
        found = next((a for a in agents if a["name"] == "solo-agent"), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["active_sessions"], 0)

    def test_unregister_agent_force_offline_clears_connections(self):
        """unregister_agent (the legacy/force-offline path) clears connections too."""
        from hub.registry import (
            _agents,
            active_session_count,
            register_agent,
            register_connection,
            unregister_agent,
        )

        register_agent("head-spartan", 1, {})
        register_connection("head-spartan", "conn-A")
        register_connection("head-spartan", "conn-B")
        self.assertEqual(active_session_count("head-spartan"), 2)

        unregister_agent("head-spartan")
        self.assertEqual(active_session_count("head-spartan"), 0)
        self.assertEqual(_agents["head-spartan"]["status"], "offline")

    def test_empty_or_invalid_args_safe(self):
        from hub.registry import register_connection, unregister_connection

        # Empty/None args do not raise + do not mutate state
        self.assertEqual(register_connection("", "conn"), 0)
        self.assertEqual(register_connection("agent", ""), 0)
        self.assertEqual(register_connection(None, None), 0)  # type: ignore[arg-type]
        self.assertEqual(unregister_connection("", "conn"), 0)
        self.assertEqual(unregister_connection("agent", ""), 0)
