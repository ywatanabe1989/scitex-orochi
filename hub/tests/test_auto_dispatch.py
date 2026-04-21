"""Tests for server-side auto-dispatch (msg#16388, Layer 1 redesign).

Covers three layers:

  1. :func:`_update_streak_locked` + :func:`_cooldown_active_locked` —
     pure streak/cooldown state primitives.
  2. :func:`_compose_dispatch_text` + :func:`_canonical_auto_dispatch_dm_name` —
     message shape + DM channel naming.
  3. :func:`check_agent_auto_dispatch` — end-to-end: streak reaches
     threshold, DM channel lazy-created, auto-dispatch Message row
     inserted with ``metadata["kind"]="auto-dispatch"``, cooldown arms.

Todo selection is mocked in these tests — the real helper hits ``gh``
and is exercised in ``test_pick_todo.py`` (PR #320). Here we assert
the fan-out path, not the gh-backed pick.
"""

from __future__ import annotations

import time
from unittest import mock

from django.test import TestCase, override_settings

from hub import auto_dispatch as ad
from hub.auto_dispatch import (
    AUTO_DISPATCH_SENDER,
    LANE_FOR_HOST,
    _canonical_auto_dispatch_dm_name,
    _compose_dispatch_text,
    _cooldown_active_locked,
    _cooldown_seconds,
    _head_host_from_name,
    _reset_auto_dispatch_state_for_tests,
    _streak_threshold,
    _update_streak_locked,
    check_agent_auto_dispatch,
)
from hub.models import Channel, Message, Workspace
from hub.registry import _agents, _lock, register_agent, update_heartbeat

_INMEM_CHANNELS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}


# ---------------------------------------------------------------------------
# 1. Pure primitives
# ---------------------------------------------------------------------------


class StreakPrimitivesTest(TestCase):
    """``_update_streak_locked`` and ``_cooldown_active_locked``."""

    def test_zero_reading_increments_streak(self):
        agent = {}
        self.assertEqual(_update_streak_locked(agent, 0), 1)
        self.assertEqual(_update_streak_locked(agent, 0), 2)
        self.assertEqual(_update_streak_locked(agent, 0), 3)

    def test_nonzero_reading_resets_streak(self):
        agent = {"idle_streak": 5}
        self.assertEqual(_update_streak_locked(agent, 2), 0)
        self.assertEqual(agent["idle_streak"], 0)

    def test_streak_survives_on_missing_prev(self):
        # First-ever observation with no prev streak stored: treat as 0.
        agent = {}
        self.assertEqual(_update_streak_locked(agent, 0), 1)

    def test_cooldown_inactive_when_never_fired(self):
        agent = {}
        self.assertFalse(_cooldown_active_locked(agent, now=1000.0, cooldown_s=900))

    def test_cooldown_active_inside_window(self):
        agent = {"auto_dispatch_last_fire_ts": 1000.0}
        # 500s elapsed, cooldown 900 — still active.
        self.assertTrue(_cooldown_active_locked(agent, now=1500.0, cooldown_s=900))

    def test_cooldown_expired_outside_window(self):
        agent = {"auto_dispatch_last_fire_ts": 1000.0}
        # 901s elapsed — expired.
        self.assertFalse(_cooldown_active_locked(agent, now=1901.0, cooldown_s=900))

    def test_cooldown_bad_ts_treated_as_inactive(self):
        agent = {"auto_dispatch_last_fire_ts": "garbage"}
        self.assertFalse(_cooldown_active_locked(agent, now=1000.0, cooldown_s=900))


class HeadHostExtractTest(TestCase):
    def test_head_host(self):
        self.assertEqual(_head_host_from_name("head-mba"), "mba")
        self.assertEqual(_head_host_from_name("head-ywata-note-win"), "ywata-note-win")

    def test_non_head_returns_none(self):
        self.assertIsNone(_head_host_from_name("worker-foo"))
        self.assertIsNone(_head_host_from_name("healer-mba"))
        self.assertIsNone(_head_host_from_name(""))
        self.assertIsNone(_head_host_from_name("head-"))


class LaneMappingTest(TestCase):
    """Spec lane-to-label mapping (lead msg#15975, reaffirmed msg#16388)."""

    def test_all_four_heads_mapped(self):
        self.assertEqual(LANE_FOR_HOST["mba"], "infrastructure")
        self.assertEqual(LANE_FOR_HOST["nas"], "hub-admin")
        self.assertEqual(LANE_FOR_HOST["spartan"], "specialized-domain")
        self.assertEqual(LANE_FOR_HOST["ywata-note-win"], "specialized-wsl-access")


class EnvConfigTest(TestCase):
    def test_streak_threshold_default(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            if "SCITEX_AUTO_DISPATCH_STREAK_THRESHOLD" in __import__("os").environ:
                del __import__("os").environ["SCITEX_AUTO_DISPATCH_STREAK_THRESHOLD"]
            self.assertEqual(_streak_threshold(), 2)

    def test_streak_threshold_env_override(self):
        with mock.patch.dict("os.environ", {"SCITEX_AUTO_DISPATCH_STREAK_THRESHOLD": "5"}):
            self.assertEqual(_streak_threshold(), 5)

    def test_streak_threshold_min_one(self):
        with mock.patch.dict("os.environ", {"SCITEX_AUTO_DISPATCH_STREAK_THRESHOLD": "0"}):
            # ``max(..., 1)`` floors the threshold at 1 so the state
            # machine can't be accidentally disabled by a bad config.
            self.assertEqual(_streak_threshold(), 1)

    def test_cooldown_default(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            if "SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS" in __import__("os").environ:
                del __import__("os").environ["SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS"]
            self.assertEqual(_cooldown_seconds(), 900)

    def test_cooldown_env_override(self):
        with mock.patch.dict("os.environ", {"SCITEX_AUTO_DISPATCH_COOLDOWN_SECONDS": "120"}):
            self.assertEqual(_cooldown_seconds(), 120)


# ---------------------------------------------------------------------------
# 2. Message composition + DM naming
# ---------------------------------------------------------------------------


class ComposeTextTest(TestCase):
    def test_text_with_pick(self):
        pick = {"number": 42, "title": "migrate foo to bar"}
        out = _compose_dispatch_text(streak=2, pick=pick, cooldown_s=900)
        self.assertIn("[auto-dispatch]", out)
        self.assertIn("idle for 2 cycles", out)
        self.assertIn("todo#42", out)
        self.assertIn("migrate foo to bar", out)
        self.assertIn("15min", out)

    def test_text_without_pick(self):
        out = _compose_dispatch_text(streak=3, pick=None, cooldown_s=900)
        self.assertIn("[auto-dispatch]", out)
        self.assertIn("no open todo matched", out)

    def test_cooldown_minutes_from_seconds(self):
        out = _compose_dispatch_text(streak=2, pick=None, cooldown_s=60)
        self.assertIn("1min", out)


class DmNameTest(TestCase):
    def test_canonical_dm_name_for_head(self):
        # Sorted lexically: ``agent:head-mba`` < ``human:orochi-auto-dispatch``.
        name = _canonical_auto_dispatch_dm_name("head-mba")
        self.assertEqual(name, "dm:agent:head-mba|human:orochi-auto-dispatch")


# ---------------------------------------------------------------------------
# 3. End-to-end via check_agent_auto_dispatch
# ---------------------------------------------------------------------------


@override_settings(CHANNEL_LAYERS=_INMEM_CHANNELS)
class CheckAgentAutoDispatchTest(TestCase):
    """Integration: heartbeat → streak → fire → DM message row."""

    def setUp(self):
        # Fresh registry slot for head-mba.
        self.agent_name = "head-mba"
        with _lock:
            _agents.pop(self.agent_name, None)
        self.ws = Workspace.objects.create(name="auto-dispatch-e2e-ws")
        register_agent(self.agent_name, self.ws.id, {"role": "head"})
        _reset_auto_dispatch_state_for_tests(self.agent_name)

    def tearDown(self):
        with _lock:
            _agents.pop(self.agent_name, None)

    def _set_subagent_count(self, count: int) -> None:
        """Mirror what ``set_subagent_count`` does — write directly."""
        with _lock:
            a = _agents.get(self.agent_name)
            if a is not None:
                a["subagent_count"] = count

    def test_streak_not_fired_below_threshold(self):
        # Threshold default 2 — a single zero reading must NOT fire.
        self._set_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=None) as pick_m:
            res = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(res["decision"], "streak_increment")
        self.assertEqual(res["streak"], 1)
        pick_m.assert_not_called()
        # No DM message yet.
        self.assertFalse(
            Message.objects.filter(
                channel__name=_canonical_auto_dispatch_dm_name(self.agent_name)
            ).exists()
        )

    def test_fires_on_second_consecutive_zero(self):
        pick = {"number": 17, "title": "clean up stale fixtures"}
        self._set_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            r1 = check_agent_auto_dispatch(self.agent_name)
            self.assertEqual(r1["decision"], "streak_increment")
            r2 = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(r2["decision"], "fired")
        self.assertEqual(r2["streak"], 2)
        self.assertEqual(r2["pick"], pick)

        # DM channel must exist with kind=DM.
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        ch = Channel.objects.get(workspace=self.ws, name=dm_name)
        self.assertEqual(ch.kind, Channel.KIND_DM)

        # One Message with the auto-dispatch metadata.
        msgs = list(Message.objects.filter(channel=ch))
        self.assertEqual(len(msgs), 1)
        m = msgs[0]
        self.assertEqual(m.sender, AUTO_DISPATCH_SENDER)
        self.assertEqual(m.metadata.get("kind"), "auto-dispatch")
        self.assertEqual(m.metadata.get("agent"), self.agent_name)
        self.assertEqual(m.metadata.get("lane"), "infrastructure")
        self.assertEqual(m.metadata.get("todo_number"), 17)
        self.assertIn("todo#17", m.content)

    def test_nonzero_resets_streak(self):
        self._set_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=None):
            check_agent_auto_dispatch(self.agent_name)  # streak=1
            self._set_subagent_count(2)
            r = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(r["decision"], "reset")
        with _lock:
            self.assertEqual(_agents[self.agent_name].get("idle_streak"), 0)

    def test_cooldown_suppresses_second_fire(self):
        pick = {"number": 17, "title": "X"}
        self._set_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            # Two consecutive zeros → fire.
            check_agent_auto_dispatch(self.agent_name)
            r2 = check_agent_auto_dispatch(self.agent_name)
            self.assertEqual(r2["decision"], "fired")

            # Keep pushing zeros — streak re-accumulates from 0 (reset
            # post-fire), but the cooldown gate blocks any new fire.
            # Need another two increments to reach threshold.
            check_agent_auto_dispatch(self.agent_name)  # streak=1
            r_cool = check_agent_auto_dispatch(self.agent_name)  # streak=2
        self.assertEqual(r_cool["decision"], "cooldown_skip")
        # Only one DM still.
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        ch = Channel.objects.get(workspace=self.ws, name=dm_name)
        self.assertEqual(Message.objects.filter(channel=ch).count(), 1)

    def test_cooldown_expires_and_refires(self):
        pick = {"number": 17, "title": "X"}
        self._set_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            check_agent_auto_dispatch(self.agent_name)
            check_agent_auto_dispatch(self.agent_name)  # fires, arms cooldown

            # Artificially expire the cooldown by rewinding last-fire ts.
            with _lock:
                _agents[self.agent_name]["auto_dispatch_last_fire_ts"] = (
                    time.time() - 10_000
                )

            # Re-build streak then fire again.
            check_agent_auto_dispatch(self.agent_name)  # streak=1
            r = check_agent_auto_dispatch(self.agent_name)  # streak=2 → fire
        self.assertEqual(r["decision"], "fired")
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        ch = Channel.objects.get(workspace=self.ws, name=dm_name)
        self.assertEqual(Message.objects.filter(channel=ch).count(), 2)

    def test_kill_switch_disables(self):
        self._set_subagent_count(0)
        with mock.patch.dict(
            "os.environ", {"SCITEX_AUTO_DISPATCH_DISABLED": "1"}
        ), mock.patch.object(ad, "_run_pick_todo", return_value=None) as pick_m:
            r1 = check_agent_auto_dispatch(self.agent_name)
            r2 = check_agent_auto_dispatch(self.agent_name)
        self.assertIsNone(r1)
        self.assertIsNone(r2)
        pick_m.assert_not_called()

    def test_non_head_agent_skipped(self):
        # Register a non-head and verify the auto-dispatch is a no-op.
        worker_name = "worker-bee"
        with _lock:
            _agents.pop(worker_name, None)
        register_agent(worker_name, self.ws.id, {"role": "worker"})
        try:
            with _lock:
                _agents[worker_name]["subagent_count"] = 0
            r = check_agent_auto_dispatch(worker_name)
            self.assertIsNone(r)
        finally:
            with _lock:
                _agents.pop(worker_name, None)

    def test_fires_without_pick_still_dms(self):
        # Picker returns None (e.g. gh unauth) — we still fire so the
        # stillness signal reaches the head. The message text mentions
        # no concrete todo.
        self._set_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=None):
            check_agent_auto_dispatch(self.agent_name)
            r = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(r["decision"], "fired")
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        msgs = list(Message.objects.filter(channel__name=dm_name))
        self.assertEqual(len(msgs), 1)
        self.assertIn("no open todo matched", msgs[0].content)


# ---------------------------------------------------------------------------
# 4. Heartbeat integration
# ---------------------------------------------------------------------------


@override_settings(CHANNEL_LAYERS=_INMEM_CHANNELS)
class HeartbeatIntegrationTest(TestCase):
    """Wire test: ``update_heartbeat`` calls through to auto-dispatch."""

    def setUp(self):
        self.agent_name = "head-mba"
        with _lock:
            _agents.pop(self.agent_name, None)
        self.ws = Workspace.objects.create(name="auto-dispatch-hb-ws")
        register_agent(self.agent_name, self.ws.id, {"role": "head"})
        _reset_auto_dispatch_state_for_tests(self.agent_name)

    def tearDown(self):
        with _lock:
            _agents.pop(self.agent_name, None)

    def test_heartbeat_invokes_auto_dispatch(self):
        with _lock:
            _agents[self.agent_name]["subagent_count"] = 0
        with mock.patch.object(
            ad, "check_agent_auto_dispatch", wraps=ad.check_agent_auto_dispatch
        ) as spy:
            update_heartbeat(self.agent_name)
            update_heartbeat(self.agent_name)
        # The hook fires once per heartbeat.
        self.assertEqual(spy.call_count, 2)

    def test_two_heartbeats_with_zero_trigger_fire(self):
        with mock.patch.object(
            ad, "_run_pick_todo", return_value={"number": 9, "title": "fix foo"}
        ):
            # Two heartbeats while subagent_count is 0 → fire.
            with _lock:
                _agents[self.agent_name]["subagent_count"] = 0
            update_heartbeat(self.agent_name)
            with _lock:
                _agents[self.agent_name]["subagent_count"] = 0
            update_heartbeat(self.agent_name)
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        msgs = list(Message.objects.filter(channel__name=dm_name))
        self.assertEqual(len(msgs), 1)


# ---------------------------------------------------------------------------
# 5. _run_pick_todo — subprocess contract (no network)
# ---------------------------------------------------------------------------


class RunPickTodoContractTest(TestCase):
    """``_run_pick_todo`` must never raise and must return ``None`` on junk."""

    def test_timeout_returns_none(self):
        import subprocess as _sp

        # ``_run_pick_todo`` only catches specific, expected subprocess
        # failure modes (Timeout / FileNotFoundError / OSError); other
        # exceptions propagate to the caller (``check_agent_auto_dispatch``
        # wraps the whole thing in its own broad except). We pin the
        # contract for the timeout path here.
        with mock.patch("subprocess.run", side_effect=_sp.TimeoutExpired(cmd="x", timeout=1)), \
             mock.patch.object(ad, "_pick_helper_path", return_value=__import__("pathlib").Path(__file__)):
            self.assertIsNone(ad._run_pick_todo("infrastructure"))
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("no gh")), \
             mock.patch.object(ad, "_pick_helper_path", return_value=__import__("pathlib").Path(__file__)):
            self.assertIsNone(ad._run_pick_todo("infrastructure"))

    def test_null_stdout_returns_none(self):
        proc = mock.MagicMock(stdout="null\n", returncode=0)
        with mock.patch("subprocess.run", return_value=proc), mock.patch.object(
            ad, "_pick_helper_path", return_value=__import__("pathlib").Path(__file__)
        ):
            self.assertIsNone(ad._run_pick_todo("infrastructure"))

    def test_malformed_json_returns_none(self):
        proc = mock.MagicMock(stdout="not-json", returncode=0)
        with mock.patch("subprocess.run", return_value=proc), mock.patch.object(
            ad, "_pick_helper_path", return_value=__import__("pathlib").Path(__file__)
        ):
            self.assertIsNone(ad._run_pick_todo("infrastructure"))

    def test_missing_helper_returns_none(self):
        with mock.patch.object(ad, "_pick_helper_path", return_value=None):
            self.assertIsNone(ad._run_pick_todo("infrastructure"))

    def test_well_formed_dict_passes_through(self):
        proc = mock.MagicMock(
            stdout='{"number":7,"title":"fix it","labels":[],"reason":"x"}\n',
            returncode=0,
        )
        with mock.patch("subprocess.run", return_value=proc), mock.patch.object(
            ad, "_pick_helper_path", return_value=__import__("pathlib").Path(__file__)
        ):
            got = ad._run_pick_todo("infrastructure")
        self.assertEqual(got["number"], 7)
        self.assertEqual(got["title"], "fix it")
