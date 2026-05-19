"""Pipeline + shadow-line tests for ``daemon-auditor-haiku`` Stage 1."""

from __future__ import annotations

from scitex_orochi._daemons._auditor_haiku._audit import (
    AuditOutcome,
    audit_message,
    render_shadow_line,
)
from scitex_orochi._daemons._auditor_haiku._rules import AuditVerdict


class TestAuditMessage:
    def test_regex_fail_short_circuits(self) -> None:
        # If regex tripped, we don't waste a Haiku call.
        called = {"haiku": False}

        def haiku(_: str) -> AuditVerdict:
            called["haiku"] = True
            return AuditVerdict.PASS

        outcome = audit_message("This is a blocker", haiku_judge=haiku)
        assert outcome.verdict == AuditVerdict.FAIL
        assert called["haiku"] is False

    def test_regex_clean_calls_haiku(self) -> None:
        called = {"haiku": False}

        def haiku(text: str) -> AuditVerdict:
            called["haiku"] = True
            return AuditVerdict.UNKNOWN

        outcome = audit_message("All tests pass; pushing.", haiku_judge=haiku)
        assert outcome.verdict == AuditVerdict.PASS
        assert called["haiku"] is True

    def test_haiku_can_escalate_to_fail(self) -> None:
        # Stage 1.5 surface: Haiku catches the regex-clean fuzzy violator.
        outcome = audit_message(
            "vague hypothesis menu A/B/C to ywatanabe",
            haiku_judge=lambda _: AuditVerdict.FAIL,
        )
        assert outcome.verdict == AuditVerdict.FAIL

    def test_default_stub_haiku_treats_as_pass(self) -> None:
        # Stage 1 default — never escalates a regex-clean message.
        outcome = audit_message("All tests pass; pushing.")
        assert outcome.verdict == AuditVerdict.PASS


class TestRenderShadowLine:
    def test_fail_line_includes_rule_and_phrase(self) -> None:
        outcome = audit_message("Should I proceed with FR-K?")
        line = render_shadow_line(
            outcome=outcome,
            chat_id="#general",
            msg_id=42,
            user="proj-foo",
            text="Should I proceed with FR-K?",
        )
        assert "verdict=FAIL" in line
        assert "in #general" in line
        assert "msg#42" in line
        assert "by proj-foo" in line
        assert "rule=" in line
        # Both rules tripped, so both ids should be cited.
        assert "zoo-08-banned-phrase-en" in line
        assert "no-internal-codenames" in line

    def test_pass_line_omits_rule_section(self) -> None:
        outcome = audit_message("All tests pass; pushing.")
        line = render_shadow_line(
            outcome=outcome,
            chat_id="#general",
            msg_id=43,
            user="proj-foo",
            text="All tests pass; pushing.",
        )
        assert "verdict=PASS" in line
        assert "rule=" not in line
        assert 'text="All tests pass; pushing."' in line

    def test_long_text_is_truncated(self) -> None:
        long = "x" * 1000
        outcome = AuditOutcome(
            verdict=AuditVerdict.PASS,
            finding=audit_message(long).finding,
        )
        line = render_shadow_line(
            outcome=outcome,
            chat_id="#general",
            msg_id=1,
            user="u",
            text=long,
            max_excerpt_chars=50,
        )
        assert line.endswith('…"')
        # Ellipsis + closing quote, plus the truncated body.
        assert len(line) < 200
