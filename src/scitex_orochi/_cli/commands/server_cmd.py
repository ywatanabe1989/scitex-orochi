"""CLI commands: serve, vapid-generate."""

from __future__ import annotations

import json

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER


# ── serve ───────────────────────────────────────────────────────
@click.command(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi serve\n"
    + "  SCITEX_OROCHI_PORT=9999 scitex-orochi serve\n",
)
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start the Orochi hub server."""
    from scitex_orochi._server import main as server_main

    server_main()


# ── vapid-generate ──────────────────────────────────────────────
@click.command(
    "vapid-generate",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi vapid-generate\n"
    + "  scitex-orochi vapid-generate --output /etc/orochi/vapid.json\n"
    + "  scitex-orochi vapid-generate --dry-run --json\n",
)
@click.option(
    "--output", default=None, help="Output path (default: /data/vapid-keys.json)."
)
@click.option("--force", is_flag=True, help="Overwrite existing keys.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--dry-run", is_flag=True, help="Show what would happen without writing.")
def vapid_generate(
    output: str | None, force: bool, as_json: bool, dry_run: bool
) -> None:
    """Generate VAPID key pair for web push notifications."""
    from scitex_orochi._push import (
        generate_vapid_keys,
        get_vapid_keys_path,
        load_vapid_keys,
        save_vapid_keys,
    )

    path = output or str(get_vapid_keys_path())

    if dry_run:
        existing = load_vapid_keys(path)
        result = {
            "action": "vapid-generate",
            "output": path,
            "exists": existing is not None,
            "force": force,
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            if existing and not force:
                click.echo(
                    f"[dry-run] Keys already exist at {path} (use --force to overwrite)"
                )
            else:
                click.echo(f"[dry-run] Would generate VAPID keys at {path}")
        return

    existing = load_vapid_keys(path)
    if existing and not force:
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "status": "exists",
                        "path": path,
                        "public_key": existing["public_key"],
                    }
                )
            )
        else:
            click.echo(f"VAPID keys already exist at {path}")
            click.echo(f"Public key: {existing['public_key']}")
            click.echo("Use --force to regenerate.")
        return

    keys = generate_vapid_keys()
    save_vapid_keys(keys, path)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "generated",
                    "path": path,
                    "public_key": keys["public_key"],
                }
            )
        )
    else:
        click.echo(f"VAPID keys generated and saved to {path}")
        click.echo(f"Public key: {keys['public_key']}")
