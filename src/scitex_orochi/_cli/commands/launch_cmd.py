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
    definitions from ~/.scitex/orochi/{shared,<host>}/agents/ (or legacy
    ~/.scitex/orochi/agents/, or examples/agents/ as fallback). If no YAML
    is found and agent-container is not installed, falls back to legacy
    orochi-config.yaml.
    """


@launch.command(
    "master",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi launch master\n"
    + "  scitex-orochi launch master --dry-run\n"
    + "  scitex-orochi launch master --agent-config examples/agents/custom.yaml\n"
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
    help="Directory containing agent YAML definitions (default: examples/agents).",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Stop any running instance first, then launch fresh.",
)
def launch_master(
    config_path: str | None,
    agent_config_path: str | None,
    agents_dir: str | None,
    dry_run: bool,
    as_json: bool,
    force: bool,
) -> None:
    """Launch orochi-agent:master.

    Resolution order:
      1. --agent-config (explicit YAML path)
      2. ~/.scitex/orochi/{<host>,shared}/agents/ (or legacy
         ~/.scitex/orochi/agents/), or examples/agents/ (auto-discovery)
      3. orochi-config.yaml (legacy fallback)
    """
    if agent_config_path:
        launch_via_agent_container(agent_config_path, dry_run, as_json, force=force)
        return

    search_dir = Path(agents_dir) if agents_dir else None
    yaml_path = find_agent_yaml("master", search_dir)
    if yaml_path and HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(f"Using agent config: {yaml_path}")
        launch_via_agent_container(str(yaml_path), dry_run, as_json, force=force)
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
    + "  scitex-orochi launch head deploy --agent-config examples/agents/custom.yaml\n"
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
    help="Directory containing agent YAML definitions (default: examples/agents).",
)
@click.option("--dry-run", is_flag=True, help="Print commands without executing.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Stop any running instance first, then launch fresh.",
)
def launch_head(
    name: str,
    config_path: str | None,
    agent_config_path: str | None,
    agents_dir: str | None,
    dry_run: bool,
    as_json: bool,
    force: bool,
) -> None:
    """Launch an orochi-agent:head by name.

    Resolution order:
      1. --agent-config (explicit YAML path)
      2. ~/.scitex/orochi/{<host>,shared}/agents/ (or legacy
         ~/.scitex/orochi/agents/), or examples/agents/ (auto-discovery)
      3. orochi-config.yaml (legacy fallback)
    """
    if agent_config_path:
        launch_via_agent_container(agent_config_path, dry_run, as_json, force=force)
        return

    search_dir = Path(agents_dir) if agents_dir else None
    yaml_path = find_agent_yaml(name, search_dir)
    if yaml_path and HAS_AGENT_CONTAINER:
        if not as_json:
            click.echo(f"Using agent config: {yaml_path}")
        launch_via_agent_container(str(yaml_path), dry_run, as_json, force=force)
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
    + "  scitex-orochi launch all --agents-dir examples/agents/\n"
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
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Stop any running instance first, then launch fresh.",
)
@click.pass_context
def launch_all(
    ctx: click.Context,
    config_path: str | None,
    agent_config_dir: str | None,
    agents_dir: str | None,
    dry_run: bool,
    as_json: bool,
    force: bool,
) -> None:
    """Launch master and all configured head agents.

    Resolution order:
      1. --agent-config-dir (explicit directory, all YAMLs launched)
      2. ~/.scitex/orochi/{<host>,shared}/agents/ (or legacy
         ~/.scitex/orochi/agents/), or examples/agents/ (if
         agent-container installed)
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
            launch_via_agent_container(str(yaml_path), dry_run, as_json, force=force)

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

        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Filter out telegrammer agents
        to_launch = []
        for yaml_path in yamls:
            if yaml_path.stem == "telegrammer" or yaml_path.stem.startswith(
                "telegrammer-"
            ):
                if not as_json:
                    click.echo(f"  Skipping {yaml_path.name} (runs separately)")
                continue
            to_launch.append(yaml_path)

        if not as_json:
            click.echo(f"Launching {len(to_launch)} agents in parallel...")

        def _launch_one(yp: Path) -> tuple[str, bool, str]:
            try:
                launch_via_agent_container(str(yp), dry_run, as_json, force=force)
                return (yp.stem, True, "OK")
            except Exception as exc:
                msg = str(exc).split("\n")[0]
                return (yp.stem, False, msg)

        results: list[tuple[str, bool, str]] = []
        with ThreadPoolExecutor(max_workers=len(to_launch)) as pool:
            futures = {pool.submit(_launch_one, yp): yp for yp in to_launch}
            for future in as_completed(futures):
                name, ok, msg = future.result()
                results.append((name, ok, msg))
                if not as_json:
                    status = "✓" if ok else "✗"
                    click.echo(f"  {status} {name}: {msg}")

        # Summary
        if not as_json:
            ok_list = [r for r in results if r[1]]
            fail_list = [r for r in results if not r[1]]
            click.echo("\n=== Fleet Launch Summary ===")
            click.echo(
                f"  OK: {len(ok_list)}/{len(results)}  "
                f"FAILED: {len(fail_list)}/{len(results)}"
            )
            if fail_list:
                for name, _, msg in fail_list:
                    click.echo(f"    ✗ {name}: {msg}")
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
