"""CLI command: scitex-orochi skills -- browse package skills."""

from __future__ import annotations

from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "_skills" / "scitex-orochi"


@click.group(
    "skills",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi skills list\n"
    + "  scitex-orochi skills get SKILL\n"
    + "  scitex-orochi skills export\n",
)
def skills() -> None:
    """View package skills (workflow-oriented guides)."""


@skills.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def skills_list(as_json: bool) -> None:
    """List available skill pages."""
    import json

    if not SKILLS_DIR.exists():
        click.echo("No skills found.", err=True)
        return

    entries = []
    for md in sorted(SKILLS_DIR.glob("*.md")):
        name = md.stem
        # Read first non-empty, non-frontmatter line as description
        desc = ""
        in_frontmatter = False
        for line in md.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if stripped and not stripped.startswith("#"):
                desc = stripped[:80]
                break
            if stripped.startswith("# "):
                desc = stripped[2:].strip()
                break
        entries.append({"name": name, "description": desc})

    if as_json:
        click.echo(json.dumps(entries, indent=2))
        return

    click.echo("Available skills for scitex-orochi:\n")
    for entry in entries:
        click.echo(f"  {entry['name']}")
        if entry["description"]:
            click.echo(f"    {entry['description']}")
    click.echo("\nUsage: scitex-orochi skills get <name>")


@skills.command("get")
@click.argument("name")
def skills_get(name: str) -> None:
    """Show a skill page."""
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        click.echo(f"Skill not found: {name}", err=True)
        click.echo("Run 'scitex-orochi skills list' to see available skills.")
        return
    click.echo(path.read_text(encoding="utf-8"))


@skills.command("export")
@click.option(
    "--target",
    default=None,
    help="Target directory (default: ~/.claude/skills/scitex/).",
)
def skills_export(target: str | None) -> None:
    """Export skills to ~/.claude/skills/scitex/."""
    import shutil

    dest = Path(target) if target else Path.home() / ".claude" / "skills" / "scitex"
    dest.mkdir(parents=True, exist_ok=True)
    orochi_dest = dest / "scitex-orochi"
    if orochi_dest.exists():
        shutil.rmtree(orochi_dest)
    shutil.copytree(SKILLS_DIR, orochi_dest)
    click.echo(f"Exported skills to {orochi_dest}")
