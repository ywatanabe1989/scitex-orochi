"""CLI command: scitex-orochi health -- run health check."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER


@click.command(
    "health",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi health\n"
    + "  scitex-orochi health --json\n",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml (reserved for future use).",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def health_cmd(config_path: str | None, as_json: bool) -> None:
    """Run health check (wraps scripts/health-check.sh)."""
    script_candidates = [
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "scripts"
        / "health-check.sh",
        Path.home() / "proj" / "scitex-orochi" / "scripts" / "health-check.sh",
    ]

    script_path = None
    for candidate in script_candidates:
        if candidate.exists():
            script_path = candidate
            break

    if script_path is None:
        if as_json:
            click.echo(
                json.dumps({"status": "error", "message": "health-check.sh not found"})
            )
        else:
            click.echo("Error: health-check.sh not found", err=True)
        sys.exit(1)

    result = subprocess.run(
        ["bash", str(script_path)], capture_output=as_json, text=True
    )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "ok" if result.returncode == 0 else "error",
                    "exit_code": result.returncode,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                }
            )
        )
    sys.exit(result.returncode)
