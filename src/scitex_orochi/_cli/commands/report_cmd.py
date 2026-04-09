"""CLI commands: orochi report — emit activity/heartbeat events to the hub.

These commands are designed to be called from Claude Code hooks
(PreToolUse, PostToolUse, Notification, SessionStart, Stop) so the
hub gets ground-truth liveness data without relying on agent
self-reporting at the message layer.

Distribution:
    - Installed with `pip install scitex-orochi`
    - Hooks reference it as `orochi report ...`
    - Auth via SCITEX_OROCHI_TOKEN env var

Examples:
    orochi report activity --tool Edit --task "implement #143"
    orochi report subagent-start --name explore --description "find files"
    orochi report subagent-end --name explore --result "5 matches"
    orochi report stuck --reason "permission-prompt"
"""

from __future__ import annotations

import json
import os
import platform
import sys
import urllib.error
import urllib.request

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER


def _agent_name() -> str:
    """Determine the agent's display name from env."""
    return (
        os.environ.get("SCITEX_OROCHI_AGENT")
        or os.environ.get("CLAUDE_AGENT_ROLE")
        or f"unknown@{platform.node().split('.')[0]}"
    )


def _post_event(path: str, payload: dict, ctx: click.Context) -> dict:
    """POST an event payload to the hub. Returns parsed response or error dict."""
    host = ctx.obj.get("host", "127.0.0.1")
    port = ctx.obj.get("dashboard_port") or 8559
    token = os.environ.get("SCITEX_OROCHI_TOKEN") or os.environ.get(
        "SCITEX_OROCHI_ADMIN_TOKEN", ""
    )
    url = f"http://{host}:{port}{path}"
    if token:
        url += f"?token={token}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}


@click.group(name="report")
def report() -> None:
    """Emit hook-driven liveness/activity events to the Orochi hub."""


# ── activity ───────────────────────────────────────────────────────
@report.command()
@click.option("--tool", default="", help="Tool name (e.g. Edit, Bash).")
@click.option("--task", default="", help="Current task description (becomes current_task).")
@click.option("--summary", default="", help="Optional one-line summary of the action.")
@click.option("--phase", type=click.Choice(["pre", "post"]), default="post")
@click.pass_context
def activity(
    ctx: click.Context, tool: str, task: str, summary: str, phase: str
) -> None:
    """Report a tool-use activity event (most common hook).

    Designed to be called from a Claude Code PostToolUse hook with
    `--tool $TOOL_NAME`. Updates the agent's last_action timestamp in
    the hub registry so the watchdog knows the agent is making progress.
    """
    payload = {
        "agent": _agent_name(),
        "tool": tool,
        "phase": phase,
        "task": task,
        "summary": summary or tool,
    }
    result = _post_event("/api/events/tool-use/", payload, ctx)
    click.echo(json.dumps(result))
    if "error" in result:
        sys.exit(1)


# ── stuck ───────────────────────────────────────────────────────────
@report.command()
@click.option("--reason", required=True, help="Reason the agent is stuck.")
@click.pass_context
def stuck(ctx: click.Context, reason: str) -> None:
    """Report that the agent is stuck (e.g. permission prompt detected).

    Designed for use from a Notification hook that pattern-matches
    common stuck states. Caduceus will pick up the alert and either
    auto-respond or escalate.
    """
    payload = {
        "agent": _agent_name(),
        "tool": "stuck",
        "phase": "post",
        "summary": f"STUCK: {reason}",
        "task": f"BLOCKED: {reason}",
    }
    result = _post_event("/api/events/tool-use/", payload, ctx)
    click.echo(json.dumps(result))
    if "error" in result:
        sys.exit(1)


# ── heartbeat ───────────────────────────────────────────────────────
@report.command()
@click.pass_context
def heartbeat(ctx: click.Context) -> None:
    """Send a passive heartbeat (no task change), useful for periodic crons."""
    payload = {
        "agent": _agent_name(),
        "tool": "heartbeat",
        "phase": "post",
        "summary": "heartbeat",
    }
    result = _post_event("/api/events/tool-use/", payload, ctx)
    click.echo(json.dumps(result))
    if "error" in result:
        sys.exit(1)
