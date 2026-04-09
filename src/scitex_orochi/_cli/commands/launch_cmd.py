"""CLI commands: scitex-orochi launch {master,head,all}."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER
from scitex_orochi._cli.commands._launch_helpers import (
    DEFAULT_AGENTS_DIR,
    HAS_AGENT_CONTAINER,
    find_agent_yaml,
    find_all_agent_yamls,
    launch_via_agent_container,
    legacy_launch_head,
    legacy_launch_master,
    load_cfg,
)


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
    if agent_config_path:
        launch_via_agent_container(agent_config_path, dry_run, as_json)
        return

    search_dir = Path(agents_dir) if agents_dir else None
    yaml_path = find_agent_yaml("master", search_dir)
    if yaml_path and HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(f"Using agent config: {yaml_path}")
        launch_via_agent_container(str(yaml_path), dry_run, as_json)
        return

    if yaml_path and not HAS_AGENT_CONTAINER:
        click.echo(
            f"Found {yaml_path} but scitex-agent-container is not installed.\n"
            f"  Install with: pip install scitex-orochi[agent-container]\n"
            f"  Falling back to legacy orochi-config.yaml mode.",
            err=True,
        )

    cfg = load_cfg(config_path)
    legacy_launch_master(cfg, dry_run, as_json)


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
    if agent_config_path:
        launch_via_agent_container(agent_config_path, dry_run, as_json)
        return

    search_dir = Path(agents_dir) if agents_dir else None
    yaml_path = find_agent_yaml(name, search_dir)
    if yaml_path and HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(f"Using agent config: {yaml_path}")
        launch_via_agent_container(str(yaml_path), dry_run, as_json)
        return

    if yaml_path and not HAS_AGENT_CONTAINER:
        click.echo(
            f"Found {yaml_path} but scitex-agent-container is not installed.\n"
            f"  Install with: pip install scitex-orochi[agent-container]\n"
            f"  Falling back to legacy orochi-config.yaml mode.",
            err=True,
        )

    cfg = load_cfg(config_path)
    legacy_launch_head(cfg, name, dry_run, as_json)


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
    if agent_config_dir:
        config_dir = Path(agent_config_dir).resolve()
        if not config_dir.is_dir():
            click.echo(f"Error: Not a directory: {config_dir}", err=True)
            sys.exit(1)

        yamls = sorted(config_dir.glob("*.yaml")) + sorted(config_dir.glob("*.yml"))
        yamls = [y for y in yamls if not y.name.startswith("_")]
        if not yamls:
            click.echo(f"Error: No YAML files found in {config_dir}", err=True)
            sys.exit(1)

        for yaml_path in yamls:
            if not as_json:
                click.echo(f"\n=== Launching from {yaml_path.name} ===")
            launch_via_agent_container(str(yaml_path), dry_run, as_json)

        if not as_json:
            click.echo(f"\nAll agents launched from {config_dir}")
        return

    search_dir = Path(agents_dir) if agents_dir else None
    yamls = find_all_agent_yamls(search_dir)

    if yamls and HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(
                f"Discovered {len(yamls)} agent config(s) "
                f"in {(search_dir or DEFAULT_AGENTS_DIR).resolve()}"
            )

        for yaml_path in yamls:
            if yaml_path.stem == "telegrammer":
                if not as_json:
                    click.echo(
                        f"\n--- Skipping {yaml_path.name} "
                        f"(runs separately, not via Orochi launch) ---"
                    )
                continue

            if not as_json:
                click.echo(f"\n=== Launching from {yaml_path.name} ===")
            launch_via_agent_container(str(yaml_path), dry_run, as_json)

        if not as_json:
            click.echo("\nAll agents launched.")
        return

    if yamls and not HAS_AGENT_CONTAINER:
        click.echo(
            f"Found {len(yamls)} agent YAML(s) but scitex-agent-container "
            f"is not installed.\n"
            f"  Install with: pip install scitex-orochi[agent-container]\n"
            f"  Falling back to legacy orochi-config.yaml mode.",
            err=True,
        )

    cfg = load_cfg(config_path)

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
