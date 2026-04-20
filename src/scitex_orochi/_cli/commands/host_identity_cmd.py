"""CLI: scitex-orochi host-identity {show, init, check}.

Manages the per-machine identity file used by the local-vs-remote
resolver in :mod:`scitex_orochi._host_identity`.
"""

from __future__ import annotations

import json
import socket
import sys

import click
import yaml

from scitex_orochi._host_identity import (
    HOST_IDENTITY_PATH,
    is_local,
    load_host_identity,
    reset_cache,
)


@click.group("host-identity")
def host_identity() -> None:
    """Manage this machine's identity (~/.scitex/orochi/host-identity.yaml)."""


@host_identity.command("show")
@click.pass_context
def show(ctx: click.Context) -> None:
    """Show the current host-identity (file + auto-derived defaults merged)."""
    reset_cache()
    data = load_host_identity()
    payload = {
        "path": str(HOST_IDENTITY_PATH),
        "exists": HOST_IDENTITY_PATH.exists(),
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "aliases": data["aliases"],
    }
    if ctx.obj.get("json"):
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"path:     {payload['path']}")
    click.echo(f"exists:   {payload['exists']}")
    click.echo(f"hostname: {payload['hostname']}")
    click.echo(f"fqdn:     {payload['fqdn']}")
    click.echo("aliases:")
    for a in payload["aliases"]:
        click.echo(f"  - {a}")


@host_identity.command("init")
@click.option(
    "--alias",
    "extra_aliases",
    multiple=True,
    help="Additional alias to record (repeatable, e.g. SSH alias).",
)
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
def init(extra_aliases: tuple[str, ...], force: bool) -> None:
    """Create ~/.scitex/orochi/host-identity.yaml seeded with defaults."""
    if HOST_IDENTITY_PATH.exists() and not force:
        click.echo(
            f"Refusing to overwrite {HOST_IDENTITY_PATH} (use --force).",
            err=True,
        )
        sys.exit(1)

    hostname = socket.gethostname()
    aliases = sorted(
        {
            "localhost",
            hostname,
            hostname.split(".")[0],
            socket.getfqdn(),
            *extra_aliases,
        }
    )
    HOST_IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "# scitex-orochi host-identity\n"
        "# Names that mean *this* machine. Add SSH aliases declared in\n"
        "# ~/.ssh/config so that `ssh <alias>` from this host short-circuits\n"
        "# to local execution instead of looping through SSH.\n"
        + yaml.safe_dump({"aliases": aliases}, sort_keys=False)
    )
    HOST_IDENTITY_PATH.write_text(body)
    click.echo(f"Wrote {HOST_IDENTITY_PATH}")
    for a in aliases:
        click.echo(f"  - {a}")


@host_identity.command("check")
@click.argument("host")
@click.pass_context
def check(ctx: click.Context, host: str) -> None:
    """Report whether HOST resolves as local or remote on this machine."""
    reset_cache()
    local = is_local(host)
    if ctx.obj.get("json"):
        click.echo(json.dumps({"host": host, "local": local}))
        return
    verdict = "local" if local else "remote (would SSH)"
    click.echo(f"{host}: {verdict}")
    sys.exit(0 if local else 1)
