"""Fleet-wide health classification for Orochi agents.

This module isolates the *classification* concern: given a snapshot of
an agent (status / liveness / idle / heartbeat-age), decide which
``HealthState`` bucket it belongs to. Recovery (nudge / escalate / SSH)
lives in :mod:`scitex_orochi._caduceus`; data collection (REST poll)
lives there too. Putting classification in its own module makes it:

* unit-testable without spinning up the caduceus loop;
* swappable — a future PR can layer a SAC-provided
  ``sac agents health --json`` result on top of the heartbeat-age
  heuristic without touching the recovery code; and
* the obvious one-stop shop when someone asks "where is the IDLE
  threshold defined?".

Per the SAC↔Orochi audit (2026-05): Orochi keeps the *n*-state
classifier (HEALTHY/IDLE/STALE/DEAD) for the dashboard; SAC owns the
*binary* alive/dead check via ``sac agents health``. The
``sac_health`` optional field on :class:`AgentSnapshot` is the seam
where that signal will plug in once heartbeat collection forwards it
(PR #3 of the consumer-refactor sequence).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# ---------------------------------------------------------------------------
# Thresholds (seconds)
# ---------------------------------------------------------------------------
# These map to the recovery ladder in :mod:`scitex_orochi._caduceus`:
#   IDLE   → soft nudge in #general
#   STALE  → escalation in #general (optionally @ywatanabe)
#   DEAD   → would SSH the host and restart the bun MCP sidecar
NUDGE_THRESHOLD = 120
"""Seconds of agent silence before the IDLE bucket fires (soft nudge)."""

ESCALATE_THRESHOLD = 600
"""Seconds of agent silence before the STALE bucket fires (escalation)."""

DEAD_THRESHOLD = 300
"""Seconds of heartbeat silence before an agent is presumed DEAD."""


class HealthState(str, Enum):
    """Coarse health bucket the dashboard renders and caduceus heals on.

    Subclassing ``str`` keeps ``HealthState.OK == "ok"`` so existing
    callers that compare against string literals (REST responses,
    dashboard JSON) keep working.
    """

    OK = "ok"
    IDLE = "idle"
    STALE = "stale"
    DEAD = "dead"


@dataclass
class AgentSnapshot:
    """Minimal projection of an agent's state needed to classify it.

    Built from a hub `/api/agents/` row. Fields mirror the wire
    contract (see :mod:`scitex_orochi._models.heartbeat`) so the
    classifier can run without coupling to the hub's full ORM.

    Parameters
    ----------
    name, machine, status, liveness, idle_seconds, orochi_current_task,
    last_heartbeat:
        Verbatim heartbeat fields. ``status`` is "online" or "offline";
        ``liveness`` is the hub-derived fine-grained label.
    sac_health:
        Optional SAC-side binary verdict (``True`` healthy, ``False``
        unhealthy, ``None`` unknown). When set, takes precedence over
        heartbeat-age in :func:`classify`. Plumbed in by heartbeat
        collection (PR #3).
    """

    name: str
    machine: str
    status: str  # "online" | "offline"
    liveness: str  # "online" | "idle" | "stale" | "offline"
    idle_seconds: int | None
    orochi_current_task: str
    last_heartbeat: str | None  # ISO
    sac_health: bool | None = None

    @property
    def heartbeat_age_seconds(self) -> int | None:
        """Seconds since ``last_heartbeat``; ``None`` if missing/malformed."""
        if not self.last_heartbeat:
            return None
        try:
            ts = datetime.fromisoformat(self.last_heartbeat.replace("Z", "+00:00"))
        except ValueError:
            return None
        return int((datetime.now(timezone.utc) - ts).total_seconds())


def classify(agent: AgentSnapshot) -> HealthState:
    """Bucket an agent snapshot into a :class:`HealthState`.

    Decision order:

    1. ``sac_health is False`` → DEAD (SAC's per-host binary probe
       beats any heartbeat-age guess).
    2. ``status == "offline"`` → DEAD.
    3. heartbeat age > :data:`DEAD_THRESHOLD` → DEAD.
    4. ``liveness == "stale"`` → STALE.
    5. ``liveness == "idle"`` *and* the agent has a current task →
       IDLE (silent agents with no task assignment aren't problematic).
    6. otherwise OK.
    """
    if agent.sac_health is False:
        return HealthState.DEAD
    if agent.status == "offline":
        return HealthState.DEAD
    hb_age = agent.heartbeat_age_seconds
    if hb_age is not None and hb_age > DEAD_THRESHOLD:
        return HealthState.DEAD
    if agent.liveness == "stale":
        return HealthState.STALE
    if agent.liveness == "idle" and agent.orochi_current_task:
        return HealthState.IDLE
    return HealthState.OK
