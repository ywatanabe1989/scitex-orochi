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

from django.test import TestCase, TransactionTestCase, override_settings

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
        out = _compose_dispatch_text(
            streak=2, pick=pick, cooldown_s=900, agent_name="head-mba"
        )
        self.assertIn("[auto-dispatch]", out)
        self.assertIn("idle 2 cycles", out)
        self.assertIn("todo#42", out)
        self.assertIn("migrate foo to bar", out)
        self.assertIn("15min", out)

    def test_text_without_pick(self):
        out = _compose_dispatch_text(
            streak=3, pick=None, cooldown_s=900, agent_name="head-mba"
        )
        self.assertIn("[auto-dispatch]", out)
        self.assertIn("no open todo matched", out)

    def test_cooldown_minutes_from_seconds(self):
        out = _compose_dispatch_text(
            streak=2, pick=None, cooldown_s=60, agent_name="head-mba"
        )
        self.assertIn("1min", out)

    def test_text_includes_per_host_gh_command(self):
        """msg#17078 lane A — DM must carry a concrete shell command.

        The head that receives the DM reads the literal command out of
        the message body and can paste it directly. Host is derived
        from the recipient's agent name (``head-<host>`` suffix).
        """
        for host in ("mba", "nas", "spartan", "ywata-note-win"):
            out = _compose_dispatch_text(
                streak=2,
                pick=None,
                cooldown_s=900,
                agent_name=f"head-{host}",
            )
            self.assertIn(
                f"gh issue list --repo ywatanabe1989/scitex-orochi "
                f"--label ready-for-head-{host}",
                out,
                msg=f"Missing tailored gh command for host={host}",
            )

    def test_text_mentions_mgr_todo_fallback(self):
        """msg#17078 lane A — DM must point at mgr-todo as a fallback."""
        out = _compose_dispatch_text(
            streak=2, pick=None, cooldown_s=900, agent_name="head-mba"
        )
        self.assertIn("mgr-todo", out)

    def test_text_fits_in_400_chars(self):
        """msg#17078 lane A — keep body under 400 chars so downstream
        previewers (Web Push 200-char body, dashboard snippet renderer)
        cannot clip the gh command line.
        """
        pick = {"number": 9999, "title": "x" * 200}  # pathological title
        out = _compose_dispatch_text(
            streak=7, pick=pick, cooldown_s=900, agent_name="head-mba"
        )
        self.assertLessEqual(len(out), 400)

    def test_text_legacy_none_agent_name(self):
        """Legacy callers (no agent_name) fall back to ``<host>``."""
        out = _compose_dispatch_text(streak=2, pick=None, cooldown_s=900)
        self.assertIn("ready-for-head-<host>", out)


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

    def _set_orochi_subagent_count(self, count: int) -> None:
        """Mirror what ``set_orochi_subagent_count`` does — write directly."""
        with _lock:
            a = _agents.get(self.agent_name)
            if a is not None:
                a["orochi_subagent_count"] = count

    def test_streak_not_fired_below_threshold(self):
        # Threshold default 2 — a single zero reading must NOT fire.
        self._set_orochi_subagent_count(0)
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
        self._set_orochi_subagent_count(0)
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
        self._set_orochi_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=None):
            check_agent_auto_dispatch(self.agent_name)  # streak=1
            self._set_orochi_subagent_count(2)
            r = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(r["decision"], "reset")
        with _lock:
            self.assertEqual(_agents[self.agent_name].get("idle_streak"), 0)

    def test_cooldown_suppresses_second_fire(self):
        pick = {"number": 17, "title": "X"}
        self._set_orochi_subagent_count(0)
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
        self._set_orochi_subagent_count(0)
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
        self._set_orochi_subagent_count(0)
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
                _agents[worker_name]["orochi_subagent_count"] = 0
            r = check_agent_auto_dispatch(worker_name)
            self.assertIsNone(r)
        finally:
            with _lock:
                _agents.pop(worker_name, None)

    def test_fires_without_pick_still_dms(self):
        # Picker returns None (e.g. gh unauth) — we still fire so the
        # stillness signal reaches the head. The message text mentions
        # no concrete todo.
        self._set_orochi_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=None):
            check_agent_auto_dispatch(self.agent_name)
            r = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(r["decision"], "fired")
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        msgs = list(Message.objects.filter(channel__name=dm_name))
        self.assertEqual(len(msgs), 1)
        self.assertIn("no open todo matched", msgs[0].content)

    # -----------------------------------------------------------------
    # msg#17078 lane A — DM body must be persisted in full (no
    # truncation) in the Message row the hub writes. The user-reported
    # clip ("Pick a hig...") comes from Web Push notification OS
    # behaviour (``hub/push.py`` truncates at 200 chars for the push
    # body only — not the DB row). This asserts the DB side is intact
    # so a healer / dashboard reading back the Message sees the full
    # command line.
    # -----------------------------------------------------------------

    def test_full_dm_body_persisted_in_db(self):
        pick = {"number": 17, "title": "a concrete title"}
        self._set_orochi_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            check_agent_auto_dispatch(self.agent_name)
            check_agent_auto_dispatch(self.agent_name)
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        m = Message.objects.get(channel__name=dm_name)
        # Full body must contain both the host-specific gh command AND
        # the mgr-todo pointer — the two most actionable elements.
        self.assertIn("gh issue list", m.content)
        self.assertIn("ready-for-head-mba", m.content)
        self.assertIn("mgr-todo", m.content)
        # Full body must match what ``_compose_dispatch_text`` produced,
        # byte-for-byte (no DB-side truncation).
        expected = ad._compose_dispatch_text(
            streak=2,
            pick=pick,
            cooldown_s=ad._cooldown_seconds(),
            agent_name=self.agent_name,
        )
        self.assertEqual(m.content, expected)

    # -----------------------------------------------------------------
    # msg#17078 lane A — cooldown must survive a hub restart. We
    # simulate the restart by (1) firing normally, (2) wiping the
    # in-memory registry entry the way a fresh process would see it,
    # (3) re-registering the agent (the normal register_agent flow), and
    # (4) running two more zero-reading ticks. The second tick must
    # return ``cooldown_skip`` because the DB write-through in the
    # first fire recorded ``AgentProfile.last_auto_dispatch_at``.
    # -----------------------------------------------------------------

    def test_cooldown_survives_simulated_hub_restart(self):
        from hub.models import AgentProfile

        pick = {"number": 17, "title": "t"}
        self._set_orochi_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            check_agent_auto_dispatch(self.agent_name)
            r_fired = check_agent_auto_dispatch(self.agent_name)
            self.assertEqual(r_fired["decision"], "fired")

        # DB row written?
        profile = AgentProfile.objects.get(
            workspace=self.ws, name=self.agent_name
        )
        self.assertIsNotNone(profile.last_auto_dispatch_at)

        # Simulate a hub restart — wipe the in-memory registry slot for
        # this agent and re-register. register_agent intentionally does
        # NOT carry over the auto_dispatch_last_fire_ts slot; it must
        # come back from the DB on next lookup.
        with _lock:
            _agents.pop(self.agent_name, None)
        register_agent(self.agent_name, self.ws.id, {"role": "head"})
        self._set_orochi_subagent_count(0)
        # Slot starts empty post-restart.
        with _lock:
            self.assertIsNone(
                _agents[self.agent_name].get("auto_dispatch_last_fire_ts")
            )

        # Two more zero-reading ticks: first increments streak; on the
        # second the hydrate-from-DB step fills in the last-fire
        # timestamp BEFORE the cooldown check, so it returns
        # cooldown_skip instead of re-firing.
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            r1 = check_agent_auto_dispatch(self.agent_name)
            r2 = check_agent_auto_dispatch(self.agent_name)
        self.assertEqual(r1["decision"], "streak_increment")
        self.assertEqual(
            r2["decision"],
            "cooldown_skip",
            msg=(
                "Post-restart second tick must NOT fire again — the "
                "DB-persisted cooldown from the first fire is the "
                "source of truth. If this assertion fails, head-mba "
                "will see ~8 auto-dispatch DMs per 40min in prod."
            ),
        )
        # Still only one DM in the DB.
        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        self.assertEqual(
            Message.objects.filter(channel__name=dm_name).count(), 1
        )

    def test_cooldown_skip_does_not_reset_streak(self):
        """Per spec: cooldown skip leaves streak intact — a subsequent
        zero tick must still evaluate cooldown (not silently re-arm the
        state machine by zeroing the streak).
        """
        pick = {"number": 17, "title": "t"}
        self._set_orochi_subagent_count(0)
        with mock.patch.object(ad, "_run_pick_todo", return_value=pick):
            check_agent_auto_dispatch(self.agent_name)
            check_agent_auto_dispatch(self.agent_name)  # fires, arms cooldown
            # Bring streak back to threshold + keep pushing.
            r1 = check_agent_auto_dispatch(self.agent_name)  # streak=1
            r2 = check_agent_auto_dispatch(self.agent_name)  # streak=2, cooldown_skip
            r3 = check_agent_auto_dispatch(self.agent_name)  # streak=3, cooldown_skip
        self.assertEqual(r1["decision"], "streak_increment")
        self.assertEqual(r2["decision"], "cooldown_skip")
        self.assertEqual(r3["decision"], "cooldown_skip")
        # Streak must not have been reset by cooldown_skip — it stays
        # ≥ threshold, which keeps the gate honest.
        with _lock:
            self.assertGreaterEqual(
                _agents[self.agent_name].get("idle_streak", 0), 2
            )


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
            _agents[self.agent_name]["orochi_subagent_count"] = 0
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
            # Two heartbeats while orochi_subagent_count is 0 → fire.
            with _lock:
                _agents[self.agent_name]["orochi_subagent_count"] = 0
            update_heartbeat(self.agent_name)
            with _lock:
                _agents[self.agent_name]["orochi_subagent_count"] = 0
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


# ---------------------------------------------------------------------------
# 6. Async-context fire path — regression for the SynchronousOnlyOperation
#    seen in prod logs on 2026-04-21: the WS ``handle_heartbeat`` handler
#    runs on the asyncio loop, and Django 4.1+ refuses ORM calls from an
#    async context. Before the fix, every WS-triggered auto-dispatch
#    fire silently lost its DM because ``_post_dispatch_message`` raised
#    inside the broad ``except Exception`` and returned None.
# ---------------------------------------------------------------------------


@override_settings(CHANNEL_LAYERS=_INMEM_CHANNELS)
class AsyncContextFireTest(TransactionTestCase):
    """``check_agent_auto_dispatch`` must dispatch cleanly from asyncio.

    Uses ``TransactionTestCase`` (not ``TestCase``) because the fix
    offloads the ORM work to a worker thread. The thread uses its own
    DB connection; with the default ``TestCase`` transaction wrapping,
    the test connection and the worker connection don't see each
    other's writes — so assertions about persisted rows would always
    fail. TransactionTestCase truncates tables per-test instead, which
    permits the cross-connection visibility this path relies on in
    production.
    """

    def setUp(self):
        self.agent_name = "head-mba"
        with _lock:
            _agents.pop(self.agent_name, None)
        self.ws = Workspace.objects.create(name="auto-dispatch-async-ws")
        register_agent(self.agent_name, self.ws.id, {"role": "head"})
        _reset_auto_dispatch_state_for_tests(self.agent_name)

    def tearDown(self):
        with _lock:
            _agents.pop(self.agent_name, None)

    def test_in_async_context_detection(self):
        """``_in_async_context`` matches the caller's execution context."""
        import asyncio

        self.assertFalse(ad._in_async_context())

        async def _probe():
            return ad._in_async_context()

        self.assertTrue(asyncio.new_event_loop().run_until_complete(_probe()))

    def test_fire_from_async_does_not_raise_sync_only(self):
        """Regression for SynchronousOnlyOperation on WS heartbeat fire path.

        Simulates the WS handler calling ``check_agent_auto_dispatch``
        from an asyncio coroutine. Before the fix, the inline
        ``Workspace.objects.get(...)`` raised ``SynchronousOnlyOperation``;
        after the fix, the ORM work is moved to a worker thread and the
        DM lands exactly like the sync path.
        """
        import asyncio
        import threading

        with _lock:
            _agents[self.agent_name]["orochi_subagent_count"] = 0

        captured: dict = {}

        async def _driver():
            # First heartbeat: streak -> 1 (no fire).
            with mock.patch.object(ad, "_run_pick_todo", return_value=None):
                r1 = ad.check_agent_auto_dispatch(self.agent_name)
                # Second heartbeat: streak -> 2 -> fire.
                r2 = ad.check_agent_auto_dispatch(self.agent_name)
            captured["r1"] = r1
            captured["r2"] = r2

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_driver())
        finally:
            loop.close()

        self.assertEqual(captured["r1"]["decision"], "streak_increment")
        self.assertEqual(captured["r2"]["decision"], "fired")

        # The DM Message is written by the worker thread launched from
        # the async context — join any live ones so the assert is
        # deterministic. Name prefix matches ``_dispatch_in_thread``.
        for t in list(threading.enumerate()):
            if t.name.startswith("auto-dispatch-"):
                t.join(timeout=5.0)

        dm_name = _canonical_auto_dispatch_dm_name(self.agent_name)
        msgs = list(Message.objects.filter(channel__name=dm_name))
        self.assertEqual(
            len(msgs),
            1,
            msg=(
                "WS-context fire must still persist exactly one "
                "auto-dispatch DM (SynchronousOnlyOperation regression)."
            ),
        )
        self.assertEqual(msgs[0].metadata.get("kind"), "auto-dispatch")
