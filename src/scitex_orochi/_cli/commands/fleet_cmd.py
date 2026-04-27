"""CLI command: scitex-orochi fleet -- list agent YAML configs with status."""

from __future__ import annotations

import json
import subprocess

import click
import yaml

from scitex_orochi._cli._helpers import EXAMPLES_HEADER
from scitex_orochi._cli.commands._launch_helpers import find_all_agent_yamls


def _screen_sessions() -> set[str]:
    """Return set of active screen session names."""
    try:
        result = subprocess.run(
            ["screen", "-ls"], capture_output=True, text=True, timeout=5
        )
        names: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if "." in line and ("Detached" in line or "Attached" in line):
                # Format: "12345.session-name\t(Detached)"
                names.add(line.split(".")[1].split("\t")[0].split(" ")[0])
        return names
    except Exception:
        return set()


def _load_agent_meta(path) -> dict:
    """Parse agent YAML and return summary dict."""
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return {"file": str(path), "error": "parse error"}

    meta = raw.get("metadata", {}) or {}
    labels = meta.get("labels", {}) or {}
    spec = raw.get("spec", {}) or {}

    return {
        "name": meta.get("name", path.stem),
        "role": labels.get("role", "unknown"),
        "orochi_machine": labels.get("orochi_machine", "unknown"),
        "orochi_model": spec.get("orochi_model", ""),
        "screen": (spec.get("screen", {}) or {}).get("name", ""),
        "file": str(path),
    }


@click.command(
    "fleet",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi fleet\n"
    + "  scitex-orochi fleet --json\n"
    + "  scitex-orochi fleet --agents-dir ~/custom-agents\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--agents-dir",
    default=None,
    type=click.Path(exists=True),
    help="Override agents directory.",
)
def fleet(as_json: bool, agents_dir: str | None) -> None:
    """List all agent YAML configs with name, role, orochi_machine, and status."""
    from pathlib import Path

    search_dir = Path(agents_dir) if agents_dir else None
    yamls = find_all_agent_yamls(search_dir)

    if not yamls:
        if as_json:
            click.echo(json.dumps([], indent=2))
        else:
            click.echo("No agent configs found.")
        return

    screens = _screen_sessions()
    agents = []

    for path in yamls:
        info = _load_agent_meta(path)
        screen_name = info.get("screen", "")
        info["status"] = "running" if screen_name in screens else "stopped"
        agents.append(info)

    if as_json:
        click.echo(json.dumps(agents, indent=2))
        return

    # Table output
    click.echo(f"{'NAME':<30} {'ROLE':<10} {'MACHINE':<20} {'STATUS':<10} {'MODEL'}")
    click.echo("-" * 90)
    for a in agents:
        status_color = "green" if a["status"] == "running" else "red"
        click.echo(
            f"{a['name']:<30} {a['role']:<10} {a['orochi_machine']:<20} "
            f"{click.style(a['status'], fg=status_color):<19} {a.get('orochi_model', '')}"
        )
    click.echo(
        f"\n{len(agents)} agent(s) configured, "
        f"{sum(1 for a in agents if a['status'] == 'running')} running"
    )
