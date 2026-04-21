"""Tests for msg#15538 — 4th LED (ECHO) auto-green on inbound agent message.

Before this change the ``last_nonce_echo_at`` timestamp (which the 4th
liveness LED renders against) was only advanced when the hub→agent
nonce round-trip probe in ``_hub_echo_loop`` completed successfully.
If an agent's MCP-client could not reply to the nonce (e.g. the
sidecar was down, or the agent never implemented the handler) the LED
stayed amber / red even though the agent was clearly alive — it was
sending chat messages every few seconds.

The fix: every authenticated inbound ``message`` frame now also
advances ``last_nonce_echo_at`` (and the sibling ``last_echo_ok_ts``)
via ``mark_echo_alive``. The LED renderer does not need to know which
mechanism wrote the timestamp — either path turns the LED green.

These tests drive the ``handle_agent_message`` coroutine directly with
a fake consumer (mirrors the ``test_reconnect_resubscribe.py`` style)
so the behaviour is exercised at the seam where the new call was added.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.test import TestCase

from hub.models import (
    Channel,
    ChannelMembership,
    Workspace,
)


def _fake_consumer(agent_name: str, workspace_id: int):
    """Minimal AgentConsumer stub capable of driving handle_agent_message.

    Provides the bound attributes the handler reads (agent_name,
    workspace_id, workspace_group, channel_layer, send_json) plus an
    ``_save_message`` AsyncMock so the handler's persistence step
    becomes a no-op. Keeping persistence out of the test isolates the
    registry-side contract.
    """
    from hub.consumers._agent import AgentConsumer

    consumer = AgentConsumer.__new__(AgentConsumer)
    consumer.agent_name = agent_name
    consumer.workspace_id = workspace_id
    consumer.workspace_group = f"workspace_{workspace_id}"
    consumer.channel_name = f"test-ch-{agent_name}"
    consumer._registered = True
    consumer.agent_meta = {"channels": ["#general"]}
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.group_add = AsyncMock()
    consumer.channel_layer.group_discard = AsyncMock()
    consumer.channel_layer.group_send = AsyncMock()
    consumer.send_json = AsyncMock()
    consumer._save_message = AsyncMock(
        return_value={"id": 1, "ts": "2026-04-20T00:00:00+00:00"}
    )
    return consumer


class InboundMessageAdvancesEchoTimestampTest(TestCase):
    """A ``type: "message"`` frame must advance ``last_nonce_echo_at``.

    This is the core contract of msg#15538: any authenticated inbound
    agent message counts as proof of life and should turn the 4th LED
    green, independent of whether the nonce probe ever completes.
    """

    def setUp(self):
        from hub.registry import _agents, _connections, register_agent

        _agents.clear()
        _connections.clear()

        self.ws = Workspace.objects.create(name="echo-auto-ws")
        self.channel = Channel.objects.create(workspace=self.ws, name="#general")

        # ChannelMembership row so the non-member ACL doesn't block the
        # message — the consumer authenticates as ``agent-<name>``.
        self.agent_user = User.objects.create(username="agent-worker-m")
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.channel
        )

        register_agent(
            "worker-m",
            self.ws.id,
            {"agent_id": "worker-m", "machine": "TEST", "role": "worker"},
        )

    def test_inbound_message_sets_last_nonce_echo_at(self):
        """Sending a message frame populates ``last_nonce_echo_at``.

        A freshly-registered agent has no echo fields yet (all None).
        After one ``message`` frame the ISO timestamp must be written
        so the LED renderer flips from grey-pending to green.
        """
        from hub.consumers._agent_message import handle_agent_message
        from hub.registry import _agents

        # Pre-condition: never probed, never messaged.
        self.assertIsNone(_agents["worker-m"].get("last_nonce_echo_at"))
        self.assertIsNone(_agents["worker-m"].get("last_echo_ok_ts"))

        consumer = _fake_consumer("worker-m", self.ws.id)
        async_to_sync(handle_agent_message)(
            consumer,
            {
                "type": "message",
                "payload": {"channel": "#general", "text": "hello"},
            },
        )

        # Both the ISO string (LED renderer) and the unix float (API
        # layer / tooling) must be populated after one inbound message.
        self.assertIsInstance(
            _agents["worker-m"]["last_nonce_echo_at"], str
        )
        self.assertTrue(
            _agents["worker-m"]["last_nonce_echo_at"].endswith("+00:00")
        )
        self.assertIsInstance(
            _agents["worker-m"]["last_echo_ok_ts"], float
        )

    def test_inbound_message_does_not_overwrite_rtt(self):
        """An inbound message has no RTT — must not wipe a real one.

        If ``update_echo_pong`` previously ran (real nonce probe), its
        ``last_echo_rtt_ms`` value must survive subsequent inbound
        messages so the per-agent detail panel keeps showing a real RTT.
        Overwriting with None would make the display misleading.
        """
        from hub.consumers._agent_message import handle_agent_message
        from hub.registry import _agents, update_echo_pong

        update_echo_pong("worker-m", 42.5)
        self.assertEqual(_agents["worker-m"]["last_echo_rtt_ms"], 42.5)
        probed_iso = _agents["worker-m"]["last_nonce_echo_at"]

        consumer = _fake_consumer("worker-m", self.ws.id)
        async_to_sync(handle_agent_message)(
            consumer,
            {
                "type": "message",
                "payload": {"channel": "#general", "text": "later"},
            },
        )

        # RTT preserved, ISO timestamp advanced (or equal — clock
        # resolution on CI might give the same string).
        self.assertEqual(_agents["worker-m"]["last_echo_rtt_ms"], 42.5)
        self.assertGreaterEqual(
            _agents["worker-m"]["last_nonce_echo_at"], probed_iso
        )


class NonceProbeIndependenceTest(TestCase):
    """The timestamp advances even if the nonce probe never completes.

    Confirms the core value proposition of msg#15538: agent-message-only
    is enough to turn the LED green. Exercises the registry seam alone
    so the test is fast and doesn't need an asyncio echo loop.
    """

    def setUp(self):
        from hub.registry import _agents, _connections, register_agent

        _agents.clear()
        _connections.clear()

        self.ws = Workspace.objects.create(name="echo-auto-nopong-ws")
        self.channel = Channel.objects.create(workspace=self.ws, name="#general")
        self.agent_user = User.objects.create(username="agent-lonely-n")
        ChannelMembership.objects.create(
            user=self.agent_user, channel=self.channel
        )
        register_agent(
            "lonely-n",
            self.ws.id,
            {"agent_id": "lonely-n", "machine": "TEST", "role": "worker"},
        )

    def test_mark_echo_alive_alone_populates_led_field(self):
        """``mark_echo_alive`` is sufficient — no nonce pong required."""
        from hub.registry import _agents, mark_echo_alive

        # Never call update_echo_pong — simulate an agent whose MCP
        # sidecar is down or whose echo_pong handler never fires.
        self.assertIsNone(_agents["lonely-n"].get("last_nonce_echo_at"))
        self.assertIsNone(_agents["lonely-n"].get("last_echo_rtt_ms"))

        mark_echo_alive("lonely-n")

        # LED field populated — renderer will flip to green.
        self.assertIsInstance(
            _agents["lonely-n"]["last_nonce_echo_at"], str
        )
        self.assertIsInstance(
            _agents["lonely-n"]["last_echo_ok_ts"], float
        )
        # RTT still absent — nothing to overwrite with and no round-trip
        # was actually measured. The per-agent detail panel renders
        # this as "no RTT recorded yet" rather than "0ms".
        self.assertIsNone(_agents["lonely-n"].get("last_echo_rtt_ms"))

    def test_mark_echo_alive_unknown_agent_is_noop(self):
        """Mirrors ``update_echo_pong`` — unknown agent must not raise."""
        from hub.registry import _agents, mark_echo_alive

        mark_echo_alive("never-registered")
        self.assertNotIn("never-registered", _agents)

    def test_payload_surfaces_field_without_rtt(self):
        """``get_agents`` must surface the inbound-only timestamp.

        Regression guard: the payload layer must include
        ``last_nonce_echo_at`` when it was set via ``mark_echo_alive``
        (not just when ``update_echo_pong`` ran). Otherwise the LED
        never sees the timestamp even though the registry has it.
        """
        from hub.registry import get_agents, mark_echo_alive

        mark_echo_alive("lonely-n")
        payload = next(
            a for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "lonely-n"
        )
        self.assertIsNotNone(payload["last_nonce_echo_at"])
        self.assertIsNone(payload["last_echo_rtt_ms"])
