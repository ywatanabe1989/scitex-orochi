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
        "context_pct": status.get("context_pct"),
        "current_task": status.get("current_task") or "",
        "current_tool": status.get("current_tool") or "",
        "subagent_count": int(status.get("subagent_count") or 0),
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
        "pane_tail_block": status.get("pane_text") or "",
        "pane_state": status.get("pane_state") or "",
        "stuck_prompt_text": status.get("stuck_prompt_text") or "",
        # Workspace files.
        "claude_md": status.get("claude_md") or "",
        "claude_md_head": (status.get("claude_md") or "").splitlines()[0][:120]
        if status.get("claude_md")
        else "",
        "mcp_json": status.get("mcp_json") or "",
        # Claude Code hook-captured events (new — forwarded as-is).
        "recent_tools": status.get("recent_tools") or [],
        "recent_prompts": status.get("recent_prompts") or [],
        "agent_calls": status.get("agent_calls") or [],
        "background_tasks": status.get("background_tasks") or [],
        "tool_counts": status.get("tool_counts") or {},
        # Accounting.
        "account_email": status.get("account_email") or "",
        "version": status.get("version") or "",
    }
    if channels:
        body["channels"] = list(channels)
    return body


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


@click.command("heartbeat-push")
@click.argument("name", required=True)
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
    name: str,
    token: str,
    hub: str,
    channels: tuple[str, ...],
    loop_seconds: int,
    verbose: bool,
) -> None:
    """Push one (or a loop of) heartbeat to the Orochi hub from
    scitex-agent-container's ``status`` CLI output.

    The pusher is deterministic: it shells out to
    ``scitex-agent-container status <name> --json`` and POSTs the result
    (plus token + optional channel override) to
    ``/api/agents/register/``. No LLM, no MCP — just a subprocess and
    an HTTP request.
    """
    ch_list = list(channels) if channels else None

    def _once() -> int:
        status = _run_agent_container_status(name)
        body = _wrap_with_orochi_fields(status, token=token, channels=ch_list)
        code, resp = _post_register(hub, body)
        if verbose:
            click.echo(
                f"[heartbeat-push] {name} -> {hub} HTTP {code} "
                f"pane_state={body.get('pane_state')} "
                f"context={body.get('context_pct')} "
                f"quota_5h={body.get('quota_5h_used_pct')} "
                f"tools={sum((body.get('tool_counts') or {}).values())}",
                err=True,
            )
        if code >= 400:
            click.echo(resp[:500], err=True)
            return 1
        return 0

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
