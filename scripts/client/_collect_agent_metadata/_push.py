"""--push heartbeat: enumerate local agents and POST to /api/agents/register/."""

from __future__ import annotations

import json
import os

from ._collect import collect
from ._log import log
from ._multiplexer import _list_local_agents
from ._oauth import read_oauth_metadata
from ._sac_status import collect_sac_status


def _http_post_json(url: str, payload: dict, timeout: float = 5.0) -> tuple[int, str]:
    """POST JSON using requests if available, else stdlib urllib."""
    data = json.dumps(payload).encode("utf-8")
    try:
        import requests  # type: ignore

        r = requests.post(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        return r.status_code, r.text[:200]
    except ImportError:
        pass
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]


def _build_payload(meta: dict, tok: str, sac_status: dict | None = None) -> dict:
    """Project the rich collect() output into the heartbeat wire format.

    ``sac_status`` is the nested ``scitex-agent-container status --terse
    --json`` dict (lead msg#16005 pivot). Attached verbatim under the
    top-level ``sac_status`` key so the hub forwards every future field
    without per-field plumbing. ``orochi_subagent_count`` is still emitted at
    the top level as a backwards-compat shortcut (multiple consumers
    already key off it).
    """
    return {
        "token": tok,
        "name": meta["agent"],
        "agent_id": meta["agent"],
        "role": "agent",
        "orochi_machine": meta.get("orochi_machine", ""),
        # Live orochi_hostname(1) — authoritative per-process identity. Client-
        # supplied via ``collect()`` from ``socket.gethostname()``; never
        # derived from env or server-side inference. Root fix for the
        # proj-neurovista/mba misreport (lead msg#15578).
        "orochi_hostname": meta.get("orochi_hostname", ""),
        "orochi_hostname_canonical": meta.get("orochi_hostname_canonical", ""),
        "orochi_model": meta.get("orochi_model", ""),
        "orochi_multiplexer": meta.get("orochi_multiplexer", ""),
        "orochi_project": meta.get("orochi_project", ""),
        "workdir": meta.get("workdir", ""),
        "orochi_pid": meta.get("orochi_pid") or 0,
        "orochi_ppid": meta.get("orochi_ppid") or 0,
        "orochi_context_pct": meta.get("orochi_context_pct"),
        "orochi_subagent_count": int(meta.get("orochi_subagent_count") or 0),
        "orochi_skills_loaded": list(meta.get("orochi_skills_loaded") or []),
        "orochi_started_at": meta.get("orochi_started_at", ""),
        "orochi_version": meta.get("orochi_version", ""),
        "orochi_runtime": meta.get("orochi_runtime", ""),
        "orochi_current_task": meta.get("orochi_current_task", ""),
        # Intentionally no "channels" key. Subscriptions are
        # server-authoritative (ChannelMembership rows); heartbeats
        # must not clobber them.
        # Observability fields for the per-agent detail view
        # (/api/agents/<name>/detail/).
        "orochi_claude_md": meta.get("orochi_claude_md", ""),
        "orochi_mcp_json": meta.get("orochi_mcp_json", ""),
        "orochi_mcp_servers": list(meta.get("orochi_mcp_servers") or []),
        "orochi_pane_tail": meta.get("orochi_pane_tail", ""),
        "orochi_pane_tail_block": meta.get("orochi_pane_tail_block", ""),
        # todo#47 — full scrollback for the "Expand" toggle in the
        # agent detail pane viewer.
        "orochi_pane_tail_full": meta.get("orochi_pane_tail_full", ""),
        "orochi_pane_state": meta.get("orochi_pane_state", ""),
        "orochi_stuck_prompt_text": meta.get("orochi_stuck_prompt_text", ""),
        # scitex-orochi #187 / #59 — forward the hook-event ring buffer
        # summary so the Agents tab's Last tool / Last MCP / Last
        # action rows populate. Without this, collect() gathers them
        # but the whitelist drops them before they reach the hub
        # (same trap as #232 for orochi_pane_tail_full).
        "sac_hooks_recent_tools": meta.get("sac_hooks_recent_tools") or [],
        "sac_hooks_recent_prompts": meta.get("sac_hooks_recent_prompts") or [],
        "sac_hooks_tool_counts": meta.get("sac_hooks_tool_counts") or {},
        "sac_hooks_last_tool_name": meta.get("sac_hooks_last_tool_name") or "",
        "sac_hooks_last_tool_at": meta.get("sac_hooks_last_tool_at") or "",
        "sac_hooks_last_mcp_tool_name": meta.get("sac_hooks_last_mcp_tool_name") or "",
        "sac_hooks_last_mcp_tool_at": meta.get("sac_hooks_last_mcp_tool_at") or "",
        "sac_hooks_last_action_name": meta.get("sac_hooks_last_action_name") or "",
        "sac_hooks_last_action_at": meta.get("sac_hooks_last_action_at") or "",
        "sac_hooks_last_action_outcome": meta.get("sac_hooks_last_action_outcome") or "",
        "sac_hooks_last_action_elapsed_s": meta.get("sac_hooks_last_action_elapsed_s"),
        "sac_hooks_p95_elapsed_s_by_action": meta.get("sac_hooks_p95_elapsed_s_by_action") or {},
        # scitex-orochi #132 — subagent activity for the Agents tab
        # AGENT CALLS / BACKGROUND TASKS panels and the
        # active-subagent badge.
        "sac_hooks_agent_calls": meta.get("sac_hooks_agent_calls") or [],
        "sac_hooks_background_tasks": meta.get("sac_hooks_background_tasks") or [],
        "orochi_subagents": meta.get("orochi_subagents") or [],
        # scitex-orochi todo#369 — host-level orochi_machine orochi_metrics (CPU / mem
        # / disk / load) + optional SLURM cluster snapshot. Without
        # these two keys the hub's /api/resources rollup has no data
        # to populate the Machines tab card for agents pushed via this
        # legacy daemon path (symptom: mba / nas / spartan show zero /
        # blink while ywata-note-win — which pushes via the sidecar
        # heartbeat in ts/mcp_channel/heartbeat.ts that spreads the
        # full collect() output — renders correctly).
        #
        # Hub-side contract: POST /api/agents/register/ reads
        # body["orochi_metrics"] verbatim (see hub/views/api/_agents_register.py
        # line `update_heartbeat(name, orochi_metrics=body.get("orochi_metrics") or
        # {})`), and the merged per-agent snapshot is flattened into
        # each orochi_machine's aggregate card by hub/views/api/_resources.py.
        # `orochi_slurm` is a nested dict used by the Machines tab's SLURM
        # card on HPC hosts and is expected to be None on non-HPC.
        "orochi_metrics": meta.get("orochi_metrics") or {},
        "orochi_slurm": meta.get("orochi_slurm"),
        # Lead msg#16005 pivot: forward the ENTIRE ``sac status --terse
        # --json`` dict as a nested field. Future additions to sac's
        # status projection (orochi_context_pct, orochi_pane_state, orochi_current_tool,
        # quota, etc.) reach the hub registry + /api/agents/ payload
        # automatically — no per-field plumbing. ``--terse`` keeps the
        # per-agent bytes bounded (see TERSE_STATUS_FIELDS in
        # scitex_agent_container.terse). Empty dict when the CLI is
        # missing / errors — the hub treats absent = unknown.
        "sac_status": sac_status or {},
    }


def push_all(url=None, token=None) -> int:
    """Collect metadata for every local agent session and POST to the hub.

    Returns number of successful heartbeats. Never raises.
    """
    if os.environ.get("SCITEX_OROCHI_REGISTRY_DISABLE") == "1":
        log.info("push disabled via SCITEX_OROCHI_REGISTRY_DISABLE=1")
        return 0
    base = url or os.environ.get("SCITEX_OROCHI_URL_HTTP", "https://scitex-orochi.com")
    tok = token or os.environ.get("SCITEX_OROCHI_TOKEN", "")
    if not tok:
        log.warning("push skipped: no SCITEX_OROCHI_TOKEN in env")
        return 0
    endpoint = base.rstrip("/") + "/api/agents/register/"

    # todo#265: read Claude Code OAuth public metadata ONCE per push
    # cycle (not per agent) — it's the same for every local agent on
    # this host. Whitelist-only; never touches .credentials.json.
    oauth_meta = read_oauth_metadata()

    ok = 0
    for agent in _list_local_agents():
        try:
            meta = collect(agent)
            if not meta.get("orochi_alive"):
                continue
            # Lead msg#16005 pivot: shell out to ``sac status --terse
            # --json`` and attach the dict as ``sac_status``. Fail-soft:
            # ``collect_sac_status`` returns ``{}`` on any CLI / parse
            # error (it also logs). Collected per-agent so each payload
            # carries that agent's own status.
            sac_status = collect_sac_status(agent)
            payload = _build_payload(meta, tok, sac_status=sac_status)
            # todo#265: merge OAuth account public metadata into the
            # heartbeat payload. All 9 keys are whitelist-extracted
            # from ~/.claude.json — no tokens/secrets/credentials.
            payload.update(oauth_meta)
            status, body = _http_post_json(endpoint, payload)
            if 200 <= status < 300:
                ok += 1
                log.info(
                    "pushed %s ctx=%s%% subs=%s orochi_pid=%s",
                    agent,
                    meta.get("orochi_context_pct"),
                    meta.get("orochi_subagent_count"),
                    meta.get("orochi_pid"),
                )
            else:
                log.warning("push %s -> HTTP %s: %s", agent, status, body)
        except Exception as e:
            log.warning("push %s failed: %s", agent, e)
    return ok
