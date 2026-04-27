"""``scitex-orochi heartbeat-push`` — consume scitex-agent-container status
and POST it to the Orochi hub's agent register endpoint.

Design rules
------------
- **Non-agentic.** Pure subprocess + HTTP POST. No LLM involvement.
- **One-way dependency.** scitex-orochi knows about scitex-agent-container;
  scitex-agent-container has no knowledge of scitex-orochi.
- **Scitex-orochi-specific metadata** (workspace token, hub URL,
  optional channel overrides) is added server-facing by this command,
  not by agent-container.

Typical usage::

    scitex-orochi heartbeat-push head-ywata-note-win \\
        --token $SCITEX_OROCHI_TOKEN \\
        --hub https://scitex-orochi.com \\
        --loop 30
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError

import click


def _run_agent_container_status(name: str) -> dict[str, Any]:
    """Invoke ``scitex-agent-container status <name> --json`` and parse JSON."""
    try:
        proc = subprocess.run(
            ["scitex-agent-container", "status", name, "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as e:
        raise click.ClickException(
            "scitex-agent-container not found on PATH; install it or set PATH"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise click.ClickException(
            f"scitex-agent-container status {name} timed out after 15s"
        ) from e
    if proc.returncode != 0:
        raise click.ClickException(
            f"scitex-agent-container status failed: {proc.stderr.strip() or proc.returncode}"
        )
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        raise click.ClickException(
            f"scitex-agent-container status returned non-JSON output: {e}"
        ) from e


def _wrap_with_orochi_fields(
    status: dict[str, Any],
    *,
    token: str,
    channels: list[str] | None,
) -> dict[str, Any]:
    """Merge the scitex-agent-container status output with orochi-specific
    fields expected by ``/api/agents/register/`` (workspace token, optional
    channel override, defensive defaults).

    Leaves every status field intact so extensions landing in
    agent-container surface automatically without a code change here.
    """
    body: dict[str, Any] = {
        "token": token,
        "name": status.get("name") or "",
        "agent_id": status.get("name") or "",
        "machine": status.get("machine") or "",
        "role": status.get("role") or "agent",
        "model": status.get("model") or "",
        "workdir": status.get("workdir") or "",
        "multiplexer": status.get("multiplexer") or "",
        "project": status.get("project") or status.get("name") or "",
        "pid": int(status.get("pid") or 0),
        "ppid": int(status.get("ppid") or 0),
        "orochi_context_pct": status.get("orochi_context_pct"),
        # YAML-declared compact policy from sac status (None when noop /
        # unconfigured). Surfaced in the Agents tab next to the live
        # orochi_context_pct so operators can see the threshold each agent uses.
        "context_management": status.get("context_management"),
        "orochi_current_task": status.get("orochi_current_task") or "",
        "orochi_current_tool": status.get("orochi_current_tool") or "",
        "orochi_subagent_count": int(status.get("orochi_subagent_count") or 0),
        "subagents": status.get("subagents") or [],
        # Claude usage quota — surfaced under the UI-expected keys.
        "quota_5h_used_pct": status.get("quota_5h_used_pct"),
        "quota_7d_used_pct": status.get("quota_7d_used_pct"),
        "quota_5h_reset_at": status.get("quota_5h_reset_at") or "",
        "quota_7d_reset_at": status.get("quota_7d_reset_at") or "",
        # Machine-level metrics (host-level, dedupe concern on the server).
        "metrics": status.get("metrics") or {},
        # Terminal pane + classified state.
        "pane_text": status.get("pane_text") or "",
        "orochi_pane_tail_block": status.get("pane_text") or "",
        "orochi_pane_state": status.get("orochi_pane_state") or "",
        "orochi_stuck_prompt_text": status.get("orochi_stuck_prompt_text") or "",
        # Workspace files.
        "orochi_claude_md": status.get("orochi_claude_md") or "",
        "orochi_claude_md_head": (status.get("orochi_claude_md") or "").splitlines()[0][:120]
        if status.get("orochi_claude_md")
        else "",
        "orochi_mcp_json": status.get("orochi_mcp_json") or "",
        # Claude Code hook-captured events (new — forwarded as-is).
        "sac_hooks_recent_tools": status.get("sac_hooks_recent_tools") or [],
        "sac_hooks_recent_prompts": status.get("sac_hooks_recent_prompts") or [],
        "sac_hooks_agent_calls": status.get("sac_hooks_agent_calls") or [],
        "background_tasks": status.get("background_tasks") or [],
        "sac_hooks_tool_counts": status.get("sac_hooks_tool_counts") or {},
        # Functional-heartbeat shortcuts (derived in agent-container).
        "sac_hooks_last_tool_at": status.get("sac_hooks_last_tool_at") or "",
        "sac_hooks_last_tool_name": status.get("sac_hooks_last_tool_name") or "",
        "sac_hooks_last_mcp_tool_at": status.get("sac_hooks_last_mcp_tool_at") or "",
        "sac_hooks_last_mcp_tool_name": status.get("sac_hooks_last_mcp_tool_name") or "",
        # PaneAction summary (from scitex-agent-container action_store).
        # Empty when actions subsystem is unused; dashboard chips it
        # as "last probe / compact / ... outcome N ago".
        "last_action_at": status.get("last_action_at") or "",
        "sac_hooks_last_action_name": status.get("sac_hooks_last_action_name") or "",
        "last_action_outcome": status.get("last_action_outcome") or "",
        "last_action_elapsed_s": status.get("last_action_elapsed_s"),
        "action_counts": status.get("action_counts") or {},
        "sac_hooks_p95_elapsed_s_by_action": status.get("sac_hooks_p95_elapsed_s_by_action") or {},
        # Accounting.
        "orochi_account_email": status.get("orochi_account_email") or "",
        "version": status.get("version") or "",
    }
    # Orochi unified cron state (msg#16406 / msg#16410). Surfaced in
    # every heartbeat so Phase 2 can wire the Machines tab directly off
    # /api/agents/...heartbeat.payload.cron_jobs — no extra endpoint
    # needed. Empty list when the daemon isn't running on this host, so
    # UI just renders "no jobs".
    body["cron_jobs"] = _collect_cron_jobs()
    if channels:
        body["channels"] = list(channels)
    return body


def _collect_cron_jobs() -> list[dict[str, Any]]:
    """Read the orochi-cron state file and normalise it for heartbeat.

    Defensive: any read / parse error returns an empty list. The
    heartbeat is best-effort telemetry; never let a local daemon glitch
    prevent the health signal from reaching the hub.
    """
    try:
        from scitex_orochi._cron import default_state_path, state_read
        from scitex_orochi._cron._state import render_cron_jobs

        return render_cron_jobs(state_read(default_state_path()))
    except Exception:
        return []


def _post_register(hub: str, body: dict[str, Any]) -> tuple[int, str]:
    """POST the heartbeat to ``<hub>/api/agents/register/``. Returns (status, text)."""
    url = hub.rstrip("/") + "/api/agents/register/"
    data = json.dumps(body).encode("utf-8")
    req = _urllib_request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Cloudflare in front of the hub rejects the default
            # Python-urllib User-Agent; mimic a real client.
            "User-Agent": "scitex-orochi-heartbeat/1.0 (+https://scitex-orochi.com)",
        },
    )
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            return resp.status, (resp.read().decode("utf-8", errors="replace") or "")
    except HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, body_txt
    except URLError as e:
        raise click.ClickException(f"hub unreachable: {e.reason}")


def _list_local_agents() -> list[str]:
    """Enumerate locally-running agent session names by shelling out to
    ``scitex-agent-container list --json``. Replaces the legacy
    ``agent_meta.py --push`` enumeration that walked ``tmux ls`` /
    ``screen -ls`` directly — sac is the source of truth for which
    agent sessions are local now.

    Returns the list of agent names whose registry entry says
    ``location == "LOCAL"``. Empty list on any failure (no sac, no
    agents) — caller treats that as "nothing to push this cycle".
    """
    try:
        proc = subprocess.run(
            ["scitex-agent-container", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    rows = data.get("agents", data) if isinstance(data, dict) else data
    out: list[str] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if str(r.get("location", "")).upper() != "LOCAL":
            continue
        n = r.get("name") or r.get("agent_id")
        if n:
            out.append(str(n))
    return out


@click.command("heartbeat-push")
@click.argument("name", required=False)
@click.option(
    "--all",
    "push_all",
    is_flag=True,
    help="Push heartbeats for every locally-running agent (sac list --json).",
)
@click.option(
    "--token",
    envvar="SCITEX_OROCHI_TOKEN",
    required=True,
    help="Workspace token (reads SCITEX_OROCHI_TOKEN if unset).",
)
@click.option(
    "--hub",
    envvar="SCITEX_OROCHI_URL",
    default="https://scitex-orochi.com",
    show_default=True,
    help="Hub base URL (reads SCITEX_OROCHI_URL if unset).",
)
@click.option(
    "--channel",
    "channels",
    multiple=True,
    help="Override the channel list sent to the hub. Omit for server-authoritative.",
)
@click.option(
    "--loop",
    "loop_seconds",
    type=int,
    default=0,
    help="Run continuously every N seconds. 0 = single push and exit (default).",
)
@click.option("--verbose", is_flag=True, help="Print each push result to stderr.")
def heartbeat_push(
    name: str | None,
    push_all: bool,
    token: str,
    hub: str,
    channels: tuple[str, ...],
    loop_seconds: int,
    verbose: bool,
) -> None:
    """Push one (or a loop of) heartbeat to the Orochi hub from
    scitex-agent-container's ``status`` CLI output.

    Two modes:

    * ``heartbeat-push <name>`` — push a single agent's heartbeat.
    * ``heartbeat-push --all``  — push every locally-running agent.
      Replaces the deprecated ``scripts/client/agent_meta.py --push``
      daemon, with the benefit of going through ``sac status --json``
      so the latest pane-state classifier (auth_error wordings,
      compose_pending fix, etc.) lands on every cycle.

    The pusher is deterministic: shells out to ``scitex-agent-container``
    and POSTs the result (plus token + optional channel override) to
    ``/api/agents/register/``. No LLM, no MCP — just subprocess + HTTP.
    """
    if not push_all and not name:
        raise click.UsageError("Provide an agent NAME or --all.")
    if push_all and name:
        raise click.UsageError("--all is mutually exclusive with NAME.")
    ch_list = list(channels) if channels else None

    def _push_one(agent_name: str) -> int:
        try:
            status = _run_agent_container_status(agent_name)
        except click.ClickException as e:
            click.echo(f"[heartbeat-push] {agent_name}: {e.format_message()}", err=True)
            return 1
        body = _wrap_with_orochi_fields(status, token=token, channels=ch_list)
        code, resp = _post_register(hub, body)
        if verbose:
            click.echo(
                f"[heartbeat-push] {agent_name} -> {hub} HTTP {code} "
                f"orochi_pane_state={body.get('orochi_pane_state')} "
                f"context={body.get('orochi_context_pct')} "
                f"quota_5h={body.get('quota_5h_used_pct')} "
                f"tools={sum((body.get('sac_hooks_tool_counts') or {}).values())}",
                err=True,
            )
        if code >= 400:
            click.echo(resp[:500], err=True)
            return 1
        return 0

    def _once() -> int:
        if push_all:
            agents = _list_local_agents()
            if not agents:
                if verbose:
                    click.echo(
                        "[heartbeat-push --all] no local agents this cycle",
                        err=True,
                    )
                return 0
            errs = sum(_push_one(a) for a in agents)
            return 1 if errs else 0
        return _push_one(name or "")

    if loop_seconds <= 0:
        sys.exit(_once())
    while True:
        try:
            _once()
        except click.ClickException as e:
            click.echo(f"[heartbeat-push] error: {e.format_message()}", err=True)
        except Exception as e:  # noqa: BLE001 — never crash the loop
            click.echo(f"[heartbeat-push] unexpected: {e}", err=True)
        time.sleep(loop_seconds)
