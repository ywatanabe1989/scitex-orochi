"""CLI commands: workspace management (create, delete, list, invites).

Phase 1d Step B additionally exposes an empty ``workspace`` click group —
the noun dispatcher that will host ``workspace create/delete/list`` once
Step C migrates the flat verbs. The group is deliberately empty in
Step B; it co-exists with the legacy flat commands.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability
from scitex_orochi._cli._helpers import EXAMPLES_HEADER


# ── Phase 1d Step B: empty noun dispatcher ─────────────────────────────
# No verbs are registered under this group in Step B. Step C migrates
# the flat ``create-workspace / delete-workspace / list-workspaces``
# commands into ``workspace create / delete / list``.
@click.group(
    "workspace",
    short_help="Manage workspaces",
    help="Manage workspaces (create, delete, list).",
)
def workspace() -> None:
    """Workspace-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(workspace)


# ── HTTP helper ───────────────────────────────────────────────────


def _api_request(
    ctx: click.Context,
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
) -> dict:
    """Perform a synchronous HTTP request to the Orochi REST API.

    Uses only urllib (no extra dependency).  Returns the parsed JSON
    response body or raises ``click.ClickException`` on failure.
    """
    base_url = f"http://{ctx.obj['host']}:{ctx.obj['port']}"
    url = f"{base_url}{path}"

    admin_token = (
        token
        or ctx.obj.get("admin_token")
        or os.environ.get("SCITEX_OROCHI_ADMIN_TOKEN", "")
    )

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if admin_token:
        headers["Authorization"] = f"Bearer {admin_token}"

    data = json.dumps(body).encode() if body is not None else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode() if exc.fp else str(exc)
        raise click.ClickException(
            f"HTTP {exc.code} from {method} {path}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise click.ClickException(f"Cannot reach {url}: {exc.reason}") from exc


def _get_admin_token(ctx: click.Context) -> str:
    """Resolve admin token from context or environment."""
    token = ctx.obj.get("admin_token") or os.environ.get(
        "SCITEX_OROCHI_ADMIN_TOKEN", ""
    )
    if not token:
        raise click.ClickException(
            "Admin token required.  Set SCITEX_OROCHI_ADMIN_TOKEN or "
            "pass --admin-token to the top-level command."
        )
    return token


# ── create-workspace ──────────────────────────────────────────────


@click.command(
    "create-workspace",
    epilog=EXAMPLES_HEADER + "  scitex-orochi create-workspace 'my-lab'"
    " --channels '#general,#research'\n" + "  scitex-orochi create-workspace 'ci-bots'"
    " --description 'CI agents workspace'\n",
)
@click.argument("name")
@click.option("--description", default=None, help="Workspace description.")
@click.option(
    "--channels",
    default=None,
    help="Comma-separated default channels (e.g. '#general,#research').",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def create_workspace(
    ctx: click.Context,
    name: str,
    description: str | None,
    channels: str | None,
    as_json: bool,
) -> None:
    """Create a new workspace."""
    _get_admin_token(ctx)

    payload: dict = {"name": name}
    if description is not None:
        payload["description"] = description
    if channels is not None:
        payload["channels"] = [ch.strip() for ch in channels.split(",") if ch.strip()]

    result = _api_request(ctx, "POST", "/api/workspaces", body=payload)

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        ws_id = result.get("id", "?")
        ws_token = result.get("token", "?")
        click.echo(f"Workspace created: {name}")
        click.echo(f"  ID:    {ws_id}")
        click.echo(f"  Token: {ws_token}")
        if channels:
            click.echo(f"  Channels: {channels}")


# ── delete-workspace ──────────────────────────────────────────────


def _confirm_or_fail(workspace_id: str, yes: bool) -> None:
    """Require --yes for non-interactive use; prompt when TTY is available."""
    if yes:
        return
    if not sys.stdin.isatty():
        raise click.ClickException(
            f"Refusing to delete workspace '{workspace_id}' without confirmation.\n"
            f"Use --yes to skip confirmation in non-interactive mode."
        )
    click.confirm(
        f"Delete workspace '{workspace_id}'?  This cannot be undone.",
        abort=True,
    )


@click.command(
    "delete-workspace",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi delete-workspace ws_abc123 --yes\n"
    + "  scitex-orochi delete-workspace ws_abc123 --json --yes\n",
)
@click.argument("workspace_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--yes", is_flag=True, help="Skip confirmation (required non-interactive)."
)
@click.pass_context
def delete_workspace(
    ctx: click.Context,
    workspace_id: str,
    as_json: bool,
    yes: bool,
) -> None:
    """Delete a workspace by ID."""
    _get_admin_token(ctx)
    _confirm_or_fail(workspace_id, yes)

    result = _api_request(ctx, "DELETE", f"/api/workspaces/{workspace_id}")

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Workspace deleted: {workspace_id}")


# ── list-workspaces ───────────────────────────────────────────────


@click.command(
    "list-workspaces",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi list-workspaces\n"
    + "  scitex-orochi list-workspaces --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def list_workspaces(ctx: click.Context, as_json: bool) -> None:
    """List all workspaces."""
    result = _api_request(ctx, "GET", "/api/workspaces")

    workspaces = result if isinstance(result, list) else result.get("workspaces", [])

    if as_json:
        click.echo(json.dumps(workspaces, indent=2))
    else:
        if not workspaces:
            click.echo("No workspaces found.")
            return
        for ws in workspaces:
            ws_id = ws.get("id", "?")
            ws_name = ws.get("name", "?")
            ws_desc = ws.get("description", "")
            line = f"  {ws_id}  {ws_name}"
            if ws_desc:
                line += f"  -- {ws_desc}"
            click.echo(line)


# ── create-invite ─────────────────────────────────────────────────


@click.command(
    "create-invite",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi create-invite ws_abc123\n"
    + "  scitex-orochi create-invite ws_abc123 --role admin --max-uses 5\n"
    + "  scitex-orochi create-invite ws_abc123 --expires-hours 48 --json\n",
)
@click.argument("workspace_id")
@click.option(
    "--role", default="member", help="Role for invited user (default: member)."
)
@click.option(
    "--max-uses",
    default=0,
    type=int,
    help="Maximum uses (0 = unlimited, default: 0).",
)
@click.option(
    "--expires-hours",
    default=0,
    type=int,
    help="Hours until expiry (0 = never, default: 0).",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def create_invite(
    ctx: click.Context,
    workspace_id: str,
    role: str,
    max_uses: int,
    expires_hours: int,
    as_json: bool,
) -> None:
    """Create an invite link for a workspace."""
    _get_admin_token(ctx)

    payload: dict = {"role": role}
    if max_uses > 0:
        payload["max_uses"] = max_uses
    if expires_hours > 0:
        payload["expires_hours"] = expires_hours

    result = _api_request(
        ctx, "POST", f"/api/workspaces/{workspace_id}/invites", body=payload
    )

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        code = result.get("code", "?")
        invite_role = result.get("role", role)
        click.echo(f"Invite created for workspace {workspace_id}")
        click.echo(f"  Code:  {code}")
        click.echo(f"  Role:  {invite_role}")
        if max_uses > 0:
            click.echo(f"  Max uses: {max_uses}")
        if expires_hours > 0:
            click.echo(f"  Expires in: {expires_hours}h")


# ── list-invites ──────────────────────────────────────────────────


@click.command(
    "list-invites",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi list-invites ws_abc123\n"
    + "  scitex-orochi list-invites ws_abc123 --json\n",
)
@click.argument("workspace_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def list_invites(ctx: click.Context, workspace_id: str, as_json: bool) -> None:
    """List invites for a workspace."""
    result = _api_request(ctx, "GET", f"/api/workspaces/{workspace_id}/invites")

    invites = result if isinstance(result, list) else result.get("invites", [])

    if as_json:
        click.echo(json.dumps(invites, indent=2))
    else:
        if not invites:
            click.echo(f"No invites for workspace {workspace_id}.")
            return
        for inv in invites:
            code = inv.get("code", "?")
            inv_role = inv.get("role", "?")
            uses = inv.get("uses", 0)
            max_u = inv.get("max_uses", 0)
            uses_str = f"{uses}/{max_u}" if max_u else f"{uses}/unlimited"
            click.echo(f"  {code}  role={inv_role}  uses={uses_str}")
