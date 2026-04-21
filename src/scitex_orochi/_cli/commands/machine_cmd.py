"""``scitex-orochi machine heartbeat {send,status}`` subcommands.

``send``  — drop-in for ``scripts/client/agent_meta.py --push --once``.
            Enumerate local tmux/screen agent sessions, collect their
            metadata via ``agent_meta_pkg`` (the real implementation
            already lives in the repo), and POST each entry to the
            Orochi hub's ``/api/agents/register/`` endpoint.

``status`` — GET the hub agents registry and print this host's canonical
            payload (``head-<hostname>``) as JSON. Used as a lightweight
            smoke test in lieu of the dashboard.

Both commands emit NDJSON on stdout and human-readable progress on
stderr when ``--verbose``.
"""

from __future__ import annotations

import json
import socket
import sys
from typing import Any
from urllib import request as _urllib_request
from urllib.error import HTTPError, URLError

import click

from ._host_ops import load_workspace_token, resolve_self_host

# ---------------------------------------------------------------------------
# ``agent_meta_pkg`` bootstrapping
# ---------------------------------------------------------------------------

def _import_agent_meta_pkg():
    """Return (push_all, collect) from ``agent_meta_pkg`` regardless of
    whether the repo's ``scripts/client/`` is on sys.path yet."""
    try:
        from agent_meta_pkg import collect, push_all  # type: ignore[import-not-found]

        return push_all, collect
    except ImportError:
        pass
    from ._host_ops import _repo_root_candidate  # local import to avoid cycle

    scripts_client = _repo_root_candidate() / "scripts" / "client"
    if scripts_client.is_dir() and str(scripts_client) not in sys.path:
        sys.path.insert(0, str(scripts_client))
    try:
        from agent_meta_pkg import collect, push_all  # type: ignore[import-not-found]

        return push_all, collect
    except ImportError as exc:  # pragma: no cover - defensive
        raise click.ClickException(
            "agent_meta_pkg not importable — ensure you're in a repo "
            "checkout or set SCITEX_OROCHI_REPO_ROOT."
        ) from exc


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@click.group("machine")
def machine() -> None:
    """Host-level operations (heartbeat push, registry inspection, ...)."""


@machine.group("heartbeat")
def heartbeat() -> None:
    """Heartbeat publishing + inspection (replaces ``agent_meta.py --push``)."""


# ---------------------------------------------------------------------------
# machine heartbeat send
# ---------------------------------------------------------------------------

@heartbeat.command("send")
@click.option(
    "--url",
    envvar="SCITEX_OROCHI_URL_HTTP",
    default=None,
    help="Hub URL [$SCITEX_OROCHI_URL_HTTP, default https://scitex-orochi.com].",
)
@click.option(
    "--token",
    envvar="SCITEX_OROCHI_TOKEN",
    default=None,
    help="Workspace token [$SCITEX_OROCHI_TOKEN].",
)
@click.option(
    "--once",
    "once",
    is_flag=True,
    default=True,
    help="Single push cycle (default, matches ``agent_meta.py --push --once``).",
)
@click.option("--verbose", is_flag=True, help="Print per-agent push status to stderr.")
def heartbeat_send(
    url: str | None,
    token: str | None,
    once: bool,  # noqa: ARG001 - preserved for flag parity
    verbose: bool,
) -> None:
    """Enumerate local agents, collect their metadata, POST to the hub.

    Drop-in replacement for ``scripts/client/agent_meta.py --push --once``.
    Logic delegates to ``agent_meta_pkg.push_all`` so changes there stay
    visible without a code change here.
    """
    push_all, _collect = _import_agent_meta_pkg()
    resolved_token = token or load_workspace_token()
    try:
        n = push_all(url=url, token=resolved_token)
    except Exception as exc:  # noqa: BLE001 - daemon must not crash
        raise click.ClickException(f"push_all failed: {exc}") from exc
    if verbose:
        click.echo(
            f"[machine heartbeat send] pushed={n} url={url or 'default'}",
            err=True,
        )
    click.echo(json.dumps({"pushed": n}, separators=(",", ":")))


# ---------------------------------------------------------------------------
# machine heartbeat status
# ---------------------------------------------------------------------------

@heartbeat.command("status")
@click.option(
    "--hub",
    envvar="SCITEX_OROCHI_URL",
    default="https://scitex-orochi.com",
    show_default=True,
    help="Hub base URL [$SCITEX_OROCHI_URL].",
)
@click.option(
    "--token",
    envvar="SCITEX_OROCHI_TOKEN",
    default=None,
    help="Workspace token [$SCITEX_OROCHI_TOKEN].",
)
@click.option(
    "--agent",
    default=None,
    help="Agent name to look up (default: head-<this host>).",
)
@click.option(
    "--pretty",
    is_flag=True,
    help="Pretty-print the JSON (default: single-line).",
)
def heartbeat_status(
    hub: str,
    token: str | None,
    agent: str | None,
    pretty: bool,
) -> None:
    """Print the hub registry entry for an agent (default head-<hostname>)."""
    resolved_token = token or load_workspace_token()
    if not resolved_token:
        raise click.ClickException(
            "no SCITEX_OROCHI_TOKEN (env, --token, or dotfiles secret)."
        )
    name = agent or f"head-{resolve_self_host()}"
    endpoint = hub.rstrip("/") + f"/api/agents/?token={resolved_token}"
    req = _urllib_request.Request(
        endpoint,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "scitex-orochi-cli/1.0",
        },
    )
    try:
        with _urllib_request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace") or "[]"
            code = resp.status
    except HTTPError as exc:
        raise click.ClickException(
            f"hub HTTP {exc.code}: {exc.reason}"
        ) from exc
    except URLError as exc:
        raise click.ClickException(f"hub unreachable: {exc.reason}") from exc

    if code != 200:
        raise click.ClickException(f"hub returned HTTP {code}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"hub returned non-JSON: {exc}") from exc
    agents = data if isinstance(data, list) else []
    payload: dict[str, Any] | None = None
    for a in agents:
        if isinstance(a, dict) and a.get("name") == name:
            payload = a
            break
    if payload is None:
        envelope = {
            "agent": name,
            "found": False,
            "hostname": socket.gethostname(),
        }
        click.echo(json.dumps(envelope, separators=(",", ":")))
        sys.exit(1)
    if pretty:
        click.echo(json.dumps(payload, indent=2, sort_keys=False))
    else:
        click.echo(json.dumps(payload, separators=(",", ":")))


__all__ = ["machine"]
