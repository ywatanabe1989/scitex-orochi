"""CLI command: scitex-orochi deploy -- deploy stable or dev instance."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

VALID_ENVS = ("stable", "dev")

# Container names per environment
CONTAINER_NAMES = {
    "stable": "orochi-server-stable",
    "dev": "orochi-server-dev",
}

# Compose files per environment
COMPOSE_FILES = {
    "stable": "docker-compose.stable.yml",
    "dev": "docker-compose.dev.yml",
}


def _find_project_root() -> Path:
    """Find the scitex-orochi project root (contains docker-compose.*.yml)."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent.parent,
        Path.home() / "proj" / "scitex-orochi",
        Path.cwd(),
    ]
    for candidate in candidates:
        if (candidate / "docker-compose.stable.yml").exists():
            return candidate
    raise click.ClickException(
        "Cannot find project root with docker-compose.stable.yml. "
        "Run from the scitex-orochi directory or install the package."
    )


@click.group("deploy")
def deploy() -> None:
    """Deploy Orochi instances (stable or dev)."""


@deploy.command("stable")
@click.option(
    "--build", "do_build", is_flag=True, help="Rebuild the image before deploying"
)
@click.option(
    "--down-first", is_flag=True, help="Bring down the container before redeploying"
)
def deploy_stable(do_build: bool, down_first: bool) -> None:
    """Deploy the stable Orochi instance (ports 9559/8559)."""
    _deploy_env("stable", do_build=do_build, down_first=down_first)


@deploy.command("dev")
@click.option(
    "--build", "do_build", is_flag=True, help="Rebuild the image before deploying"
)
@click.option(
    "--down-first", is_flag=True, help="Bring down the container before redeploying"
)
def deploy_dev(do_build: bool, down_first: bool) -> None:
    """Deploy the dev Orochi instance (ports 9560/8560)."""
    _deploy_env("dev", do_build=do_build, down_first=down_first)


@deploy.command("status")
def deploy_status() -> None:
    """Show status of stable and dev containers."""
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
            click.echo(f"  {env}: error querying docker (is docker running?)", err=True)
            continue
        output = result.stdout.strip()
        if output:
            click.echo(f"  {env}: {output}")
        else:
            click.echo(f"  {env}: not running")


def _deploy_env(env: str, *, do_build: bool, down_first: bool) -> None:
    """Deploy a specific environment."""
    root = _find_project_root()
    compose_file = root / COMPOSE_FILES[env]
    container = CONTAINER_NAMES[env]

    if not compose_file.exists():
        raise click.ClickException(f"Compose file not found: {compose_file}")

    click.echo(f"Deploying {env} instance (container: {container})")
    click.echo(f"  Compose file: {compose_file}")

    base_cmd = ["docker", "compose", "-f", str(compose_file), "-p", f"orochi-{env}"]

    if down_first:
        click.echo("  Bringing down existing container...")
        result = subprocess.run(base_cmd + ["down"], cwd=str(root))
        if result.returncode != 0:
            raise click.ClickException(
                f"'docker compose down' failed with exit code {result.returncode}"
            )

    up_cmd = base_cmd + ["up", "-d"]
    if do_build:
        up_cmd.append("--build")

    click.echo("  Starting container...")
    result = subprocess.run(up_cmd, cwd=str(root))
    if result.returncode != 0:
        raise click.ClickException(
            f"'docker compose up' failed with exit code {result.returncode}"
        )

    click.echo(f"  {env} instance deployed successfully.")
