"""CLI command: scitex-orochi init -- generate orochi-config.yaml."""

from __future__ import annotations

import importlib.resources
import json
import sys
from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER


@click.command(
    "init",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi init\n"
    + "  scitex-orochi init --output /etc/orochi/config.yaml\n"
    + "  scitex-orochi init --dry-run --json\n",
)
@click.option(
    "--output",
    "-o",
    default="orochi-config.yaml",
    help="Output path (default: ./orochi-config.yaml).",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be created without writing."
)
def init_cmd(output: str, as_json: bool, dry_run: bool) -> None:
    """Generate an orochi-config.yaml from the example template."""
    out_path = Path(output)

    if dry_run:
        result = {
            "action": "init",
            "output": str(out_path),
            "exists": out_path.exists(),
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            if out_path.exists():
                click.echo(f"[dry-run] {out_path} already exists, would fail")
            else:
                click.echo(f"[dry-run] Would create {out_path}")
        return

    if out_path.exists():
        msg = f"{out_path} already exists. Remove it first."
        if as_json:
            click.echo(json.dumps({"status": "error", "message": msg}))
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    template_pkg = "scitex_orochi.templates"
    template_name = "orochi-config.example.yaml"
    try:
        ref = importlib.resources.files(template_pkg).joinpath(template_name)
        content = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        msg = f"Cannot find template: {exc}"
        if as_json:
            click.echo(json.dumps({"status": "error", "message": msg}))
        else:
            click.echo(f"Error: {msg}", err=True)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    if as_json:
        click.echo(json.dumps({"status": "created", "path": str(out_path)}))
    else:
        click.echo(f"Created {out_path}")
        click.echo(
            "Edit it with your server/host details, then run: scitex-orochi launch all"
        )
