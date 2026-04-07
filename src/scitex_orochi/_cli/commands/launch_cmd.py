"""CLI commands: scitex-orochi launch {master,head,all}."""

from __future__ import annotations

import importlib.resources
import json
import subprocess
import sys
from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER
from scitex_orochi._config_loader import (
    ConfigError,
    _find_head,
    build_template_vars,
    load_config,
    render_template,
)

# Optional scitex-agent-container integration
try:
    from scitex_agent_container import agent_start as _ac_agent_start

    _HAS_AGENT_CONTAINER = True
except ImportError:
    _HAS_AGENT_CONTAINER = False


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


def _launch_via_agent_container(
    agent_config_path: str, dry_run: bool, as_json: bool
) -> None:
    """Delegate launch to scitex-agent-container.

    Requires the 'agent-container' optional dependency.
    """
    if not _HAS_AGENT_CONTAINER:
        click.echo(
            "Error: scitex-agent-container is not installed.\n"
            "  Install with: pip install scitex-orochi[agent-container]",
            err=True,
        )
        sys.exit(1)

    config_path = Path(agent_config_path).resolve()
    if not config_path.exists():
        click.echo(f"Error: Agent config not found: {config_path}", err=True)
        sys.exit(1)

    if dry_run:
        result = {
            "action": "launch-via-agent-container",
            "config": str(config_path),
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Would launch agent via scitex-agent-container:")
            click.echo(f"  Config: {config_path}")
        return

    try:
        _ac_agent_start(str(config_path))
        if as_json:
            click.echo(json.dumps({"status": "launched", "config": str(config_path)}))
        else:
            click.echo(f"Agent launched via scitex-agent-container: {config_path}")
    except Exception as exc:
        click.echo(f"Error: Agent container launch failed: {exc}", err=True)
        sys.exit(1)


def _screen_exists(name: str, ssh_prefix: str | None = None) -> bool:
    """Check if a screen session exists (local or remote)."""
    cmd = "screen -ls 2>/dev/null"
    if ssh_prefix:
        cmd = f"{ssh_prefix} {cmd}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return name in result.stdout


@click.group(
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi launch master\n"
    + "  scitex-orochi launch head spartan\n"
    + "  scitex-orochi launch all --dry-run\n",
)
def launch() -> None:
    """Launch orochi agents (master, head, or all)."""


@launch.command(
    "master",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi launch master\n"
    + "  scitex-orochi launch master --dry-run\n"
    + "  scitex-orochi launch master --agent-config agents/master.yaml\n"
    + "  scitex-orochi launch master --json\n",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml.",
)
@click.option(
    "--agent-config",
    "agent_config_path",
    default=None,
    help="Path to agent-container YAML file. Uses scitex-agent-container to launch.",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def launch_master(
    config_path: str | None,
    agent_config_path: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Launch orochi-agent:master in a screen session."""
    if agent_config_path:
        _launch_via_agent_container(agent_config_path, dry_run, as_json)
        return

    cfg = _load_cfg(config_path)
    master = cfg["master"]
    screen_name = master["name"]
    model = master.get("model", "opus[1m]")
    channels = master.get("channels", ["#general"])
    server = cfg["server"]

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
        result = {
            "action": "launch-master",
            "screen": screen_name,
            "model": model,
            "channels": channels,
            "command": launch_cmd,
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Would execute:")
            click.echo(launch_cmd)
            click.echo(f"\nRendered CLAUDE.md at: {claude_md}")
        return

    if _screen_exists(screen_name):
        click.echo(
            f"Error: Screen '{screen_name}' already exists.\n"
            f"  Kill it first: screen -S {screen_name} -X quit",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Launching {screen_name}...")
    subprocess.run(launch_cmd, shell=True, check=True)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "launched",
                    "screen": screen_name,
                    "model": model,
                }
            )
        )
    else:
        click.echo(f"Started screen session: {screen_name}")
        click.echo(f"Attach with: screen -r {screen_name}")


@launch.command(
    "head",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi launch head spartan\n"
    + "  scitex-orochi launch head nas --dry-run\n"
    + "  scitex-orochi launch head spartan --agent-config agents/head.yaml\n"
    + "  scitex-orochi launch head spartan --json\n",
)
@click.argument("name")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml.",
)
@click.option(
    "--agent-config",
    "agent_config_path",
    default=None,
    help="Path to agent-container YAML file. Uses scitex-agent-container to launch.",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def launch_head(
    name: str,
    config_path: str | None,
    agent_config_path: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Launch an orochi-agent:head on a remote host via SSH + screen."""
    if agent_config_path:
        _launch_via_agent_container(agent_config_path, dry_run, as_json)
        return

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
        result = {
            "action": "launch-head",
            "name": name,
            "screen": screen_name,
            "ssh": ssh_cmd,
            "model": model,
            "channels": channels,
            "command": full_cmd,
        }
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo("Would execute via SSH:")
            click.echo(full_cmd)
        return

    if _screen_exists(screen_name, ssh_cmd):
        click.echo(
            f"Error: Screen '{screen_name}' already exists on remote.\n"
            f"  Kill it first: {ssh_cmd} screen -S {screen_name} -X quit",
            err=True,
        )
        sys.exit(1)

    click.echo(f"Launching {screen_name} via {ssh_cmd}...")
    result_proc = subprocess.run(
        full_cmd,
        shell=True,
        capture_output=True,
        text=True,
    )
    if result_proc.returncode != 0:
        click.echo(
            f"Error: SSH command failed (exit {result_proc.returncode})",
            err=True,
        )
        if result_proc.stderr:
            click.echo(result_proc.stderr, err=True)
        sys.exit(1)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "status": "launched",
                    "screen": screen_name,
                    "ssh": ssh_cmd,
                }
            )
        )
    else:
        click.echo(f"Started remote screen session: {screen_name}")
        click.echo(f"Attach with: {ssh_cmd} -t screen -r {screen_name}")


@launch.command(
    "all",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi launch all\n"
    + "  scitex-orochi launch all --dry-run\n"
    + "  scitex-orochi launch all --agent-config-dir agents/\n"
    + "  scitex-orochi launch all --json\n",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml.",
)
@click.option(
    "--agent-config-dir",
    "agent_config_dir",
    default=None,
    help="Directory containing agent-container YAML files. Launches all *.yaml files found.",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def launch_all(
    ctx: click.Context,
    config_path: str | None,
    agent_config_dir: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Launch master and all configured heads."""
    # Agent-container mode: launch all YAML files in the directory
    if agent_config_dir:
        config_dir = Path(agent_config_dir).resolve()
        if not config_dir.is_dir():
            click.echo(f"Error: Not a directory: {config_dir}", err=True)
            sys.exit(1)

        yamls = sorted(config_dir.glob("*.yaml")) + sorted(
            config_dir.glob("*.yml")
        )
        if not yamls:
            click.echo(f"Error: No YAML files found in {config_dir}", err=True)
            sys.exit(1)

        for yaml_path in yamls:
            if not as_json:
                click.echo(f"\n=== Launching from {yaml_path.name} ===")
            _launch_via_agent_container(str(yaml_path), dry_run, as_json)

        if not as_json:
            click.echo(f"\nAll agents launched from {config_dir}")
        return

    # Legacy mode: use orochi-config.yaml
    cfg = _load_cfg(config_path)

    if not as_json:
        click.echo("=== Launching master ===")
    ctx.invoke(
        launch_master,
        config_path=config_path,
        agent_config_path=None,
        dry_run=dry_run,
        as_json=as_json,
    )

    for head in cfg.get("heads", []):
        short = head.get("host", head["name"])
        if not as_json:
            click.echo(f"\n=== Launching head: {short} ===")
        ctx.invoke(
            launch_head,
            name=short,
            config_path=config_path,
            agent_config_path=None,
            dry_run=dry_run,
            as_json=as_json,
        )

    if not as_json:
        click.echo("\nAll agents launched.")
