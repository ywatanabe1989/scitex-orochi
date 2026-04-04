"""CLI command: scitex-orochi docs -- browse documentation."""

from __future__ import annotations

from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

_PKG_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


@click.group(
    "docs",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi docs list\n"
    + "  scitex-orochi docs get readme\n",
)
def docs() -> None:
    """Browse scitex-orochi documentation."""


_DOC_PAGES = {
    "readme": _PKG_ROOT / "README.md",
    "protocol": _PKG_ROOT / "README.md",
    "cloudflare": _PKG_ROOT / "docs" / "cloudflare-tunnel-config.md",
    "workspaces": _PKG_ROOT / "docs" / "workspace-integration-design.md",
}


@docs.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def docs_list(as_json: bool) -> None:
    """List available documentation pages."""
    import json

    entries = []
    for name, path in _DOC_PAGES.items():
        exists = path.exists()
        entries.append({"name": name, "path": str(path), "exists": exists})

    if as_json:
        click.echo(json.dumps(entries, indent=2))
        return

    click.echo("Available documentation:\n")
    for entry in entries:
        tag = "" if entry["exists"] else " (not found)"
        click.echo(f"  {entry['name']}{tag}")
    click.echo("\nUsage: scitex-orochi docs get <name>")


@docs.command("get")
@click.argument("name")
def docs_get(name: str) -> None:
    """Show a documentation page."""
    path = _DOC_PAGES.get(name)
    if path is None:
        click.echo(f"Unknown doc page: {name}", err=True)
        click.echo("Run 'scitex-orochi docs list' to see available pages.")
        return
    if not path.exists():
        click.echo(f"Doc file not found: {path}", err=True)
        return
    click.echo(path.read_text(encoding="utf-8"))
