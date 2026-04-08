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

# Default agents directory (relative to project root / cwd)
_DEFAULT_AGENTS_DIR = Path("agents")
_USER_AGENTS_DIR = Path.home() / ".scitex" / "orochi" / "agents"


def _find_agent_yaml(name: str, agents_dir: Path | None = None) -> Path | None:
    """Resolve an agent YAML file by convention.

    Search order for a given name (e.g. "master", "head-general", "research"):
      1. ~/.scitex/orochi/agents/<name>.yaml  (user config, checked first)
      2. ~/.scitex/orochi/agents/head-<name>.yaml
      3. agents/<name>.yaml   (repo fallback)
      4. agents/<name>.yml
      5. agents/head-<name>.yaml   (convenience for head agents)
      6. agents/head-<name>.yml

    Returns the resolved Path or None if not found.
    """
    # Check user config dir first
    if _USER_AGENTS_DIR.is_dir():
        for ext in (".yaml", ".yml"):
            for prefix in ("", "head-"):
                candidate = _USER_AGENTS_DIR / f"{prefix}{name}{ext}"
                if candidate.exists():
                    return candidate

    # Fall back to repo agents/ dir
    d = (agents_dir or _DEFAULT_AGENTS_DIR).resolve()
    if not d.is_dir():
        return None

    candidates = [
        d / f"{name}.yaml",
        d / f"{name}.yml",
        d / f"head-{name}.yaml",
        d / f"head-{name}.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_all_agent_yamls(agents_dir: Path | None = None) -> list[Path]:
    """Find all agent YAML files in the agents directory.

    Returns sorted list of YAML paths, excluding files whose names start
    with underscore (convention for disabled/template files).
    """
    d = (agents_dir or _DEFAULT_AGENTS_DIR).resolve()
    if not d.is_dir():
        return []

    yamls = sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml"))
    # Exclude underscore-prefixed files and telegrammer (runs separately)
    return [y for y in yamls if not y.name.startswith("_")]


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
    + "  scitex-orochi launch head general\n"
    + "  scitex-orochi launch all --dry-run\n",
)
def launch() -> None:
    """Launch orochi agents (master, head, or all).

    By default, agents are launched via scitex-agent-container using YAML
    definitions from the agents/ directory. If no YAML is found and
    agent-container is not installed, falls back to legacy orochi-config.yaml.
    """


@launch.command(
    "master",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi launch master\n"
    + "  scitex-orochi launch master --dry-run\n"
    + "  scitex-orochi launch master --agent-config agents/custom.yaml\n"
    + "  scitex-orochi launch master --json\n",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml (legacy mode).",
)
@click.option(
    "--agent-config",
    "agent_config_path",
    default=None,
    help="Path to agent-container YAML file. Overrides auto-discovery.",
)
@click.option(
    "--agents-dir",
    "agents_dir",
    default=None,
    help="Directory containing agent YAML definitions (default: ./agents).",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def launch_master(
    config_path: str | None,
    agent_config_path: str | None,
    agents_dir: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Launch orochi-agent:master.

    Resolution order:
      1. --agent-config (explicit YAML path)
      2. agents/master.yaml (auto-discovery)
      3. orochi-config.yaml (legacy fallback)
    """
    # 1. Explicit --agent-config
    if agent_config_path:
        _launch_via_agent_container(agent_config_path, dry_run, as_json)
        return

    # 2. Auto-discover agents/master.yaml
    search_dir = Path(agents_dir) if agents_dir else None
    yaml_path = _find_agent_yaml("master", search_dir)
    if yaml_path and _HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(f"Using agent config: {yaml_path}")
        _launch_via_agent_container(str(yaml_path), dry_run, as_json)
        return

    if yaml_path and not _HAS_AGENT_CONTAINER:
        click.echo(
            f"Found {yaml_path} but scitex-agent-container is not installed.\n"
            f"  Install with: pip install scitex-orochi[agent-container]\n"
            f"  Falling back to legacy orochi-config.yaml mode.",
            err=True,
        )

    # 3. Legacy fallback via orochi-config.yaml
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

    channel_args = " ".join(f"--channel server:scitex-orochi:{ch}" for ch in channels)
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
    + "  scitex-orochi launch head general\n"
    + "  scitex-orochi launch head research --dry-run\n"
    + "  scitex-orochi launch head deploy --agent-config agents/custom.yaml\n"
    + "  scitex-orochi launch head general --json\n",
)
@click.argument("name")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml (legacy mode).",
)
@click.option(
    "--agent-config",
    "agent_config_path",
    default=None,
    help="Path to agent-container YAML file. Overrides auto-discovery.",
)
@click.option(
    "--agents-dir",
    "agents_dir",
    default=None,
    help="Directory containing agent YAML definitions (default: ./agents).",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def launch_head(
    name: str,
    config_path: str | None,
    agent_config_path: str | None,
    agents_dir: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Launch an orochi-agent:head by name.

    Resolution order:
      1. --agent-config (explicit YAML path)
      2. agents/<name>.yaml or agents/head-<name>.yaml (auto-discovery)
      3. orochi-config.yaml (legacy fallback)
    """
    # 1. Explicit --agent-config
    if agent_config_path:
        _launch_via_agent_container(agent_config_path, dry_run, as_json)
        return

    # 2. Auto-discover agents/<name>.yaml or agents/head-<name>.yaml
    search_dir = Path(agents_dir) if agents_dir else None
    yaml_path = _find_agent_yaml(name, search_dir)
    if yaml_path and _HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(f"Using agent config: {yaml_path}")
        _launch_via_agent_container(str(yaml_path), dry_run, as_json)
        return

    if yaml_path and not _HAS_AGENT_CONTAINER:
        click.echo(
            f"Found {yaml_path} but scitex-agent-container is not installed.\n"
            f"  Install with: pip install scitex-orochi[agent-container]\n"
            f"  Falling back to legacy orochi-config.yaml mode.",
            err=True,
        )

    # 3. Legacy fallback via orochi-config.yaml
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

    channel_args = " ".join(f"--channel server:scitex-orochi:{ch}" for ch in channels)
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
    + "  scitex-orochi launch all --agents-dir agents/\n"
    + "  scitex-orochi launch all --json\n",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    help="Path to orochi-config.yaml (legacy mode).",
)
@click.option(
    "--agent-config-dir",
    "agent_config_dir",
    default=None,
    help="Explicit directory of agent-container YAMLs (overrides auto-discovery).",
)
@click.option(
    "--agents-dir",
    "agents_dir",
    default=None,
    help="Directory containing agent YAML definitions (default: ./agents).",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.pass_context
def launch_all(
    ctx: click.Context,
    config_path: str | None,
    agent_config_dir: str | None,
    agents_dir: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Launch master and all configured head agents.

    Resolution order:
      1. --agent-config-dir (explicit directory, all YAMLs launched)
      2. agents/ directory auto-discovery (if agent-container installed)
      3. orochi-config.yaml (legacy fallback)
    """
    # 1. Explicit --agent-config-dir (backwards compat)
    if agent_config_dir:
        config_dir = Path(agent_config_dir).resolve()
        if not config_dir.is_dir():
            click.echo(f"Error: Not a directory: {config_dir}", err=True)
            sys.exit(1)

        yamls = sorted(config_dir.glob("*.yaml")) + sorted(
            config_dir.glob("*.yml")
        )
        yamls = [y for y in yamls if not y.name.startswith("_")]
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

    # 2. Auto-discover agents/ directory
    search_dir = Path(agents_dir) if agents_dir else None
    yamls = _find_all_agent_yamls(search_dir)

    if yamls and _HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(
                f"Discovered {len(yamls)} agent config(s) "
                f"in {(search_dir or _DEFAULT_AGENTS_DIR).resolve()}"
            )

        for yaml_path in yamls:
            # Skip telegrammer -- it runs separately (see telegrammer.yaml comments)
            if yaml_path.stem == "telegrammer":
                if not as_json:
                    click.echo(
                        f"\n--- Skipping {yaml_path.name} "
                        f"(runs separately, not via Orochi launch) ---"
                    )
                continue

            if not as_json:
                click.echo(f"\n=== Launching from {yaml_path.name} ===")
            _launch_via_agent_container(str(yaml_path), dry_run, as_json)

        if not as_json:
            click.echo("\nAll agents launched.")
        return

    if yamls and not _HAS_AGENT_CONTAINER:
        click.echo(
            f"Found {len(yamls)} agent YAML(s) but scitex-agent-container "
            f"is not installed.\n"
            f"  Install with: pip install scitex-orochi[agent-container]\n"
            f"  Falling back to legacy orochi-config.yaml mode.",
            err=True,
        )

    # 3. Legacy fallback: use orochi-config.yaml
    cfg = _load_cfg(config_path)

    if not as_json:
        click.echo("=== Launching master ===")
    ctx.invoke(
        launch_master,
        config_path=config_path,
        agent_config_path=None,
        agents_dir=agents_dir,
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
            agents_dir=agents_dir,
            dry_run=dry_run,
            as_json=as_json,
        )

    if not as_json:
        click.echo("\nAll agents launched.")
