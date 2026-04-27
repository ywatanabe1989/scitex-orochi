"""``scitex-orochi dispatch {run,status}`` subcommands.

Operator-side complement to the server-side auto-dispatch (PR #334).

* ``dispatch run --head <host> [--todo N]`` — forces an immediate
  auto-dispatch DM to ``head-<host>`` via the hub's
  ``POST /api/auto-dispatch/fire/`` endpoint, bypassing the streak /
  cooldown gate. Optional ``--todo`` overrides the pick-helper result
  with a specific issue number.

* ``dispatch status`` — GET ``/api/auto-dispatch/status/``: shows per-head
  ``idle_streak``, ``last_fire_at`` (ISO), ``cooldown_active``, and
  ``cooldown_remaining_s`` so the operator can see why a head is or
  isn't being auto-dispatched right now.

Auth: workspace token (env ``SCITEX_OROCHI_TOKEN`` or ``--token``), same
as every other token-authenticated CLI verb. Hub defaults to
``https://scitex-orochi.com``.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError

import click

from ._host_ops import load_workspace_token

DEFAULT_HUB = "https://scitex-orochi.com"


@click.group("dispatch")
def dispatch() -> None:
    """Operator-side control of the server-side auto-dispatch."""


def _resolve_token(token: str | None) -> str:
    resolved = token or load_workspace_token()
    if not resolved:
        raise click.ClickException(
            "no SCITEX_OROCHI_TOKEN (env, --token, or dotfiles secret)."
        )
    return resolved


def _http_json(
    method: str,
    url: str,
    token: str,
    body: dict | None = None,
    timeout: int = 15,
) -> tuple[int, Any]:
    """Tiny stdlib HTTP-JSON client. Returns (status, parsed_body|text)."""
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}token={token}"
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "scitex-orochi-cli/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = _urllib_request.Request(
        full_url, data=data, headers=headers, method=method
    )
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.status
    except HTTPError as exc:
        # Try to read the body so the caller sees the server's error.
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = str(exc)
        try:
            return exc.code, json.loads(err_body)
        except (json.JSONDecodeError, ValueError):
            return exc.code, err_body
    except URLError as exc:
        raise click.ClickException(f"hub unreachable: {exc.reason}") from exc
    try:
        return code, json.loads(raw or "null")
    except json.JSONDecodeError:
        return code, raw


# ---------------------------------------------------------------------------
# dispatch run
# ---------------------------------------------------------------------------

@dispatch.command("run")
@click.option(
    "--head",
    required=True,
    help="Head host label (e.g. 'mba' → head-mba, or 'head-mba' directly).",
)
@click.option(
    "--todo",
    type=int,
    default=None,
    help="Specific issue number to dispatch (else the pick-helper chooses).",
)
@click.option(
    "--reason",
    default="operator-manual",
    show_default=True,
    help="Audit tag stored in the message metadata.",
)
@click.option(
    "--hub",
    envvar="SCITEX_OROCHI_URL",
    default=DEFAULT_HUB,
    show_default=True,
    help="Hub base URL [$SCITEX_OROCHI_URL].",
)
@click.option(
    "--token",
    envvar="SCITEX_OROCHI_TOKEN",
    default=None,
    help="Workspace token [$SCITEX_OROCHI_TOKEN].",
)
@click.pass_context
def dispatch_run(
    ctx: click.Context,
    head: str,
    todo: int | None,
    reason: str,
    hub: str,
    token: str | None,
) -> None:
    """Force an auto-dispatch DM to ``head-<host>`` now.

    Bypasses the heartbeat-path streak/cooldown gate. The head's
    ``AgentConsumer`` delivers it as a normal chat frame.
    """
    resolved = _resolve_token(token)
    body: dict[str, Any] = {"head": head, "reason": reason}
    if todo is not None:
        body["todo"] = int(todo)
    url = hub.rstrip("/") + "/api/auto-dispatch/fire/"
    status_code, payload = _http_json("POST", url, resolved, body=body)
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if status_code >= 400:
        if as_json:
            click.echo(
                json.dumps(
                    {"status": "error", "http": status_code, "body": payload},
                    separators=(",", ":"),
                )
            )
        else:
            click.echo(f"hub returned HTTP {status_code}: {payload}", err=True)
        sys.exit(1)
    if as_json:
        click.echo(json.dumps(payload, separators=(",", ":")))
        return
    # Human output
    if isinstance(payload, dict):
        click.echo(f"status:     {payload.get('status')}")
        click.echo(f"decision:   {payload.get('decision')}")
        click.echo(f"agent:      {payload.get('agent')}")
        click.echo(f"lane:       {payload.get('lane')}")
        pick = payload.get("pick") or {}
        if pick:
            click.echo(
                f"pick:       #{pick.get('number')} {pick.get('title')}"
            )
        else:
            click.echo("pick:       (none — head picks from own backlog)")
        click.echo(f"message_id: {payload.get('message_id')}")
    else:
        click.echo(str(payload))


# ---------------------------------------------------------------------------
# dispatch status
# ---------------------------------------------------------------------------

@dispatch.command("status")
@click.option(
    "--hub",
    envvar="SCITEX_OROCHI_URL",
    default=DEFAULT_HUB,
    show_default=True,
    help="Hub base URL [$SCITEX_OROCHI_URL].",
)
@click.option(
    "--token",
    envvar="SCITEX_OROCHI_TOKEN",
    default=None,
    help="Workspace token [$SCITEX_OROCHI_TOKEN].",
)
@click.pass_context
def dispatch_status(
    ctx: click.Context,
    hub: str,
    token: str | None,
) -> None:
    """Show per-head auto-dispatch streak + cooldown state."""
    resolved = _resolve_token(token)
    url = hub.rstrip("/") + "/api/auto-dispatch/status/"
    status_code, payload = _http_json("GET", url, resolved)
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if status_code >= 400:
        if as_json:
            click.echo(
                json.dumps(
                    {"status": "error", "http": status_code, "body": payload},
                    separators=(",", ":"),
                )
            )
        else:
            click.echo(f"hub returned HTTP {status_code}: {payload}", err=True)
        sys.exit(1)
    rows = payload if isinstance(payload, list) else []
    if as_json:
        click.echo(json.dumps(rows, separators=(",", ":")))
        return
    if not rows:
        click.echo("no head-* agents currently registered in this workspace.")
        return
    click.echo(
        f"{'agent':<28}  {'lane':<24}  {'streak':>6}  {'orochi_subagents':>9}  "
        f"{'cooldown':>8}  last_fire_at"
    )
    for r in rows:
        cd = "active" if r.get("cooldown_active") else "-"
        if r.get("cooldown_active"):
            cd = f"{int(r.get('cooldown_remaining_s') or 0)}s"
        click.echo(
            f"{str(r.get('agent', '')):<28}  "
            f"{str(r.get('lane', '')):<24}  "
            f"{int(r.get('idle_streak') or 0):>6}  "
            f"{int(r.get('orochi_subagent_count') or 0):>9}  "
            f"{cd:>8}  "
            f"{r.get('last_fire_at') or '-'}"
        )


__all__ = ["dispatch"]
