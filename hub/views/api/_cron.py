"""``GET /api/cron/`` — fleet-wide cron status aggregator.

Phase 2 of the Orochi unified cron (lead msg#16406 / msg#16408). Phase 1
landed the per-host daemon + CLI in scitex-orochi (PR #335); every head
heartbeat since carries a ``cron_jobs`` array describing the daemon's
state on that host.

This view aggregates those arrays across the in-memory registry and
returns a host-keyed dict that the Machines tab (and any external tool)
can render without talking to each host directly. No new DB model — we
reuse the registry that ``/api/agents/`` already reads from.

Shape::

    {
      "hosts": {
        "mba": {
          "agent": "head-mba",
          "last_heartbeat_at": "2026-04-22T...Z",
          "stale": false,
          "jobs": [
            {"name": "orochi_machine-heartbeat",
             "last_run": 1713792000.0,
             "last_exit": 0,
             "next_run": 1713792120.0,
             ...},
            ...
          ]
        },
        ...
      }
    }

Staleness: a host is marked ``stale: true`` when the hub has not seen a
heartbeat in >10 minutes (``HEARTBEAT_STALE_THRESHOLD_S``). The hub keeps
serving the last-known ``jobs`` array so the UI can show stale data with
a warning rather than dropping the card.

Auth (lead msg#16684 follow-up): accepts either a Django session OR a
workspace token (``?token=wks_...&agent=<name>``) so the MCP
``cron_status`` tool can hit it from the bare domain without a browser
session. Routing falls back on the same ``resolve_workspace_and_actor``
helper used by other agent-callable read-only endpoints (channel_members,
my_subscriptions, ...).

Optional ``?host=<name>`` query param filters the response server-side
to a single host key — cheaper than pulling all hosts and discarding the
rest on the client.
"""

import time
from datetime import datetime, timezone

from hub.views._helpers import resolve_workspace_and_actor
from hub.views.api._common import (
    JsonResponse,
    require_GET,
)

# >10 min since last heartbeat → host is stale. Same 600s threshold
# used by the liveness classifier in ``_payload.get_agents()``; keep in
# sync if that one moves.
HEARTBEAT_STALE_THRESHOLD_S = 600


def _host_key(agent_row: dict) -> str:
    """Prefer the short ``orochi_machine`` label, fall back to ``hostname`` then agent name.

    The Machines tab keys cards by ``orochi_machine`` (e.g. "mba", "nas") so we
    do the same here — a head and its per-host workers collapse to one
    row per physical host.
    """
    return (
        (agent_row.get("orochi_machine") or "").strip()
        or (agent_row.get("hostname") or "").strip()
        or agent_row.get("name", "")
    )


def _to_iso(ts: str | float | None) -> str | None:
    """Normalise a heartbeat timestamp (ISO string or epoch float) to ISO."""
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(ts, str):
        return ts
    return None


@require_GET
def api_cron(request):
    """GET /api/cron/ — fleet-wide cron status aggregated from heartbeats.

    Auth: accepts either a Django session (dashboard) OR a workspace
    token (``?token=wks_...&agent=<name>`` — MCP sidecars on the bare
    domain). Workspace-scoped: the registry read is filtered by the
    resolved workspace, so users on different workspaces see disjoint
    host sets.

    Query params:
        host: optional host key (orochi_machine label, e.g. ``mba``). When
            present, the response is filtered server-side to that
            single host. If the host is unknown, ``{"hosts": {}}`` is
            returned — the same shape as "no hosts reporting".

    Returns ``{"hosts": {<orochi_machine>: {agent, last_heartbeat_at, stale,
    jobs}}}``. An empty registry (or a workspace with no heads) returns
    ``{"hosts": {}}``; never 404 — the Machines tab panel renders an
    "no hosts reporting" placeholder in that case.

    Collision strategy when multiple agents report from the same orochi_machine
    (e.g. head-mba + healer-mba + the nas head sharing a hostname):
    the newest non-empty ``cron_jobs`` wins. Heads are the authoritative
    cron-job source (Phase 1 installs the daemon on heads only), so this
    naturally picks the head's view without hardcoding ``role == "head"``.
    """
    from hub.registry import get_agents

    workspace, _actor, err = resolve_workspace_and_actor(request)
    if err is not None:
        return err

    host_filter = (request.GET.get("host") or "").strip() or None
    agents = get_agents(workspace_id=workspace.id)

    now = time.time()
    hosts: dict[str, dict] = {}
    # Track the heartbeat epoch-time for each host so we can always prefer
    # the freshest cron_jobs source when multiple agents share a host.
    host_best_hb: dict[str, float] = {}

    for a in agents:
        host = _host_key(a)
        if not host:
            continue
        # ``?host=<name>`` short-circuits the aggregation: skip any row
        # whose host key doesn't match. Done at loop-head so collision
        # resolution (freshness wins) stays scoped to the filtered host.
        if host_filter is not None and host != host_filter:
            continue
        jobs = a.get("cron_jobs") or []
        # Parse last_heartbeat to an epoch float for the stale check +
        # freshness-wins tiebreak.
        hb_iso = a.get("last_heartbeat")
        hb_epoch: float | None = None
        if isinstance(hb_iso, str) and hb_iso:
            try:
                hb_epoch = datetime.fromisoformat(
                    hb_iso.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                hb_epoch = None

        existing = hosts.get(host)
        # Freshness wins. If the incumbent has jobs and this one doesn't,
        # keep the incumbent. If both have jobs, pick the newer heartbeat.
        # If neither has jobs, pick the newer heartbeat so the row still
        # shows up (with an empty jobs array).
        incumbent_hb = host_best_hb.get(host, 0.0)
        incumbent_jobs = existing.get("jobs") if existing else []
        promote = False
        if existing is None:
            promote = True
        elif jobs and not incumbent_jobs:
            promote = True
        elif jobs and incumbent_jobs:
            promote = (hb_epoch or 0.0) > incumbent_hb
        elif not jobs and not incumbent_jobs:
            promote = (hb_epoch or 0.0) > incumbent_hb

        if not promote:
            continue

        stale = False
        if hb_epoch is not None:
            stale = (now - hb_epoch) > HEARTBEAT_STALE_THRESHOLD_S

        hosts[host] = {
            "agent": a.get("name", ""),
            "last_heartbeat_at": _to_iso(hb_iso) or _to_iso(hb_epoch),
            "stale": bool(stale),
            "jobs": list(jobs),
        }
        host_best_hb[host] = hb_epoch or 0.0

    return JsonResponse({"hosts": hosts})
