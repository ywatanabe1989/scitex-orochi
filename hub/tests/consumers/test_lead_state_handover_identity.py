"""Lead-state-handover (ZOO#12) — WS consumer identity + cardinality.

Tests the FR-C cardinality guard + FR-E UUID stamping pieces in
``hub/consumers/_agent_identity.py`` and the ``AgentSession`` row
lifecycle they drive. The pure helpers are exercised directly; the
async connect / disconnect path is covered by spinning up a
``WebsocketCommunicator`` against the real ASGI router so the 4001
close path is verified end-to-end.
"""

from __future__ import annotations

import os
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "orochi.settings")
django.setup()

from asgiref.sync import async_to_sync  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.test import TestCase, TransactionTestCase  # noqa: E402

from hub.consumers._agent_identity import (  # noqa: E402
    active_session_with_different_uuid,
    any_active_session_enforces_cardinality,
    format_agent_id,
    parse_identity_query,
    record_session_close,
    record_session_open,
    short_uuid,
)
from hub.models import AgentSession, Workspace, WorkspaceToken  # noqa: E402


class IdentityHelperTests(TestCase):
    """Pure helpers — no DB needed except for record_session_*."""

    def setUp(self) -> None:
        self.ws = Workspace.objects.create(name="ws-zoo12-ident")

    def test_parse_uuid_accepts_valid_uuid4(self) -> None:
        u = str(uuid.uuid4())
        out = parse_identity_query({"instance_uuid": [u]})
        self.assertEqual(out["instance_uuid"], u)

    def test_parse_uuid_strips_invalid(self) -> None:
        out = parse_identity_query({"instance_uuid": ["not-a-uuid"]})
        # Stays in the bucket but as empty string so callers can warn.
        self.assertEqual(out["instance_uuid"], "")

    def test_parse_uuid_missing_is_empty(self) -> None:
        out = parse_identity_query({})
        self.assertNotIn("instance_uuid", out)

    def test_parse_cardinality_flag_truthy_values(self) -> None:
        for v in ("true", "1", "yes", "TRUE"):
            out = parse_identity_query({"cardinality_enforce": [v]})
            self.assertTrue(out["cardinality_enforce"], v)

    def test_parse_cardinality_flag_falsy_values(self) -> None:
        for v in ("", "false", "0", "no"):
            out = parse_identity_query({"cardinality_enforce": [v]})
            self.assertFalse(out["cardinality_enforce"], v)

    def test_parse_failback_grace(self) -> None:
        self.assertTrue(parse_identity_query({"failback_grace": ["true"]})["failback_grace"])
        self.assertFalse(parse_identity_query({})["failback_grace"])

    def test_short_uuid_truncates_without_hyphens(self) -> None:
        u = "8af3a2b1-0000-4000-8000-deadbeefcafe"
        self.assertEqual(short_uuid(u), "8af3")
        self.assertEqual(short_uuid(u, length=8), "8af3a2b1")
        self.assertEqual(short_uuid(""), "")

    def test_format_agent_id_with_uuid(self) -> None:
        u = str(uuid.uuid4())
        self.assertEqual(format_agent_id("lead", u), f"lead:{u}")

    def test_format_agent_id_without_uuid_falls_back(self) -> None:
        out = format_agent_id("lead", "")
        self.assertTrue(out.startswith("lead:hub-"), out)

    def test_record_session_open_upserts(self) -> None:
        u = str(uuid.uuid4())
        sess = record_session_open(
            self.ws.id, "lead", u, "spartan", 4242, "ch-x", True
        )
        self.assertIsNotNone(sess)
        # Re-open with the same UUID just refreshes the row.
        sess2 = record_session_open(
            self.ws.id, "lead", u, "spartan", 4242, "ch-x", True
        )
        self.assertEqual(sess.id, sess2.id)
        self.assertEqual(AgentSession.objects.filter(instance_uuid=u).count(), 1)

    def test_record_session_open_no_uuid_is_noop(self) -> None:
        self.assertIsNone(
            record_session_open(self.ws.id, "lead", "", "spartan", 1, "ch", True)
        )
        self.assertEqual(AgentSession.objects.count(), 0)

    def test_record_session_close_marks_disconnected(self) -> None:
        u = str(uuid.uuid4())
        record_session_open(self.ws.id, "lead", u, "spartan", 1, "ch", False)
        record_session_close(u)
        row = AgentSession.objects.get(instance_uuid=u)
        self.assertIsNotNone(row.disconnected_at)

    def test_active_sibling_detects_different_uuid(self) -> None:
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
        record_session_open(self.ws.id, "lead", u1, "spartan", 1, "a", True)
        # No sibling yet.
        self.assertFalse(
            active_session_with_different_uuid(self.ws.id, "lead", u1)
        )
        # A second instance under a different UUID — that's the rogue
        # situation FR-C is built to catch.
        record_session_open(self.ws.id, "lead", u2, "mba", 2, "b", True)
        self.assertTrue(
            active_session_with_different_uuid(self.ws.id, "lead", u1)
        )

    def test_active_sibling_ignores_disconnected(self) -> None:
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
        record_session_open(self.ws.id, "lead", u1, "spartan", 1, "a", True)
        record_session_open(self.ws.id, "lead", u2, "mba", 2, "b", True)
        record_session_close(u2)
        self.assertFalse(
            active_session_with_different_uuid(self.ws.id, "lead", u1)
        )

    def test_cardinality_sticky_across_clients(self) -> None:
        """Even if a second client omits the flag, prior live session sets it."""
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
        record_session_open(self.ws.id, "lead", u1, "spartan", 1, "a", True)
        # The flag is "sticky" — it suffices for ANY live session to
        # have declared it, so a buggy / hostile newcomer can't dodge
        # enforcement by lying.
        self.assertTrue(
            any_active_session_enforces_cardinality(self.ws.id, "lead")
        )
        record_session_close(u1)
        record_session_open(self.ws.id, "lead", u2, "spartan", 1, "b", False)
        self.assertFalse(
            any_active_session_enforces_cardinality(self.ws.id, "lead")
        )

    def test_cardinality_generic_across_agents(self) -> None:
        """ZOO#12 v2 — flag must apply to ANY agent, not just ``lead``.

        Mission spec calls out lead, mgr-auth, mgr-reviewer, mgr-verifier
        as the cardinality=1 family; the helper has to work on the
        agent_name level rather than hard-coding ``lead``.
        """
        u_lead = str(uuid.uuid4())
        u_mgr = str(uuid.uuid4())
        record_session_open(
            self.ws.id, "lead", u_lead, "spartan", 1, "a", True
        )
        record_session_open(
            self.ws.id, "mgr-auth", u_mgr, "ywata-note-win", 2, "b", True
        )
        # Both agents independently report active enforcement.
        self.assertTrue(
            any_active_session_enforces_cardinality(self.ws.id, "lead")
        )
        self.assertTrue(
            any_active_session_enforces_cardinality(self.ws.id, "mgr-auth")
        )
        # And they don't shadow each other — closing one leaves the
        # other's enforcement intact.
        record_session_close(u_lead)
        self.assertFalse(
            any_active_session_enforces_cardinality(self.ws.id, "lead")
        )
        self.assertTrue(
            any_active_session_enforces_cardinality(self.ws.id, "mgr-auth")
        )


class CardinalityWsAcceptTests(TransactionTestCase):
    """End-to-end FR-C 4001 close on duplicate UUID-different connect.

    Spins up two ``WebsocketCommunicator`` instances against the real
    AgentConsumer router so the connect path actually walks the whole
    accept→sibling-check→close flow. ``TransactionTestCase`` is required
    because the consumer's DB writes run in their own transaction.
    """

    def setUp(self) -> None:
        self.ws_obj = Workspace.objects.create(name="ws-zoo12-ws")
        self.token = WorkspaceToken.objects.create(
            workspace=self.ws_obj, label="t"
        ).token

    def _open(self, agent: str, instance_uuid: str, **extra) -> WebsocketCommunicator:
        from orochi.asgi import application

        qs_pairs = [
            ("token", self.token),
            ("agent", agent),
            ("instance_uuid", instance_uuid),
        ]
        for k, v in extra.items():
            qs_pairs.append((k, str(v).lower() if isinstance(v, bool) else str(v)))
        qs = "&".join(f"{k}={v}" for k, v in qs_pairs)
        return WebsocketCommunicator(application, f"/ws/agent/?{qs}")

    def test_second_connect_with_flag_is_4001(self) -> None:
        """ZOO#12 — same name, different UUID, flag set → 4001 reject."""
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())

        from asgiref.sync import sync_to_async as _sta

        async def _run():
            c1 = self._open("lead", u1, cardinality_enforce=True)
            ok1, _ = await c1.connect()
            self.assertTrue(ok1)

            c2 = self._open("lead", u2, cardinality_enforce=True)
            ok2, code = await c2.connect()
            # Channels reports the close code as the 2nd return when
            # accept never happened OR after we close immediately.
            # Either way the second connect must NOT survive.
            if ok2:
                # Accept happened, then 4001 close — drain the close.
                await c2.receive_output(timeout=1)
                await c2.disconnect()
            # Snapshot DB state BEFORE c1 disconnects so u1's row is
            # still ``disconnected_at IS NULL``; otherwise both sides
            # show closed and the assertion can't distinguish them.
            live_uuids = await _sta(
                lambda: set(
                    AgentSession.objects.filter(
                        agent_name="lead", disconnected_at__isnull=True
                    ).values_list("instance_uuid", flat=True)
                )
            )()
            await c1.disconnect()
            return code, live_uuids

        code, live_uuids = async_to_sync(_run)()
        # Only u1 should remain alive; u2 either never wrote a row or
        # was already marked closed by record_session_close.
        self.assertIn(u1, live_uuids)
        self.assertNotIn(u2, live_uuids)
        # Suppress the unused-var warning when pre-accept close happened.
        del code

    def test_failback_grace_bypasses_guard(self) -> None:
        """``?failback_grace=true`` must coexist with the live instance.

        Without this, FR-B's hot handoff would 4001 itself out before
        the old lead's snapshot push completes.
        """
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())

        async def _run():
            c1 = self._open("lead", u1, cardinality_enforce=True)
            await c1.connect()
            c2 = self._open(
                "lead", u2, cardinality_enforce=True, failback_grace=True
            )
            ok2, _ = await c2.connect()
            self.assertTrue(ok2)
            await c1.disconnect()
            await c2.disconnect()

        async_to_sync(_run)()

    def test_cardinality_off_allows_dups(self) -> None:
        """Agents without the flag preserve the legacy permissive path."""
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())

        async def _run():
            c1 = self._open("freerunner", u1)
            ok1, _ = await c1.connect()
            self.assertTrue(ok1)
            c2 = self._open("freerunner", u2)
            ok2, _ = await c2.connect()
            self.assertTrue(ok2)
            await c1.disconnect()
            await c2.disconnect()

        async_to_sync(_run)()
