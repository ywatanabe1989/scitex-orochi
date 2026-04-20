"""--push heartbeat: enumerate local agents and POST to /api/agents/register/."""

from __future__ import annotations

import json
import os

from ._collect import collect
from ._log import log
from ._multiplexer import _list_local_agents
from ._oauth import read_oauth_metadata


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


def _build_payload(meta: dict, tok: str) -> dict:
    """Project the rich collect() output into the heartbeat wire format."""
    return {
        "token": tok,
        "name": meta["agent"],
        "agent_id": meta["agent"],
        "role": "agent",
        "machine": meta.get("machine", ""),
        "hostname_canonical": meta.get("hostname_canonical", ""),
        "model": meta.get("model", ""),
        "multiplexer": meta.get("multiplexer", ""),
        "project": meta.get("project", ""),
        "workdir": meta.get("workdir", ""),
        "pid": meta.get("pid") or 0,
        "ppid": meta.get("ppid") or 0,
        "context_pct": meta.get("context_pct"),
        "subagent_count": int(meta.get("subagent_count") or 0),
        "skills_loaded": list(meta.get("skills_loaded") or []),
        "started_at": meta.get("started_at", ""),
        "version": meta.get("version", ""),
        "runtime": meta.get("runtime", ""),
        "current_task": meta.get("current_task", ""),
        # Intentionally no "channels" key. Subscriptions are
        # server-authoritative (ChannelMembership rows); heartbeats
        # must not clobber them.
        # Observability fields for the per-agent detail view
        # (/api/agents/<name>/detail/).
        "claude_md": meta.get("claude_md", ""),
        "mcp_json": meta.get("mcp_json", ""),
        "mcp_servers": list(meta.get("mcp_servers") or []),
        "pane_tail": meta.get("pane_tail", ""),
        "pane_tail_block": meta.get("pane_tail_block", ""),
        # todo#47 — full scrollback for the "Expand" toggle in the
        # agent detail pane viewer.
        "pane_tail_full": meta.get("pane_tail_full", ""),
        "pane_state": meta.get("pane_state", ""),
        "stuck_prompt_text": meta.get("stuck_prompt_text", ""),
        # scitex-orochi #187 / #59 — forward the hook-event ring buffer
        # summary so the Agents tab's Last tool / Last MCP / Last
        # action rows populate. Without this, collect() gathers them
        # but the whitelist drops them before they reach the hub
        # (same trap as #232 for pane_tail_full).
        "recent_tools": meta.get("recent_tools") or [],
        "recent_prompts": meta.get("recent_prompts") or [],
        "tool_counts": meta.get("tool_counts") or {},
        "last_tool_name": meta.get("last_tool_name") or "",
        "last_tool_at": meta.get("last_tool_at") or "",
        "last_mcp_tool_name": meta.get("last_mcp_tool_name") or "",
        "last_mcp_tool_at": meta.get("last_mcp_tool_at") or "",
        "last_action_name": meta.get("last_action_name") or "",
        "last_action_at": meta.get("last_action_at") or "",
        "last_action_outcome": meta.get("last_action_outcome") or "",
        "last_action_elapsed_s": meta.get("last_action_elapsed_s"),
        "p95_elapsed_s_by_action": meta.get("p95_elapsed_s_by_action") or {},
        # scitex-orochi #132 — subagent activity for the Agents tab
        # AGENT CALLS / BACKGROUND TASKS panels and the
        # active-subagent badge.
        "agent_calls": meta.get("agent_calls") or [],
        "background_tasks": meta.get("background_tasks") or [],
        "subagents": meta.get("subagents") or [],
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
            if not meta.get("alive"):
                continue
            payload = _build_payload(meta, tok)
            # todo#265: merge OAuth account public metadata into the
            # heartbeat payload. All 9 keys are whitelist-extracted
            # from ~/.claude.json — no tokens/secrets/credentials.
            payload.update(oauth_meta)
            status, body = _http_post_json(endpoint, payload)
            if 200 <= status < 300:
                ok += 1
                log.info(
                    "pushed %s ctx=%s%% subs=%s pid=%s",
                    agent,
                    meta.get("context_pct"),
                    meta.get("subagent_count"),
                    meta.get("pid"),
                )
            else:
                log.warning("push %s -> HTTP %s: %s", agent, status, body)
        except Exception as e:
            log.warning("push %s failed: %s", agent, e)
    return ok
