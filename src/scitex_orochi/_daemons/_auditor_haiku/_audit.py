"""Audit pipeline — combines regex layer with the Haiku second-pass.

Stage 1 (this PR) ships **regex-only**: the Haiku second-pass is a
stub that returns ``UNKNOWN`` so the pipeline maps regex-clean → PASS.
Stage 1.5 will plug in a real Haiku call; the seam is here so that
upgrade is a single function swap, not a pipeline rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass

from scitex_orochi._daemons._auditor_haiku._rules import (
    AuditFinding,
    AuditVerdict,
    Rule,
    apply_regex_rules,
)

# Type alias — keeping it as a free function (not a class with state)
# means the haiku-second-pass stub and the eventual real call have
# identical signatures, so swapping is a one-line ``haiku_judge=`` arg.
HaikuJudge = "Callable[[str], AuditVerdict] | None"


def _stub_haiku_judge(_text: str) -> AuditVerdict:
    """Stage 1 placeholder — never escalates a regex-clean message."""
    return AuditVerdict.UNKNOWN


@dataclass(frozen=True)
class AuditOutcome:
    """The final verdict the subscriber emits to ``#audit-shadow``.

    ``verdict`` collapses regex + Haiku into ``PASS|FAIL`` (Stage 1
    treats UNKNOWN as PASS). ``finding`` retains the rich detail so
    the subscriber can render a rule-by-rule trace in the shadow log.
    """

    verdict: AuditVerdict
    finding: AuditFinding


def audit_message(
    text: str,
    *,
    rules: tuple[Rule, ...] | None = None,
    haiku_judge=None,  # HaikuJudge — typed as Callable in Stage 1.5
) -> AuditOutcome:
    """Run the hybrid pipeline on a single message.

    The pipeline is: regex first (cheap, deterministic) → Haiku only
    on regex-clean (UNKNOWN). Once the Haiku second-pass is wired,
    that order keeps cost minimal while preserving zero-FN coverage
    of the explicit banned phrases.
    """
    finding = apply_regex_rules(text, rules=rules)
    if finding.verdict == AuditVerdict.FAIL:
        return AuditOutcome(verdict=AuditVerdict.FAIL, finding=finding)
    judge = haiku_judge or _stub_haiku_judge
    haiku_verdict = judge(text)
    if haiku_verdict == AuditVerdict.FAIL:
        return AuditOutcome(verdict=AuditVerdict.FAIL, finding=finding)
    return AuditOutcome(verdict=AuditVerdict.PASS, finding=finding)


def render_shadow_line(
    *,
    outcome: AuditOutcome,
    chat_id: str,
    msg_id: str | int,
    user: str,
    text: str,
    max_excerpt_chars: int = 200,
) -> str:
    """Format one audit verdict for posting to ``#audit-shadow``.

    Shape (per lead msg#23300 review-friendly format):
        ``[verdict=FAIL] in <chat_id> msg#<id> by <user> — rule=<id1,id2> phrase="<spans>" — text="<excerpt>"``

    For PASS verdicts we still emit a line (a quiet one) so the soak
    review has explicit per-message coverage; absence-of-line would
    be ambiguous between "auditor saw it and passed" and "auditor
    missed it entirely".
    """
    excerpt = text.strip().replace("\n", " ")
    if len(excerpt) > max_excerpt_chars:
        excerpt = excerpt[: max_excerpt_chars - 1] + "…"
    head = f"[verdict={outcome.verdict.value}] in {chat_id} msg#{msg_id} by {user}"
    if outcome.verdict == AuditVerdict.FAIL and outcome.finding.hits:
        rule_ids = ",".join(h.rule_id for h in outcome.finding.hits)
        spans = ",".join(f'"{h.matched_span}"' for h in outcome.finding.hits)
        return f'{head} — rule={rule_ids} phrase={spans} — text="{excerpt}"'
    return f'{head} — text="{excerpt}"'


__all__ = [
    "AuditOutcome",
    "audit_message",
    "render_shadow_line",
]
