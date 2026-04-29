"""Regex rule layer for ``daemon-auditor-haiku`` (FR-M).

The hybrid pipeline (lead msg#23300) runs this layer first because:

  * Banned phrases are exact-match-able and deserve **zero false
    negatives** — phrasing the rule as a regex makes the meaning
    inspectable, version-controllable, and unit-testable.
  * Each rule carries a ZOO / runbook citation so the verdict shows
    *why* the message tripped, not just *that* it did. The Stage 3
    reply will quote this so the offending agent learns the rule.

The Haiku second-pass (separate module) handles the fuzzy ones —
hypothesis menus, communication-priority gaps, "ywatanabe please run
X" intent without literal phrase. Those rules need judgement; they
don't fit a regex without unacceptable false-positive rates.

Self-exclusion is **not** the responsibility of this module — the
subscriber filters by sender before invoking ``apply_regex_rules``.
That keeps the rules pure and means tests can assert "if this string
arrived from this sender, it would fail" without simulating a
network sender filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Pattern


class AuditVerdict(str, Enum):
    """Three-valued verdict — UNKNOWN exists so a regex-pass result
    can be distinguished from a confidently-clean result. The Haiku
    second-pass turns UNKNOWN into PASS or FAIL; for Stage 1 we
    treat UNKNOWN as PASS (regex-only).
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Rule:
    """One regex-checkable rule.

    Attributes
    ----------
    rule_id
        Stable short id used in verdict output and in tests. Don't
        rename without updating skill docs that quote it.
    citation
        Plain-text rule source (ZOO clause, runbook section). Surfaced
        in the verdict so the auditor's reaction is self-explanatory.
    pattern
        Compiled regex. Use ``re.IGNORECASE`` for natural-language
        phrases; use a tighter pattern for codename-leak rules so a
        legitimate technical mention with prose around it doesn't trip.
    suggested_rephrase
        Reserved for Stage 3 reply text. Stage 1 still records it so
        the shadow log is self-explanatory.
    """

    rule_id: str
    citation: str
    pattern: Pattern[str]
    suggested_rephrase: str = ""


@dataclass(frozen=True)
class RuleHit:
    """A single rule firing on a message — keep the matched span so
    the shadow log can show *where* the rule tripped, not just *which*."""

    rule_id: str
    citation: str
    matched_span: str
    suggested_rephrase: str


@dataclass(frozen=True)
class AuditFinding:
    """The full verdict for one message.

    A message can trip multiple rules — we surface them all in
    ``hits`` rather than short-circuiting on first match, because
    Stage 1 review benefits from knowing the *full* surface area of
    a violation (training data for tightening Haiku prompts later).
    """

    verdict: AuditVerdict
    hits: tuple[RuleHit, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------
#
# Each rule is intentionally small + readable. Adding a rule is one
# tuple + one test. Removing a rule is the inverse — never delete a
# rule without deleting its test, otherwise reviewers can't tell why
# coverage dropped.

# ZOO#08 — agents must not surface "blocker" framing to ywatanabe.
# Fleet convention: investigate, don't escalate. The phrase "blocker"
# is a tell that an agent is asking ywatanabe to unblock something
# they could have unblocked themselves.
_BANNED_PHRASES_ZOO_08 = re.compile(
    r"\b("
    r"blocker"
    r"|blocked\s+on\s+ywatanabe"
    r"|should\s+I"
    r"|may\s+I"
    r")\b",
    re.IGNORECASE,
)

# Same rule, JP variant — these phrases convey the same "asking
# permission" pattern that ZOO#08 prohibits.
_BANNED_PHRASES_ZOO_08_JP = re.compile(
    r"(OK\s*ですか|進めますか|よろしいですか|宜しいですか)"
)

# "no internal codenames" rule — when an agent surfaces a contributor
# branch name like "c-orochi-foo" or an FR id like "FR-K" *to
# ywatanabe* (or in his channel) without a plain-language description,
# he can't tell what the work actually is. The rule fires on the
# bare codename; the subscriber decides whether the message is
# *to ywatanabe* before applying.
_INTERNAL_CODENAMES = re.compile(
    r"\b("
    # FR-X / RFC-X / ZOO#NN style identifiers
    r"FR-[A-Z]+\b"
    r"|RFC-\d+\b"
    r"|ZOO#\d+\b"
    # contributor branch names
    r"|c-orochi-[a-z0-9-]+"
    r"|c-sac-[a-z0-9-]+"
    r"|c-scitex-[a-z0-9-]+"
    r")",
)

# "ywatanabe please run X" — agents must not ask ywatanabe to run
# commands they could have run themselves. The handyman path
# (``handyman-spartan`` etc.) is the correct route. This is a coarse
# detector; Haiku second-pass refines.
_HUMAN_HANDYMAN_BYPASS = re.compile(
    r"ywatanabe[^\n]{0,80}?\b(please\s+run|run\s+this|execute)\b",
    re.IGNORECASE,
)


def default_rules() -> tuple[Rule, ...]:
    """The rule set ``daemon-auditor-haiku`` ships with by default.

    Tests pin every rule's id + citation so a refactor that drops
    coverage is loud. Don't tighten patterns here without first
    expanding tests — the cost of a false-negative on a banned phrase
    is precisely the failure mode this daemon exists to catch.
    """
    return (
        Rule(
            rule_id="zoo-08-banned-phrase-en",
            citation="ZOO#08 (humans-out-of-loop): no permission-asking phrases",
            pattern=_BANNED_PHRASES_ZOO_08,
            suggested_rephrase=(
                "State what you're going to do (or what you did), not whether "
                "ywatanabe should let you. Investigate, don't escalate."
            ),
        ),
        Rule(
            rule_id="zoo-08-banned-phrase-jp",
            citation="ZOO#08 (humans-out-of-loop): 「OK ですか」「進めますか」禁止",
            pattern=_BANNED_PHRASES_ZOO_08_JP,
            suggested_rephrase=(
                "許可を聞かず、行動を述べる。investigate-don't-ask。"
            ),
        ),
        Rule(
            rule_id="no-internal-codenames",
            citation="no-internal-codenames rule — plain-language to ywatanabe",
            pattern=_INTERNAL_CODENAMES,
            suggested_rephrase=(
                "Pair the codename with a plain-language description "
                "('FR-K = MCP sidecar reconnect') the first time you "
                "mention it in a thread."
            ),
        ),
        Rule(
            rule_id="lead-routes-handyman-bypass",
            citation="lead-routes-only override — use handyman, not ywatanabe",
            pattern=_HUMAN_HANDYMAN_BYPASS,
            suggested_rephrase=(
                "Route command requests through handyman-<host>. ywatanabe "
                "is not an actuator."
            ),
        ),
    )


def apply_regex_rules(
    text: str,
    *,
    rules: Iterable[Rule] | None = None,
) -> AuditFinding:
    """Run every rule and aggregate the hits.

    Returns ``UNKNOWN`` (not ``PASS``) when nothing fires, because the
    Haiku second-pass may still flag the message. The subscriber maps
    ``UNKNOWN → PASS`` for Stage 1.
    """
    rule_list = tuple(rules) if rules is not None else default_rules()
    hits: list[RuleHit] = []
    for rule in rule_list:
        for m in rule.pattern.finditer(text):
            hits.append(
                RuleHit(
                    rule_id=rule.rule_id,
                    citation=rule.citation,
                    matched_span=m.group(0),
                    suggested_rephrase=rule.suggested_rephrase,
                )
            )
    if hits:
        return AuditFinding(verdict=AuditVerdict.FAIL, hits=tuple(hits))
    return AuditFinding(verdict=AuditVerdict.UNKNOWN, hits=())


__all__ = [
    "AuditFinding",
    "AuditVerdict",
    "Rule",
    "RuleHit",
    "apply_regex_rules",
    "default_rules",
]
