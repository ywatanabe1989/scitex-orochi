"""CLI command: scitex-orochi health -- run health check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click


@click.command("health")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml (reserved for future use)",
)
def health_cmd(config_path: str | None) -> None:
    """Run health check (wraps scripts/health-check.sh)."""
    script_candidates = [
        # Installed package location (relative to this file)
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "scripts"
        / "health-check.sh",
        # Development checkout
        Path.home() / "proj" / "scitex-orochi" / "scripts" / "health-check.sh",
    ]

    script_path = None
    for candidate in script_candidates:
        if candidate.exists():
            script_path = candidate
            break

    if script_path is None:
        click.echo("Error: health-check.sh not found", err=True)
        sys.exit(1)

    result = subprocess.run(["bash", str(script_path)], capture_output=False)
    sys.exit(result.returncode)
