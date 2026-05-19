"""Regex layer tests for ``daemon-auditor-haiku`` (FR-M Stage 1).

Acceptance pin (lead msg#23289):
  * Synthetic message containing "blocker" → ❌ react + reply citing ZOO#08
  * Synthetic message containing "FR-K" without plain-language → ❌ react
  * Clean message → ⭕️ react

The Stage 1 implementation only posts to ``#audit-shadow`` (no origin
react/reply yet), so these tests pin the *verdict* and *citation* —
the reaction-layer behaviour is a Stage 2 concern.
"""

from __future__ import annotations

import re

from scitex_orochi._daemons._auditor_haiku._rules import (
    AuditVerdict,
    Rule,
    apply_regex_rules,
    default_rules,
)


def _verdict(text: str) -> AuditVerdict:
    return apply_regex_rules(text).verdict


def _hit_rules(text: str) -> set[str]:
    return {h.rule_id for h in apply_regex_rules(text).hits}


class TestZooBannedPhrasesEN:
    def test_blocker_trips_zoo_08(self) -> None:
        finding = apply_regex_rules("This is a blocker for the deploy.")
        assert finding.verdict == AuditVerdict.FAIL
        assert {h.rule_id for h in finding.hits} == {"zoo-08-banned-phrase-en"}
        assert "ZOO#08" in finding.hits[0].citation

    def test_blocked_on_ywatanabe_trips(self) -> None:
        assert _verdict("we're blocked on ywatanabe for sign-off") == AuditVerdict.FAIL

    def test_should_i_trips(self) -> None:
        assert _verdict("Should I proceed with the migration?") == AuditVerdict.FAIL

    def test_may_i_trips(self) -> None:
        assert _verdict("May I open the PR now?") == AuditVerdict.FAIL

    def test_unrelated_use_of_block_does_not_trip(self) -> None:
        # "block" without "blocker" is not the banned phrase. Word-boundary
        # \b in the regex prevents this from being a substring match.
        assert _verdict("The function uses a try/except block.") == AuditVerdict.UNKNOWN


class TestZooBannedPhrasesJP:
    def test_ok_desuka_trips(self) -> None:
        finding = apply_regex_rules("OK ですか？進めて良いですか")
        assert finding.verdict == AuditVerdict.FAIL
        assert "zoo-08-banned-phrase-jp" in {h.rule_id for h in finding.hits}

    def test_susume_masuka_trips(self) -> None:
        assert _verdict("PR を進めますか？") == AuditVerdict.FAIL

    def test_yoroshii_desuka_trips(self) -> None:
        assert _verdict("merge してよろしいですか") == AuditVerdict.FAIL


class TestInternalCodenames:
    def test_fr_codename_trips(self) -> None:
        # Lead-spec acceptance #2: FR-K without plain-language description.
        finding = apply_regex_rules("Working on FR-K now.")
        assert finding.verdict == AuditVerdict.FAIL
        assert "no-internal-codenames" in {h.rule_id for h in finding.hits}

    def test_contributor_branch_codename_trips(self) -> None:
        assert _verdict("pushed c-orochi-stale-pr-daemon") == AuditVerdict.FAIL

    def test_zoo_clause_codename_trips(self) -> None:
        assert _verdict("per ZOO#08 we should not.") == AuditVerdict.FAIL

    def test_rfc_codename_trips(self) -> None:
        assert _verdict("see RFC-42 for the design.") == AuditVerdict.FAIL


class TestHandymanBypass:
    def test_ywatanabe_please_run_trips(self) -> None:
        assert (
            _verdict("ywatanabe please run the deploy script")
            == AuditVerdict.FAIL
        )

    def test_ywatanabe_run_this_trips(self) -> None:
        assert _verdict("ywatanabe, run this and let me know") == AuditVerdict.FAIL

    def test_ywatanabe_unrelated_does_not_trip(self) -> None:
        # The rule looks for an action verb following ywatanabe within a
        # short window. A bare mention should not trip.
        assert _verdict("ywatanabe asked for a status update.") == AuditVerdict.UNKNOWN


class TestCleanMessages:
    def test_clean_status_message(self) -> None:
        # Lead-spec acceptance #3: clean message → PASS (UNKNOWN at this
        # layer; subscriber maps it to PASS).
        assert _verdict("Tests pass; pushing to develop.") == AuditVerdict.UNKNOWN

    def test_empty_message(self) -> None:
        assert _verdict("") == AuditVerdict.UNKNOWN


class TestMultipleHits:
    def test_one_message_can_trip_multiple_rules(self) -> None:
        # A real corpus example — banned phrase + codename leak in the
        # same message. Both should surface in the verdict.
        finding = apply_regex_rules(
            "Should I proceed with FR-K? It's a blocker."
        )
        assert finding.verdict == AuditVerdict.FAIL
        rules_hit = {h.rule_id for h in finding.hits}
        assert "zoo-08-banned-phrase-en" in rules_hit
        assert "no-internal-codenames" in rules_hit


class TestDefaultRulesShape:
    def test_every_default_rule_has_id_and_citation(self) -> None:
        for rule in default_rules():
            assert rule.rule_id, "rule_id must be non-empty"
            assert rule.citation, "citation must be non-empty"

    def test_rule_ids_are_unique(self) -> None:
        ids = [r.rule_id for r in default_rules()]
        assert len(ids) == len(set(ids))


class TestRuleInjection:
    def test_caller_supplied_rules_replace_default(self) -> None:
        custom = (
            Rule(
                rule_id="custom-foo",
                citation="local rule",
                pattern=re.compile(r"foo"),
                suggested_rephrase="say bar instead",
            ),
        )
        finding = apply_regex_rules("foo bar baz", rules=custom)
        assert finding.verdict == AuditVerdict.FAIL
        assert finding.hits[0].rule_id == "custom-foo"
        assert finding.hits[0].suggested_rephrase == "say bar instead"
