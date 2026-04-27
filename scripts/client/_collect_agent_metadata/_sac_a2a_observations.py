"""Layer A — A2A sidecar observations (pure data collection, no interpretation).

Queries the local sac sidecar's observability endpoint:

    GET http://<host>:<port>/v1/agents/<name>/_active
    → {"tasks": [{"id", "state", "last_event_at"}, ...]}

Returns a flat dict of primitive facts about the agent's task state. NO
opinions about "stuck" / "communicating" / "idle" — those live in
``states/_orochi_comm_state_v1.py`` (Layer B), which consumes this output.

Fail-soft on every error mode (missing port, connection refused,
timeout, malformed JSON) — returns a dict with ``endpoint_reachable:
False`` plus a short ``reachability_error`` so consumers can distinguish
"no A2A configured" from "A2A configured but down".
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ._log import log

_TIMEOUT_SECONDS = 2.0
_AGENTS_DIR = Path.home() / ".scitex" / "orochi" / "shared" / "agents"


def _read_a2a_endpoint(agent_name: str) -> tuple[str, int] | None:
    """Return (host, port) for the agent's A2A sidecar, or None."""
    if not agent_name:
        return None
    yaml_path = _AGENTS_DIR / agent_name / f"{agent_name}.yaml"
    if not yaml_path.is_file():
        return None
    try:
        doc = yaml.safe_load(yaml_path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.debug("a2a yaml parse failed for %s: %s", agent_name, exc)
        return None
    a2a = (doc.get("spec") or {}).get("a2a") or {}
    port = a2a.get("port")
    host = a2a.get("host") or "127.0.0.1"
    if not isinstance(port, int) or port <= 0:
        return None
    if not isinstance(host, str) or not host.strip():
        host = "127.0.0.1"
    return host.strip(), port


def _seconds_since_iso(ts: str | None) -> float | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        normalised = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def _empty(reason: str, *, configured: bool, reachable: bool) -> dict[str, Any]:
    return {
        "endpoint_configured": configured,
        "endpoint_reachable": reachable,
        "endpoint_url": None,
        "reachability_error": reason,
        "tasks": [],
        "active_task_count": 0,
        "tasks_by_state": {},
        "most_recent_event_at": None,
        "seconds_since_most_recent_event": None,
        "most_recent_task_state": "",
    }


def collect_sac_a2a_observations(agent_name: str) -> dict[str, Any]:
    """Layer A entry point: A2A sidecar → flat dict of primitive facts.

    Always returns a dict. Always includes ``endpoint_configured`` /
    ``endpoint_reachable`` so consumers can distinguish "no A2A" from
    "A2A down".
    """
    if not agent_name:
        return _empty("empty agent name", configured=False, reachable=False)
    endpoint = _read_a2a_endpoint(agent_name)
    if endpoint is None:
        return _empty("no a2a config in YAML", configured=False, reachable=False)
    host, port = endpoint
    url = f"http://{host}:{port}/v1/agents/{agent_name}/_active"

    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:
            body = resp.read()
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        log.debug(
            "collect_sac_a2a_observations %s: %s unreachable: %s", agent_name, url, exc
        )
        out = _empty(f"unreachable: {exc}", configured=True, reachable=False)
        out["endpoint_url"] = url
        return out
    except Exception as exc:  # pragma: no cover — defense in depth
        log.warning(
            "collect_sac_a2a_observations %s: unexpected fetch error: %s",
            agent_name,
            exc,
        )
        out = _empty(f"fetch error: {exc}", configured=True, reachable=False)
        out["endpoint_url"] = url
        return out

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(
            "collect_sac_a2a_observations %s: bad JSON from %s: %s",
            agent_name,
            url,
            exc,
        )
        out = _empty(f"bad json: {exc}", configured=True, reachable=False)
        out["endpoint_url"] = url
        return out

    raw_tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(raw_tasks, list):
        log.warning("collect_sac_a2a_observations %s: 'tasks' is not a list", agent_name)
        out = _empty("malformed: tasks not a list", configured=True, reachable=True)
        out["endpoint_url"] = url
        return out

    # Augment each task with seconds_since_event so consumers don't
    # have to re-parse timestamps.
    tasks: list[dict[str, Any]] = []
    by_state: dict[str, int] = {}
    most_recent: dict[str, Any] | None = None
    for t in raw_tasks:
        if not isinstance(t, dict):
            continue
        state = str(t.get("state") or "")
        ts = t.get("last_event_at")
        secs = _seconds_since_iso(ts)
        record = {
            "id": str(t.get("id") or ""),
            "state": state,
            "last_event_at": ts,
            "seconds_since_event": secs,
        }
        tasks.append(record)
        by_state[state] = by_state.get(state, 0) + 1
        # Pick the task with the smallest seconds_since_event (most
        # recent). Treat None as +infinity so tasks lacking a timestamp
        # never win the comparison.
        rec_secs = record["seconds_since_event"]
        rec_key = rec_secs if rec_secs is not None else float("inf")
        if most_recent is None:
            most_recent = record
        else:
            mr_secs = most_recent["seconds_since_event"]
            mr_key = mr_secs if mr_secs is not None else float("inf")
            if rec_key < mr_key:
                most_recent = record

    return {
        "endpoint_configured": True,
        "endpoint_reachable": True,
        "endpoint_url": url,
        "reachability_error": "",
        "tasks": tasks,
        "active_task_count": len(tasks),
        "tasks_by_state": by_state,
        "most_recent_event_at": (most_recent or {}).get("last_event_at"),
        "seconds_since_most_recent_event": (most_recent or {}).get(
            "seconds_since_event"
        ),
        "most_recent_task_state": (most_recent or {}).get("state", ""),
    }
