"""``scitex-orochi machine {heartbeat,resources} ...`` subcommands.

``heartbeat send``    — drop-in for ``scripts/client/agent_meta.py --push --once``.
                       Enumerate local tmux/screen agent sessions, collect their
                       metadata via ``agent_meta_pkg`` (the real implementation
                       already lives in the repo), and POST each entry to the
                       Orochi hub's ``/api/agents/register/`` endpoint.

``heartbeat status``  — GET the hub agents registry and print this host's canonical
                       payload (``head-<hostname>``) as JSON. Used as a lightweight
                       smoke test in lieu of the dashboard.

``resources show``    — Snapshot local CPU / RAM / Storage / GPU in the
                       ``N cores`` / ``N/M GB`` / ``N/M TB`` format that the
                       Machines tab renders (PR #327 parity, ywatanabe msg#16215).
                       Reads via ``agent_meta_pkg._metrics.collect_machine_metrics``.

All commands emit NDJSON on stdout and human-readable progress on
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
    """Heartbeat publishing + inspection."""


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
    help="Single push cycle (default).",
)
@click.option("--verbose", is_flag=True, help="Print per-agent push status to stderr.")
def heartbeat_send(
    url: str | None,
    token: str | None,
    once: bool,  # noqa: ARG001 - preserved for flag parity
    verbose: bool,
) -> None:
    """Enumerate local agents, collect their metadata, POST to the hub."""
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
# machine heartbeat send-host — wheel-resident host-level pusher
# ---------------------------------------------------------------------------


@heartbeat.command("send-host")
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
    "--machine",
    "machine_arg",
    envvar="SCITEX_OROCHI_MACHINE",
    default=None,
    help="Canonical machine name [$SCITEX_OROCHI_MACHINE]; defaults to short hostname.",
)
def heartbeat_send_host(
    url: str | None,
    token: str | None,
    machine_arg: str | None,
) -> None:
    """POST a single host-level heartbeat (machine metrics, no agents).

    Lets hosts that don't run any local tmux/screen agents populate
    their Machines tab card with live cpu/mem/disk/gpu numbers. Synthetic
    agent name is ``host-<machine>``. Cross-platform metrics via
    ``scitex_resource.get_metrics()``.
    """
    import json as _json
    import os
    import socket
    from urllib import request as _ur

    try:
        from scitex_resource import get_metrics
    except ImportError as exc:
        raise click.ClickException(
            "scitex-resource not installed; pip install -U scitex-resource"
        ) from exc

    base = url or os.environ.get("SCITEX_OROCHI_URL_HTTP", "https://scitex-orochi.com")
    tok = token or load_workspace_token()
    if not tok:
        raise click.ClickException(
            "no SCITEX_OROCHI_TOKEN (env, --token, or dotfiles secret)."
        )
    machine = (machine_arg or socket.gethostname()).split(".", 1)[0]
    metrics = get_metrics(gpu=True)
    payload = {
        "token": tok,
        "name": f"host-{machine}",
        "machine": machine,
        "status": "online",
        "metrics": metrics,
    }
    data = _json.dumps(payload).encode("utf-8")
    req = _ur.Request(
        base.rstrip("/") + "/api/agents/register/",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _ur.urlopen(req, timeout=5) as resp:
            status = resp.status
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"host push failed: {exc}") from exc
    click.echo(
        _json.dumps({"machine": machine, "status": status, "metric_keys": len(metrics)})
    )


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
        raise click.ClickException(f"hub HTTP {exc.code}: {exc.reason}") from exc
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


# ---------------------------------------------------------------------------
# machine resources show
# ---------------------------------------------------------------------------


@machine.group("resources")
def resources() -> None:
    """Local host resource snapshot (CPU / RAM / Storage / GPU)."""


def _import_metrics():
    """Return ``collect_machine_metrics`` from ``agent_meta_pkg._metrics``.

    Same bootstrapping dance as ``_import_agent_meta_pkg`` above: falls
    back to prepending ``scripts/client`` to ``sys.path`` so non-installed
    checkouts work.
    """
    try:
        from agent_meta_pkg._metrics import (  # type: ignore[import-not-found]
            collect_machine_metrics,
        )

        return collect_machine_metrics
    except ImportError:
        pass
    from ._host_ops import _repo_root_candidate  # local import to avoid cycle

    scripts_client = _repo_root_candidate() / "scripts" / "client"
    if scripts_client.is_dir() and str(scripts_client) not in sys.path:
        sys.path.insert(0, str(scripts_client))
    try:
        from agent_meta_pkg._metrics import (  # type: ignore[import-not-found]
            collect_machine_metrics,
        )

        return collect_machine_metrics
    except ImportError as exc:  # pragma: no cover - defensive
        raise click.ClickException(
            "agent_meta_pkg._metrics not importable — ensure you're in a "
            "repo checkout or set SCITEX_OROCHI_REPO_ROOT."
        ) from exc


def _fmt_cores(n: int | None) -> str:
    if not n:
        return "-"
    return f"{int(n)} cores"


def _fmt_gb_ratio(used_mb: int | None, total_mb: int | None) -> str:
    if not used_mb or not total_mb:
        return "-"
    used_gb = float(used_mb) / 1024.0
    total_gb = float(total_mb) / 1024.0
    return f"{used_gb:.1f}/{total_gb:.1f} GB"


def _fmt_tb_ratio(used_mb: int | None, total_mb: int | None) -> str:
    if not used_mb or not total_mb:
        return "-"
    used_tb = float(used_mb) / 1024.0 / 1024.0
    total_tb = float(total_mb) / 1024.0 / 1024.0
    return f"{used_tb:.2f}/{total_tb:.2f} TB"


def _fmt_gpu(gpus: list[dict]) -> str:
    if not gpus:
        return "n/a"
    used = sum(float(g.get("memory_used_mb") or 0) for g in gpus)
    total = sum(float(g.get("memory_total_mb") or 0) for g in gpus)
    if total <= 0:
        return f"{len(gpus)}x"
    used_gb = used / 1024.0
    total_gb = total / 1024.0
    return f"{len(gpus)}x — VRAM {used_gb:.1f}/{total_gb:.1f} GB"


@resources.command("show")
@click.option(
    "--pretty",
    is_flag=True,
    help="Pretty-print the JSON (default: single-line NDJSON).",
)
@click.pass_context
def resources_show(ctx: click.Context, pretty: bool) -> None:
    """Print this host's resource snapshot (matches Machines-tab display).

    Emits the shape::

        {
          "host": "<shortname>",
          "display": {
            "cpu": "N cores",
            "ram": "N/M GB",
            "storage": "N/M TB",
            "gpu":  "N x — VRAM N/M GB"   # or "n/a"
          },
          "raw": { ...full metrics dict... }
        }

    ``--json`` (top-level) or ``--pretty`` honoured. Human output prints
    the four lines in a compact key:value format so operators can eyeball
    the values without piping through jq.
    """
    collect = _import_metrics()
    try:
        metrics = collect()
    except Exception as exc:  # noqa: BLE001 - must degrade
        raise click.ClickException(f"collect_machine_metrics failed: {exc}") from exc

    display = {
        "cpu": _fmt_cores(metrics.get("cpu_count")),
        "ram": _fmt_gb_ratio(metrics.get("mem_used_mb"), metrics.get("mem_total_mb")),
        "storage": _fmt_tb_ratio(
            metrics.get("disk_used_mb"), metrics.get("disk_total_mb")
        ),
        "gpu": _fmt_gpu(metrics.get("gpus") or []),
    }
    payload = {
        "host": resolve_self_host(),
        "display": display,
        "raw": metrics,
    }
    as_json = bool(ctx.obj and ctx.obj.get("json"))
    if as_json or pretty:
        click.echo(
            json.dumps(payload, indent=2 if pretty else None, default=str)
            if pretty
            else json.dumps(payload, separators=(",", ":"), default=str)
        )
        return
    # Human output — the four Machines-tab lines.
    click.echo(f"host:    {payload['host']}")
    click.echo(f"CPU:     {display['cpu']}")
    click.echo(f"RAM:     {display['ram']}")
    click.echo(f"Storage: {display['storage']}")
    click.echo(f"GPU:     {display['gpu']}")


__all__ = ["machine"]
