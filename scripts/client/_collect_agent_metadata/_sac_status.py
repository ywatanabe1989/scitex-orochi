"""Shell out to ``scitex-agent-container status --terse --json`` for heartbeat forwarding.

Lead msg#16005 spec: instead of per-field plumbing (``subagent_count``
only in the previous cut of this PR), forward the FULL ``sac status``
terse-JSON payload as a nested ``sac_status`` field on the heartbeat.
This way new fields added to ``sac status`` (``orochi_context_pct``,
``pane_state``, ``current_tool``, quota, etc.) are automatically
adopted hub-side without every consumer opening a PR.

Design:

* Use ``--terse`` so the payload stays small (the full ``status --json``
  is ~18x larger and carries noise we don't need on the heartbeat hot
  path — see ``scitex_agent_container.terse.TERSE_STATUS_FIELDS``).
* Fail soft: missing CLI / nonzero exit / JSON parse error -> ``{}``
  plus a single ``log.warning`` (never raises into the heartbeat
  loop).
* Honour a short timeout (3 s) — ``sac status`` is normally a pure
  read, but a hung tmux / registry can stall it; the heartbeat must
  not block on us.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from ._log import log

_SAC_CLI = "scitex-agent-container"
_TIMEOUT_SECONDS = 3.0


def collect_sac_status(agent_name: str) -> dict:
    """Return ``sac status <agent_name> --terse --json`` as a dict.

    Graceful on every failure mode:

    * ``scitex-agent-container`` not on ``PATH`` -> ``{}`` + warning.
    * Nonzero exit (agent not in sac registry, tmux missing, etc.) ->
      ``{}`` + warning (stderr included so the heartbeat log is
      diagnostic).
    * Stdout not valid JSON -> ``{}`` + warning.
    * Process hangs -> ``{}`` (subprocess times out after 3 s).

    Returned dict is passed through verbatim — the caller attaches it
    under the top-level ``sac_status`` key in the heartbeat payload so
    downstream consumers see the flat ``sac_status["field"]`` shape
    (``--terse`` already flattens dotted paths).
    """
    if not agent_name:
        return {}
    if shutil.which(_SAC_CLI) is None:
        # Quiet — many dev environments don't have sac installed, and
        # this helper runs on every push cycle. A single debug line is
        # enough to confirm the code path is reached.
        log.debug("collect_sac_status: %s not on PATH — skipping", _SAC_CLI)
        return {}
    try:
        r = subprocess.run(
            [_SAC_CLI, "status", agent_name, "--terse", "--json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        log.warning(
            "collect_sac_status %s: timed out after %.1fs",
            agent_name,
            _TIMEOUT_SECONDS,
        )
        return {}
    except Exception as exc:  # pragma: no cover — defense in depth
        log.warning("collect_sac_status %s: subprocess failed: %s", agent_name, exc)
        return {}
    if r.returncode != 0:
        log.warning(
            "collect_sac_status %s: exit=%d stderr=%s",
            agent_name,
            r.returncode,
            (r.stderr or "").strip()[:200],
        )
        return {}
    try:
        data = json.loads(r.stdout or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(
            "collect_sac_status %s: json parse failed: %s (stdout head=%r)",
            agent_name,
            exc,
            (r.stdout or "")[:120],
        )
        return {}
    if not isinstance(data, dict):
        log.warning(
            "collect_sac_status %s: expected dict, got %s", agent_name, type(data)
        )
        return {}
    return data
