"""``daemon-auditor-haiku`` — fleet-wide ZOO/banned-phrase auditor.

FR-M (lead msg#23289 + msg#23300 + msg#23327). Subscribes to fleet
channels via :class:`scitex_orochi.OrochiClient`, runs a hybrid
audit pipeline against each new message (regex layer first for
zero-false-negative banned-phrase coverage; Haiku second-pass for
fuzzy rules), and posts a verdict.

Stage gating (msg#23300):
  Stage 1 — verdicts go *only* to ``#audit-shadow``; origin
            channels are not touched. 24h soak; lead + ywatanabe
            review false-positives.
  Stage 2 — react ⭕️/❌ on the origin message; no reply.
  Stage 3 — full ⭕️/❌ + reply with violation cite + suggested
            rephrase.

This package ships **Stage 1** behaviour. The stage is selected at
deploy time via the ``DAEMON_AUDITOR_STAGE`` env var (default ``1``).
"""

from scitex_orochi._daemons._auditor_haiku._rules import (
    AuditFinding,
    AuditVerdict,
    Rule,
    RuleHit,
    apply_regex_rules,
    default_rules,
)

__all__ = [
    "AuditFinding",
    "AuditVerdict",
    "Rule",
    "RuleHit",
    "apply_regex_rules",
    "default_rules",
]
