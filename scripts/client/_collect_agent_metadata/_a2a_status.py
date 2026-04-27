"""Query the local sac A2A sidecar for live task state.

Hits the sac-side observability route added on 2026-04-27:

    GET http://<host>:<port>/v1/agents/<name>/_active

That route returns ``{"tasks": [{"id", "state", "last_event_at"}, ...]}``
listing every task currently in the per-agent in-memory task store. We
aggregate it into three primitive fields the heartbeat carries:

    active_task_count   — number of tasks currently in the store
    active_task_state   — A2A protobuf enum name of the most-recent
                          task (e.g. "TASK_STATE_WORKING"), or "" when
                          the store is empty
    last_task_event_at  — ISO 8601 timestamp of the most-recent task's
                          last status update (or None when unavailable)

These primitives let the orochi hub derive richer classifications
(idle / working / awaiting-input / stuck) without sac knowing anything
about orochi.

Fail-soft on every error mode — missing port, connection refused,
timeout, malformed JSON, HTTP 4xx/5xx — returns ``{}`` plus a single
``log.warning``. The heartbeat must not block on a stalled sidecar.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from ._log import log

_TIMEOUT_SECONDS = 2.0
_AGENTS_DIR = Path.home() / ".scitex" / "orochi" / "shared" / "agents"


def _read_a2a_endpoint(agent_name: str) -> tuple[str, int] | None:
    """Return (host, port) for the agent's A2A sidecar, or None.

    Reads ``spec.a2a.{host,port}`` from the canonical agent YAML at
    ``~/.scitex/orochi/shared/agents/<name>/<name>.yaml``. Returns None
    when the file is missing, the YAML lacks an ``a2a`` block, or any
    field is malformed.
    """
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


def collect_a2a_status(agent_name: str) -> dict[str, Any]:
    """Return primitive A2A task-state fields for ``agent_name``.

    See module docstring for the field contract. Always returns a dict;
    empty when the sidecar isn't reachable or the agent has no A2A
    config (legacy / non-A2A agents).
    """
    if not agent_name:
        return {}
    endpoint = _read_a2a_endpoint(agent_name)
    if endpoint is None:
        log.debug("collect_a2a_status %s: no a2a config — skipping", agent_name)
        return {}
    host, port = endpoint
    url = f"http://{host}:{port}/v1/agents/{agent_name}/_active"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:
            body = resp.read()
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        log.debug("collect_a2a_status %s: %s unreachable: %s", agent_name, url, exc)
        return {}
    except Exception as exc:  # pragma: no cover — defense in depth
        log.warning(
            "collect_a2a_status %s: unexpected fetch error: %s", agent_name, exc
        )
        return {}
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("collect_a2a_status %s: bad JSON from %s: %s", agent_name, url, exc)
        return {}
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if not isinstance(tasks, list):
        log.warning(
            "collect_a2a_status %s: expected list under 'tasks', got %s",
            agent_name,
            type(tasks).__name__,
        )
        return {}
    if not tasks:
        return {
            "active_task_count": 0,
            "active_task_state": "",
            "last_task_event_at": None,
        }

    # Pick the task with the most recent last_event_at as the
    # "representative" state for the agent. Ties broken by list order.
    def _sort_key(t: dict[str, Any]) -> str:
        ts = t.get("last_event_at")
        return ts if isinstance(ts, str) else ""

    most_recent = max(tasks, key=_sort_key)
    return {
        "active_task_count": len(tasks),
        "active_task_state": most_recent.get("state") or "",
        "last_task_event_at": most_recent.get("last_event_at"),
    }
