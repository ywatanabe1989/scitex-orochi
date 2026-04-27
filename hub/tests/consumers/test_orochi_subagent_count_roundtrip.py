"""End-to-end lifecycle tests for ``orochi_subagent_count`` on the hub side.

Exercises the full path a heartbeat frame takes through
``handle_heartbeat`` → ``set_orochi_subagent_count`` → in-memory registry →
``get_agents`` payload. Both Layer 1 (server-side auto-dispatch) and
Layer 2 (hungry-signal DM, PR #329) depend on the hub's in-memory
``orochi_subagent_count`` field reflecting reality within one heartbeat of the
pane change — if the hub undercounts, auto-dispatch fires while the
head is actually busy; if it overcounts, the head stays hungry forever.

Scope: the WS heartbeat seam (``handle_heartbeat``) plus the direct
registry setter (``set_orochi_subagent_count``). The parser-side lifecycle
that produces the field is covered by
``tests/test_orochi_subagent_count_lifecycle.py``. The REST register path
(``/api/agents/register/``) round-trip is already covered by
``hub/tests/views/api/test_agents_register.py::test_register_persists_orochi_subagent_count``;
this module focuses on the WebSocket consumer path instead.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from asgiref.sync import async_to_sync
from django.test import TestCase

from hub.models import Workspace


def _fake_consumer(agent_name: str, workspace_id: int):
    """Minimal AgentConsumer stub capable of driving handle_heartbeat.

    Mirrors the stub in ``test_agent_message_echo.py`` — bound attributes
    the handler reads (agent_name, workspace_id, workspace_group,
    channel_layer) plus an async-mocked ``send_json``. Persistence paths
    are not involved in the heartbeat handler, so no ``_save_message``
    stub is needed.
    """
    from hub.consumers._agent import AgentConsumer

    consumer = AgentConsumer.__new__(AgentConsumer)
    consumer.agent_name = agent_name
    consumer.workspace_id = workspace_id
    consumer.workspace_group = f"workspace_{workspace_id}"
    consumer.channel_name = f"test-ch-{agent_name}"
    consumer._registered = True
    consumer.agent_meta = {"channels": []}
    consumer.channel_layer = MagicMock()
    consumer.channel_layer.group_send = AsyncMock()
    consumer.send_json = AsyncMock()
    return consumer


class SubagentCountRoundtripTest(TestCase):
    """Heartbeat payload → registry round-trip across the full lifecycle.

    Each test drives ``handle_heartbeat`` with a synthesised payload and
    asserts the in-memory registry entry reflects the advertised count.
    The lifecycle covered matches the parser-side parametric list:
    spawn (0→N), partial completion (N→M<N), full completion (N→0),
    and the stale-frame race (hub records whatever arrives; eventually
    consistent via the next heartbeat).
    """

    def setUp(self):
        from hub.registry import _agents, _connections, register_agent

        _agents.clear()
        _connections.clear()
        self.ws = Workspace.objects.create(name="subagent-count-roundtrip-ws")

        register_agent(
            "head-test",
            self.ws.id,
            {"agent_id": "head-test", "machine": "TEST", "role": "head"},
        )

    def _send_heartbeat(self, orochi_subagent_count):
        """Drive one heartbeat frame through ``handle_heartbeat``.

        The helper builds a payload whose only meaningful field is
        ``orochi_subagent_count`` (the metrics block is fine as ``None``s —
        ``handle_heartbeat`` just passes them through verbatim).
        """
        from hub.consumers._agent_handlers import handle_heartbeat

        consumer = _fake_consumer("head-test", self.ws.id)
        frame = {
            "type": "heartbeat",
            "payload": {
                "orochi_subagent_count": orochi_subagent_count,
            },
        }
        async_to_sync(handle_heartbeat)(consumer, frame)

    # ------------------------------------------------------------------
    # Cold start — no heartbeat yet. The prev-preserve register_agent
    # path defaults orochi_subagent_count to 0 so the field exists from the
    # first call.
    # ------------------------------------------------------------------

    def test_cold_start_defaults_to_zero(self):
        """A freshly-registered agent has ``orochi_subagent_count == 0``.

        No heartbeat has arrived yet — the field must still be present
        and equal to zero so auto-dispatch / hungry-signal doesn't
        crash on a KeyError or treat "unknown" as "busy".
        """
        from hub.registry import _agents

        self.assertEqual(_agents["head-test"].get("orochi_subagent_count", 0), 0)

    # ------------------------------------------------------------------
    # Layer 1 — spawn events (0 → N).
    # ------------------------------------------------------------------

    def test_heartbeat_with_one_subagent_records_one(self):
        """One Agent in flight → registry ``orochi_subagent_count == 1``."""
        from hub.registry import _agents

        self._send_heartbeat(1)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 1)

    def test_heartbeat_with_three_orochi_subagents_records_three(self):
        """Three Agents in flight → registry ``orochi_subagent_count == 3``."""
        from hub.registry import _agents

        self._send_heartbeat(3)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 3)

    def test_heartbeat_with_five_orochi_subagents_records_five(self):
        """Large batches carry through unchanged."""
        from hub.registry import _agents

        self._send_heartbeat(5)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 5)

    # ------------------------------------------------------------------
    # Full-lifecycle transitions. The sequence (0 → 3 → 2 → 0) is the
    # critical path — if any of these steps fail to update the registry,
    # the dependent features misfire.
    # ------------------------------------------------------------------

    def test_full_spawn_to_zero_lifecycle(self):
        """Full lifecycle: 0 → 1 → 0 → 3 → 2 → 0.

        Each transition is an independent heartbeat. The registry must
        reflect each step without interpolation, clamping, or memory of
        the previous value.
        """
        from hub.registry import _agents

        # Cold start: 0 (default)
        self.assertEqual(_agents["head-test"].get("orochi_subagent_count", 0), 0)

        # Spawn 1
        self._send_heartbeat(1)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 1)

        # That 1 finishes — back to idle
        self._send_heartbeat(0)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 0)

        # Fresh batch of 3
        self._send_heartbeat(3)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 3)

        # Partial completion: 1 of 3 returns, 2 still live
        self._send_heartbeat(2)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 2)

        # Full completion — idle again, hungry-signal counter can start
        self._send_heartbeat(0)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 0)

    def test_partial_completion_decrement(self):
        """3 spawned, 1 finishes → hub tracks 2 (not stuck at 3)."""
        from hub.registry import _agents

        self._send_heartbeat(3)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 3)

        # One of the three completes — the pane now shows
        # "2 local agents still running" and the parser returns 2.
        self._send_heartbeat(2)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 2)

    def test_completion_clears_to_zero(self):
        """Running → idle transition: hub reflects the zero within one tick."""
        from hub.registry import _agents

        self._send_heartbeat(4)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 4)

        self._send_heartbeat(0)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 0)

    # ------------------------------------------------------------------
    # Race / stale-frame semantics. Heartbeat is eventually consistent —
    # whatever the parser sampled is what the hub records, and the next
    # heartbeat corrects it.
    # ------------------------------------------------------------------

    def test_stale_frame_records_stale_count(self):
        """If the parser sampled a stale "2 local agents running" frame
        while the batch had actually finished, the hub records 2. The
        next heartbeat (post-redraw → 0) corrects it. Eventually
        consistent; pin that so a future change to "smooth" transitions
        doesn't silently swallow a stale frame.
        """
        from hub.registry import _agents

        # Parser saw a stale status-line frame → hub records 2.
        self._send_heartbeat(2)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 2)

        # Next heartbeat arrives with the correct post-redraw count.
        self._send_heartbeat(0)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 0)

    def test_overshoot_then_correct(self):
        """Heartbeat arrives with 5 (bogus / transient spike), next
        heartbeat corrects to 2. Hub honours the latest value.
        """
        from hub.registry import _agents

        self._send_heartbeat(5)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 5)

        self._send_heartbeat(2)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 2)

    # ------------------------------------------------------------------
    # Payload surface — get_agents must expose the round-tripped field
    # so the Agents-tab / hungry-signal reader sees the live value.
    # ------------------------------------------------------------------

    def test_get_agents_surfaces_current_count(self):
        """The payload layer reflects the registry's current count.

        Regression guard: without this, the dashboard + the server-side
        auto-dispatch reader could see a stale value even though the
        in-memory dict has the fresh one.
        """
        from hub.registry import get_agents

        self._send_heartbeat(2)
        payload = next(
            a
            for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "head-test"
        )
        self.assertEqual(payload["orochi_subagent_count"], 2)

        self._send_heartbeat(0)
        payload = next(
            a
            for a in get_agents(workspace_id=self.ws.id)
            if a["name"] == "head-test"
        )
        self.assertEqual(payload["orochi_subagent_count"], 0)

    # ------------------------------------------------------------------
    # Defensive input handling — the WS heartbeat handler must not
    # blow up on missing / malformed / negative counts. Pins the
    # hub's "best-effort int, floor at 0" contract.
    # ------------------------------------------------------------------

    def test_heartbeat_without_orochi_subagent_count_preserves_prior(self):
        """Heartbeat omitting ``orochi_subagent_count`` leaves the registry's
        current value unchanged — the field is optional on the wire
        and a heartbeat that doesn't know it should not clobber a
        previously-recorded 3 back to 0.
        """
        from hub.consumers._agent_handlers import handle_heartbeat
        from hub.registry import _agents

        # Plant a known count.
        self._send_heartbeat(3)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 3)

        # Send a heartbeat that omits ``orochi_subagent_count``.
        consumer = _fake_consumer("head-test", self.ws.id)
        async_to_sync(handle_heartbeat)(
            consumer, {"type": "heartbeat", "payload": {}}
        )
        # Prior value preserved.
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 3)

    def test_heartbeat_with_negative_count_floors_to_zero(self):
        """A negative count (never legal, but pathological clients
        sometimes send one) is floored to 0 — matches the contract in
        ``set_orochi_subagent_count`` itself.
        """
        from hub.registry import _agents

        self._send_heartbeat(-1)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 0)

        self._send_heartbeat(-99)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 0)

    def test_heartbeat_with_non_int_count_is_ignored(self):
        """Malformed ``orochi_subagent_count`` (non-coercible string) is
        swallowed — the handler catches the ValueError and leaves the
        prior value in place. Contract: one bad frame never corrupts
        the registry.
        """
        from hub.consumers._agent_handlers import handle_heartbeat
        from hub.registry import _agents

        # Plant a known count.
        self._send_heartbeat(2)
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 2)

        # Send a heartbeat with a garbage count.
        consumer = _fake_consumer("head-test", self.ws.id)
        async_to_sync(handle_heartbeat)(
            consumer,
            {
                "type": "heartbeat",
                "payload": {"orochi_subagent_count": "banana"},
            },
        )
        # Prior value preserved, no exception propagated.
        self.assertEqual(_agents["head-test"]["orochi_subagent_count"], 2)


class SetSubagentCountDirectTest(TestCase):
    """Direct tests of ``set_orochi_subagent_count`` — the registry primitive.

    The WS handler and the REST ``/api/agents/register/`` endpoint
    both funnel through this setter, so pinning its behaviour guards
    both call-sites at once.
    """

    def setUp(self):
        from hub.registry import _agents, _connections, register_agent

        _agents.clear()
        _connections.clear()
        self.ws = Workspace.objects.create(name="set-subagent-count-ws")
        register_agent(
            "head-x",
            self.ws.id,
            {"agent_id": "head-x", "machine": "TEST", "role": "head"},
        )

    def test_set_monotonic_sequence(self):
        """0 → 1 → 3 → 2 → 0 round-trip."""
        from hub.registry import _agents, set_orochi_subagent_count

        for value in (0, 1, 3, 2, 0):
            set_orochi_subagent_count("head-x", value)
            self.assertEqual(_agents["head-x"]["orochi_subagent_count"], value)

    def test_set_floors_negative_at_zero(self):
        from hub.registry import _agents, set_orochi_subagent_count

        set_orochi_subagent_count("head-x", -5)
        self.assertEqual(_agents["head-x"]["orochi_subagent_count"], 0)

    def test_set_accepts_none_as_zero(self):
        """``None`` maps to 0 per the ``int(count or 0)`` contract."""
        from hub.registry import _agents, set_orochi_subagent_count

        # Plant a non-zero first.
        set_orochi_subagent_count("head-x", 4)
        self.assertEqual(_agents["head-x"]["orochi_subagent_count"], 4)

        set_orochi_subagent_count("head-x", None)  # type: ignore[arg-type]
        self.assertEqual(_agents["head-x"]["orochi_subagent_count"], 0)

    def test_set_on_unknown_agent_is_noop(self):
        """Unknown agent name is a silent no-op — the setter must not
        create phantom registry rows. Mirrors ``update_echo_pong``'s
        defensive behaviour.
        """
        from hub.registry import _agents, set_orochi_subagent_count

        set_orochi_subagent_count("never-registered", 7)
        self.assertNotIn("never-registered", _agents)
