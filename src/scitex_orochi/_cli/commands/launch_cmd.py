"""CLI commands: scitex-orochi launch {master,head,all}."""

from __future__ import annotations

import importlib.resources
import subprocess
import sys
from pathlib import Path

import click

from scitex_orochi._config_loader import (
    ConfigError,
    _find_head,
    build_template_vars,
    load_config,
    render_template,
)


def _load_cfg(config_path: str | None) -> dict:
    """Load config or exit with error."""
    try:
        return load_config(Path(config_path) if config_path else None)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


def _read_template(name: str) -> str:
    """Read a template file from the package."""
    pkg = "scitex_orochi.templates"
    try:
        ref = importlib.resources.files(pkg).joinpath(name)
        return ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        click.echo(f"Error: Cannot find template: {exc}", err=True)
        sys.exit(1)


def _screen_exists(name: str, ssh_prefix: str | None = None) -> bool:
    """Check if a screen session exists (local or remote)."""
    cmd = "screen -ls 2>/dev/null"
    if ssh_prefix:
        cmd = f"{ssh_prefix} {cmd}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return name in result.stdout


@click.group()
def launch() -> None:
    """Launch orochi agents (master, head, or all)."""


@launch.command("master")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
def launch_master(config_path: str | None, dry_run: bool) -> None:
    """Launch orochi-agent:master:<user>@<host> in a screen session."""
    cfg = _load_cfg(config_path)
    master = cfg["master"]
    screen_name = master["name"]
    model = master.get("model", "opus[1m]")
    channels = master.get("channels", ["#general"])
    server = cfg["server"]

    # Render CLAUDE.md
    tvars = build_template_vars(cfg, role="master")
    rendered = render_template(_read_template("master-claude.md"), tvars)

    claude_md = Path(f"/tmp/{screen_name}-CLAUDE.md")
    claude_md.write_text(rendered, encoding="utf-8")

    channel_args = " ".join(f"--channel server:orochi-push:{ch}" for ch in channels)
    launch_cmd = (
        f"screen -dmS {screen_name} bash -c '"
        f"export SCITEX_OROCHI_HOST={server['host']}; "
        f"export SCITEX_OROCHI_PORT={server['ws_port']}; "
        f"export SCITEX_OROCHI_AGENT={screen_name}; "
        f"claude --model {model} "
        f'--system-prompt "$(cat {claude_md})" '
        f"{channel_args}; "
        f"exec bash'"
    )

    if dry_run:
        click.echo("Would execute:")
        click.echo(launch_cmd)
        click.echo(f"\nRendered CLAUDE.md at: {claude_md}")
        return

    if _screen_exists(screen_name):
        click.echo(
            f"Error: Screen '{screen_name}' already exists. "
            f"Kill it first: screen -S {screen_name} -X quit",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Launching {screen_name}...")
    subprocess.run(launch_cmd, shell=True, check=True)
    click.echo(f"Started screen session: {screen_name}")
    click.echo(f"Attach with: screen -r {screen_name}")


@launch.command("head")
@click.argument("name")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
def launch_head(name: str, config_path: str | None, dry_run: bool) -> None:
    """Launch an orochi-agent:head:<user>@<host> on a remote host via SSH + screen."""
    cfg = _load_cfg(config_path)

    try:
        head = _find_head(cfg, name)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    screen_name = head["name"]
    ssh_cmd = head["ssh"]
    model = head.get("model", "sonnet")
    channels = head.get("channels", ["#general"])
    workdir = head.get("workdir", "~/proj")
    server = cfg["server"]

    # Render CLAUDE.md
    tvars = build_template_vars(cfg, role="head", head_name=name)
    rendered = render_template(_read_template("head-claude.md"), tvars)

    channel_args = " ".join(f"--channel server:orochi-push:{ch}" for ch in channels)
    remote_script = (
        f"cat > /tmp/{screen_name}-CLAUDE.md << 'CLAUDE_EOF'\n"
        f"{rendered}\n"
        f"CLAUDE_EOF\n"
        f"screen -dmS {screen_name} bash -c '"
        f"cd {workdir}; "
        f"export SCITEX_OROCHI_HOST={server['host']}; "
        f"export SCITEX_OROCHI_PORT={server['ws_port']}; "
        f"export SCITEX_OROCHI_AGENT={screen_name}; "
        f"claude --model {model} "
        f'--system-prompt "$(cat /tmp/{screen_name}-CLAUDE.md)" '
        f"{channel_args}; "
        f"exec bash'"
    )
    full_cmd = f"{ssh_cmd} bash -s << 'SSH_EOF'\n{remote_script}\nSSH_EOF"

    if dry_run:
        click.echo("Would execute via SSH:")
        click.echo(full_cmd)
        return

    if _screen_exists(screen_name, ssh_cmd):
        click.echo(
            f"Error: Screen '{screen_name}' already exists on remote. "
            f"Kill it first: {ssh_cmd} screen -S {screen_name} -X quit",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Launching {screen_name} via {ssh_cmd}...")
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        click.echo(f"Error: SSH command failed (exit {result.returncode})", err=True)
        if result.stderr:
            click.echo(result.stderr, err=True)
        sys.exit(1)

    click.echo(f"Started remote screen session: {screen_name}")
    click.echo(f"Attach with: {ssh_cmd} -t screen -r {screen_name}")


@launch.command("all")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing")
@click.pass_context
def launch_all(ctx: click.Context, config_path: str | None, dry_run: bool) -> None:
    """Launch master and all configured heads."""
    cfg = _load_cfg(config_path)

    click.echo("=== Launching master ===")
    ctx.invoke(launch_master, config_path=config_path, dry_run=dry_run)

    for head in cfg.get("heads", []):
        short = head.get("host", head["name"])
        click.echo(f"\n=== Launching head: {short} ===")
        ctx.invoke(
            launch_head,
            name=short,
            config_path=config_path,
            dry_run=dry_run,
        )

    click.echo("\nAll agents launched.")
