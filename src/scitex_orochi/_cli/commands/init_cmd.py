"""CLI command: scitex-orochi init -- generate orochi-config.yaml."""

from __future__ import annotations

import importlib.resources
import sys
from pathlib import Path

import click


@click.command("init")
@click.option(
    "--output",
    "-o",
    default="orochi-config.yaml",
    help="Output path (default: ./orochi-config.yaml)",
)
def init_cmd(output: str) -> None:
    """Generate an orochi-config.yaml from the example template."""
    out_path = Path(output)
    if out_path.exists():
        click.echo(f"Error: {out_path} already exists. Remove it first.", err=True)
        sys.exit(1)

    template_pkg = "scitex_orochi.templates"
    template_name = "orochi-config.example.yaml"
    try:
        ref = importlib.resources.files(template_pkg).joinpath(template_name)
        content = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        click.echo(f"Error: Cannot find template: {exc}", err=True)
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    click.echo(f"Created {out_path}")
    click.echo(
        "Edit it with your server/host details, then run: scitex-orochi launch all"
    )
