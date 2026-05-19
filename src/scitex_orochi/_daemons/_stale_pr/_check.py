"""Pure stale-PR predicates and finding-selection.

Kept I/O-free so the rules are unit-testable without a gitea mock —
the wrapper supplies fetched PR + status payloads as plain dicts.

Spec recap (lead msg#23297):
  Stale PR := mergeable=True ∧ all-CI=success ∧ age > threshold_s

Selection rule (debounce):
  A finding is dispatched only if no DM was sent for the same PR
  identifier within the last ``redm_after_s`` window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Mapping


@dataclass(frozen=True)
class StalePrFinding:
    """A stale PR ready to dispatch a DM about.

    The ``key`` field is the stable identifier used for debounce
    state; ``repo + number`` works across PR title edits and force-pushes.
    """

    repo: str
    number: int
    sha: str
    age_seconds: float
    title: str
    author: str

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"


def _parse_iso8601(value: str) -> datetime:
    """Tolerant ISO-8601 parser — handles trailing ``Z`` and offsets.

    Gitea returns ``2026-04-29T12:34:56Z`` for created_at; Python's
    ``fromisoformat`` only accepts ``Z`` from 3.11 on. We're already
    on 3.11 per pyproject, so this is straight-through.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_stale(
    pr: Mapping,
    combined_status: Mapping,
    *,
    threshold_s: float,
    now_ts: float | None = None,
) -> bool:
    """Return True iff this PR meets the stale-merge criteria.

    Parameters
    ----------
    pr
        Gitea ``GET /repos/.../pulls`` element. Required keys:
        ``mergeable`` (bool), ``created_at`` (ISO-8601 str).
    combined_status
        Gitea ``GET /repos/.../commits/<sha>/status`` payload. Required
        key: ``state`` ∈ {``success``, ``pending``, ``failure``,
        empty-string for "no checks reported"}.
    threshold_s
        Minimum PR age (seconds since ``created_at``) before staleness
        kicks in. The original FR-N spec said 1h.
    now_ts
        Override "current time" for tests. Defaults to ``time.time()``.

    Notes
    -----
    A PR with no CI configured returns ``state=""`` from gitea — we
    treat that as "no checks reported" rather than success, because
    rubber-stamping a PR that *should* have had CI is exactly the
    failure mode the auditor (close-evidence-gate) catches separately.
    """
    if not pr.get("mergeable"):
        return False
    if combined_status.get("state") != "success":
        return False
    created_raw = pr.get("created_at")
    if not created_raw:
        return False
    created_dt = _parse_iso8601(created_raw)
    now = now_ts if now_ts is not None else time.time()
    age = now - created_dt.timestamp()
    return age > threshold_s


def _to_finding(pr: Mapping, repo: str, *, now_ts: float) -> StalePrFinding:
    created_dt = _parse_iso8601(pr["created_at"])
    return StalePrFinding(
        repo=repo,
        number=int(pr["number"]),
        sha=str(pr.get("head", {}).get("sha", "")),
        age_seconds=now_ts - created_dt.timestamp(),
        title=str(pr.get("title", "")),
        author=str(pr.get("user", {}).get("login", "")),
    )


@dataclass
class _DebounceView:
    """The minimum surface of :class:`StalePrState` this module needs.

    Defined as a Protocol-shaped dataclass so the ``select`` function
    can be unit-tested with a plain ``dict`` instead of touching the
    filesystem.
    """

    last_notified_ts: dict[str, float] = field(default_factory=dict)


def select_stale_for_dm(
    stale_findings: Iterable[StalePrFinding],
    state: _DebounceView,
    *,
    redm_after_s: float,
    now_ts: float | None = None,
) -> list[StalePrFinding]:
    """Filter findings down to those that should actually trigger a DM.

    Debounce rule: a key is suppressed if its last notification was
    less than ``redm_after_s`` ago. The state is *not* mutated here —
    the wrapper records the dispatch only after the DM POST succeeds,
    so a transient hub outage doesn't silently swallow an alert.
    """
    now = now_ts if now_ts is not None else time.time()
    out: list[StalePrFinding] = []
    for f in stale_findings:
        last = state.last_notified_ts.get(f.key)
        if last is None or (now - last) >= redm_after_s:
            out.append(f)
    return out


def findings_from_payload(
    pulls: Iterable[Mapping],
    status_lookup: Mapping[str, Mapping],
    repo: str,
    *,
    threshold_s: float,
    now_ts: float | None = None,
) -> list[StalePrFinding]:
    """Convenience: walk a ``GET /pulls`` list, attach combined status,
    and produce findings for the stale subset.

    ``status_lookup`` is keyed by head SHA so the wrapper can fetch
    once per PR and reuse the dict across reruns within a tick.
    """
    now = now_ts if now_ts is not None else time.time()
    out: list[StalePrFinding] = []
    for pr in pulls:
        sha = pr.get("head", {}).get("sha", "")
        status = status_lookup.get(sha, {})
        if is_stale(pr, status, threshold_s=threshold_s, now_ts=now):
            out.append(_to_finding(pr, repo, now_ts=now))
    return out


__all__ = [
    "StalePrFinding",
    "is_stale",
    "select_stale_for_dm",
    "findings_from_payload",
    "_DebounceView",
    "_parse_iso8601",
]
