"""CLI command: scitex-orochi deploy -- deploy stable or dev instance."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER

VALID_ENVS = ("stable", "dev")

CONTAINER_NAMES = {
    "stable": "orochi-server-stable",
    "dev": "orochi-server-dev",
}

COMPOSE_DIR = Path("deployment") / "docker"

COMPOSE_FILES = {
    "stable": COMPOSE_DIR / "docker-compose.stable.yml",
    "dev": COMPOSE_DIR / "docker-compose.dev.yml",
}


def _find_project_root() -> Path:
    """Find the scitex-orochi orochi_project root."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent.parent,
        Path.home() / "proj" / "scitex-orochi",
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / COMPOSE_FILES["stable"]).exists():
            return candidate
    raise click.ClickException(
        "Cannot find orochi_project root with deployment/docker/docker-compose.stable.yml.\n"
        "  Run from the scitex-orochi directory or install the package."
    )


@click.group(
    "deploy",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi deploy stable\n"
    + "  scitex-orochi deploy dev --build\n"
    + "  scitex-orochi deploy status --json\n",
)
def deploy() -> None:
    """Deploy Orochi instances (stable or dev)."""


@deploy.command(
    "stable",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi deploy stable\n"
    + "  scitex-orochi deploy stable --build --down-first\n"
    + "  scitex-orochi deploy stable --dry-run --json\n",
)
@click.option("--build", "do_build", is_flag=True, help="Rebuild image first.")
@click.option("--down-first", is_flag=True, help="Bring down before redeploying.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--dry-run", is_flag=True, help="Show commands without executing.")
def deploy_stable(
    do_build: bool, down_first: bool, as_json: bool, dry_run: bool
) -> None:
    """Deploy the stable Orochi instance (ports 9559/8559)."""
    _deploy_env(
        "stable",
        do_build=do_build,
        down_first=down_first,
        as_json=as_json,
        dry_run=dry_run,
    )


@deploy.command(
    "dev",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi deploy dev\n"
    + "  scitex-orochi deploy dev --build\n"
    + "  scitex-orochi deploy dev --dry-run\n",
)
@click.option("--build", "do_build", is_flag=True, help="Rebuild image first.")
@click.option("--down-first", is_flag=True, help="Bring down before redeploying.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--dry-run", is_flag=True, help="Show commands without executing.")
def deploy_dev(do_build: bool, down_first: bool, as_json: bool, dry_run: bool) -> None:
    """Deploy the dev Orochi instance (ports 9560/8560)."""
    _deploy_env(
        "dev",
        do_build=do_build,
        down_first=down_first,
        as_json=as_json,
        dry_run=dry_run,
    )


@deploy.command(
    "status",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi deploy status\n"
    + "  scitex-orochi deploy status --json\n",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def deploy_status(as_json: bool) -> None:
    """Show status of stable and dev containers."""
    results = {}
    for env in VALID_ENVS:
        container = CONTAINER_NAMES[env]
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name={container}",
                "--format",
                "{{.Names}}\t{{.Status}}\t{{.Ports}}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            results[env] = {"status": "error", "message": "docker not reachable"}
        elif result.stdout.strip():
            results[env] = {"status": "running", "detail": result.stdout.strip()}
        else:
            results[env] = {"status": "not running"}

    if as_json:
        click.echo(json.dumps(results, indent=2))
        return
    for env, info in results.items():
        if info["status"] == "running":
            click.echo(f"  {env}: {info['detail']}")
        else:
            click.echo(f"  {env}: {info['status']}")


def _deploy_env(
    env: str,
    *,
    do_build: bool,
    down_first: bool,
    as_json: bool,
    dry_run: bool,
) -> None:
    """Deploy a specific environment."""
    root = _find_project_root()
    compose_file = root / COMPOSE_FILES[env]
    container = CONTAINER_NAMES[env]

    if not compose_file.exists():
        raise click.ClickException(f"Compose file not found: {compose_file}")

    base_cmd = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "-p",
        f"orochi-{env}",
    ]

    down_cmd = base_cmd + ["down"] if down_first else None
    up_cmd = base_cmd + ["up", "-d"]
    if do_build:
        up_cmd.append("--build")

    if dry_run:
        result = {
            "action": "deploy",
            "env": env,
            "container": container,
            "compose_file": str(compose_file),
            "down_first": down_first,
            "build": do_build,
            "down_cmd": " ".join(down_cmd) if down_cmd else None,
            "up_cmd": " ".join(up_cmd),
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"[dry-run] Deploy {env} (container: {container})")
            click.echo(f"          Compose: {compose_file}")
            if down_cmd:
                click.echo(f"          Down:    {' '.join(down_cmd)}")
            click.echo(f"          Up:      {' '.join(up_cmd)}")
        return

    if not as_json:
        click.echo(f"Deploying {env} instance (container: {container})")
        click.echo(f"  Compose file: {compose_file}")

    if down_first:
        if not as_json:
            click.echo("  Bringing down existing container...")
        result_proc = subprocess.run(base_cmd + ["down"], cwd=str(root))
        if result_proc.returncode != 0:
            raise click.ClickException(
                f"'docker compose down' failed (exit {result_proc.returncode})"
            )

    if not as_json:
        click.echo("  Starting container...")
    result_proc = subprocess.run(up_cmd, cwd=str(root))
    if result_proc.returncode != 0:
        raise click.ClickException(
            f"'docker compose up' failed (exit {result_proc.returncode})"
        )

    if as_json:
        click.echo(
            json.dumps({"status": "deployed", "env": env, "container": container})
        )
    else:
        click.echo(f"  {env} instance deployed successfully.")
