"""``scitex-orochi message react {add,remove}`` (msg#16489).

Thin HTTP client over the existing ``/api/reactions/`` endpoint in
``hub/views/api/_reactions.py`` (POST = add, DELETE = remove). The same
endpoint backs the web dashboard (``hub/static/hub/reactions.js``) and
the MCP ``react`` tool (``ts/src/tools/messaging.ts``); this CLI is the
shell-script / non-Claude client-side convenience.

Auth: workspace token (``$SCITEX_OROCHI_TOKEN``, ``--token``, or
dotfiles secret file) — same pattern as ``dispatch`` and ``machine``.
The endpoint derives the workspace from the token; ``--workspace`` is
accepted as an advisory override (forwarded in the body; server ignores
today, honoured if/when a future PR adds cross-workspace moderation).

The ``reactor`` identity is passed in the body as the agent name
(``$SCITEX_OROCHI_AGENT`` → fallback ``platform.node()``); the hub
stores reactor+emoji+message as a unique tuple so re-adding is a
no-op (``action: "existed"``) and removing a non-existent reaction is
also a no-op (``action: "not_found"``).

Emoji encoding: pure JSON body — emoji characters are serialised as
UTF-8 inside the JSON string, which Python's ``json.dumps`` handles
natively. No URL-encoding is required because the emoji never appears
in the path or query string (unlike the REST sketch in the original
spec where ``DELETE /api/messages/<id>/reactions/<emoji>/`` was
considered — that flavour does not exist on the hub and is not needed
given the body-based endpoint).
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER, get_agent_name

from ._host_ops import load_workspace_token

DEFAULT_HUB = "https://scitex-orochi.com"


@click.group(
    "react",
    short_help="Add/remove emoji reactions on a message",
    help=(
        "Add or remove emoji reactions on a message (add, remove).\n"
        "\n"
        "The MCP tool ``mcp__scitex-orochi__react`` provides the same "
        "functionality for in-Claude use; this CLI is aimed at shell "
        "scripts and non-Claude clients."
    ),
)
def react() -> None:
    """Add or remove emoji reactions on a message."""


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
    """Tiny stdlib HTTP-JSON client (same shape as dispatch_cmd._http_json).

    Returns (status_code, parsed_body_or_text). Never raises on HTTP
    errors — the caller maps status → exit code itself so ``--json``
    mode can still emit a structured error payload.
    """
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
    req = _urllib_request.Request(full_url, data=data, headers=headers, method=method)
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.status
    except HTTPError as exc:
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


def _run_reaction(
    ctx: click.Context,
    *,
    action: str,
    msg_id: int,
    emoji: str,
    workspace: str | None,
    hub: str,
    token: str | None,
) -> None:
    """Shared body for ``add`` and ``remove``.

    ``action`` is the client-facing label (``"add"``/``"remove"``).
    The HTTP method is POST for add and DELETE for remove — matching
    the existing ``api_reactions`` view.
    """
    resolved = _resolve_token(token)
    method = "POST" if action == "add" else "DELETE"
    body: dict[str, Any] = {
        "message_id": int(msg_id),
        "emoji": emoji,
        "reactor": get_agent_name(),
    }
    if workspace:
        # Forwarded for future cross-workspace moderation; server
        # currently derives workspace from the token and ignores this.
        body["workspace"] = workspace

    url = hub.rstrip("/") + "/api/reactions/"
    status_code, payload = _http_json(method, url, resolved, body=body)
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    if status_code >= 400:
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "status": "error",
                        "http": status_code,
                        "body": payload,
                        "msg_id": int(msg_id),
                        "emoji": emoji,
                        "action": action,
                    },
                    separators=(",", ":"),
                )
            )
        else:
            # Surface the hub's error body verbatim on stderr.
            click.echo(f"hub returned HTTP {status_code}: {payload}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "ok",
                    "msg_id": int(msg_id),
                    "emoji": emoji,
                    "action": action,
                    "hub_action": (
                        payload.get("action") if isinstance(payload, dict) else None
                    ),
                },
                separators=(",", ":"),
                ensure_ascii=False,
            )
        )
        return

    # Human-readable
    hub_action = payload.get("action") if isinstance(payload, dict) else None
    if action == "add":
        note = {
            "added": f"reacted {emoji} to msg#{msg_id}",
            "existed": f"already reacted {emoji} to msg#{msg_id} (no-op)",
        }.get(hub_action or "", f"reacted {emoji} to msg#{msg_id}")
    else:
        note = {
            "removed": f"removed {emoji} from msg#{msg_id}",
            "not_found": f"no {emoji} reaction on msg#{msg_id} (no-op)",
        }.get(hub_action or "", f"removed {emoji} from msg#{msg_id}")
    click.echo(note)


# ---------------------------------------------------------------------------
# react add
# ---------------------------------------------------------------------------


@react.command(
    "add",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi message react add 12345 👍\n"
    + "  scitex-orochi --json message react add 12345 ✅\n"
    + "  scitex-orochi message react add 12345 :+1: --workspace scitex\n",
)
@click.argument("msg_id", type=int)
@click.argument("emoji")
@click.option(
    "--workspace",
    envvar="SCITEX_OROCHI_WORKSPACE",
    default=None,
    help=(
        "Workspace slug override [$SCITEX_OROCHI_WORKSPACE]. Defaults to "
        "the workspace derived from the token."
    ),
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
def react_add(
    ctx: click.Context,
    msg_id: int,
    emoji: str,
    workspace: str | None,
    hub: str,
    token: str | None,
) -> None:
    """Add a reaction EMOJI to message MSG_ID."""
    _run_reaction(
        ctx,
        action="add",
        msg_id=msg_id,
        emoji=emoji,
        workspace=workspace,
        hub=hub,
        token=token,
    )


# ---------------------------------------------------------------------------
# react remove
# ---------------------------------------------------------------------------


@react.command(
    "remove",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi message react remove 12345 👍\n"
    + "  scitex-orochi --json message react remove 12345 ✅\n",
)
@click.argument("msg_id", type=int)
@click.argument("emoji")
@click.option(
    "--workspace",
    envvar="SCITEX_OROCHI_WORKSPACE",
    default=None,
    help=(
        "Workspace slug override [$SCITEX_OROCHI_WORKSPACE]. Defaults to "
        "the workspace derived from the token."
    ),
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
def react_remove(
    ctx: click.Context,
    msg_id: int,
    emoji: str,
    workspace: str | None,
    hub: str,
    token: str | None,
) -> None:
    """Remove a reaction EMOJI from message MSG_ID."""
    _run_reaction(
        ctx,
        action="remove",
        msg_id=msg_id,
        emoji=emoji,
        workspace=workspace,
        hub=hub,
        token=token,
    )


__all__ = ["react", "react_add", "react_remove"]
