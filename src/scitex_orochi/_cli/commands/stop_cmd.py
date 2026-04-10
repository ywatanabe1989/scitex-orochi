"""CLI commands: scitex-orochi stop {NAME, --all}.

Stops Orochi fleet agents cleanly via scitex-agent-container's library
API, so no ad-hoc PID killing or hand-crafted screen wipes are needed.

Design notes:
- ``stop NAME`` looks up the yaml by name (same resolution rules as
  ``launch head NAME``), loads it, and calls ``agent_stop`` from
  scitex-agent-container. That works for both local and remote
  agents because scitex-agent-container's SSHRemote runtime handles
  the dispatch.
- ``stop --all`` walks every yaml in ``~/.scitex/orochi/agents/`` and
  stops each. Telegrammer agents are skipped (same exclusion logic as
  ``launch all``) — they run independently.
- ``--force`` is passed through to the underlying ``agent_stop`` so
  stale registry entries, ghost screens, and hook failures don't
  block cleanup of the rest of the fleet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from scitex_orochi._cli._helpers import EXAMPLES_HEADER
from scitex_orochi._cli.commands._launch_helpers import (
    HAS_AGENT_CONTAINER,
    find_agent_yaml,
    find_all_agent_yamls,
)

# Importing lazily (inside the command handlers) keeps the top-level
# import graph clean and lets the module load even if the optional
# scitex-agent-container extra isn't installed.


def _is_telegrammer_yaml(yaml_path: Path) -> bool:
    """Return True if the yaml belongs to a telegrammer agent.

    Telegrammer agents live outside the Orochi launch/stop lifecycle
    (independent MCP bridge), matching ``launch all``'s skip logic.
    """
    stem = yaml_path.stem
    return stem == "telegrammer" or stem.startswith("telegrammer-")


def _call_agent_stop(yaml_path: Path, force: bool) -> tuple[bool, str]:
    """Stop a single agent via the scitex-agent-container library.

    Returns (success, message) — never raises, so bulk operations can
    continue through individual failures.
    """
    if not HAS_AGENT_CONTAINER:
        return (
            False,
            "scitex-agent-container not installed. "
            "Install with: pip install scitex-orochi[agent-container]",
        )

    try:
        # Deferred imports so missing optional dep doesn't break CLI import
        from scitex_agent_container import load_config
        from scitex_agent_container.lifecycle import agent_stop
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"Import failed: {exc}"

    try:
        config = load_config(str(yaml_path))
    except Exception as exc:
        return False, f"Config load failed: {exc}"

    try:
        agent_stop(config.name, force=force)
        return True, f"stopped {config.name}"
    except Exception as exc:
        return False, f"stop failed: {exc}"


@click.command(
    "stop",
    epilog=EXAMPLES_HEADER
    + "  scitex-orochi stop master\n"
    + "  scitex-orochi stop head-mba\n"
    + "  scitex-orochi stop --all\n"
    + "  scitex-orochi stop --all --force\n",
)
@click.argument("name", required=False)
@click.option(
    "--all",
    "stop_all",
    is_flag=True,
    default=False,
    help="Stop every fleet agent discovered in ~/.scitex/orochi/agents/.",
)
@click.option(
    "--force",
    "force",
    is_flag=True,
    default=False,
    help="Tolerate stale registry, missing configs, hook failures.",
)
def stop(name: str | None, stop_all: bool, force: bool) -> None:
    """Stop an Orochi fleet agent (one or all).

    Resolution for a single NAME follows the same rules as
    ``launch head <name>``: ``~/.scitex/orochi/agents/<name>{,.yaml}``
    and ``head-<name>`` fallbacks.
    """
    if not stop_all and not name:
        click.echo(
            "Error: provide an agent NAME or use --all.\n"
            "  scitex-orochi stop master\n"
            "  scitex-orochi stop --all",
            err=True,
        )
        sys.exit(2)

    if stop_all:
        yamls = find_all_agent_yamls()
        if not yamls:
            click.echo("No agent YAML files found.", err=True)
            sys.exit(1)

        any_failure = False
        for yaml_path in yamls:
            if _is_telegrammer_yaml(yaml_path):
                click.echo(
                    f"--- Skipping {yaml_path.name} (telegrammer runs separately) ---"
                )
                continue

            click.echo(f"\n=== Stopping {yaml_path.stem} ===")
            ok, msg = _call_agent_stop(yaml_path, force=force)
            if ok:
                click.echo(f"  {msg}")
            else:
                any_failure = True
                click.echo(f"  [ERROR] {msg}", err=True)
                if not force:
                    click.echo(
                        "  Hint: rerun with --force to continue past failures.",
                        err=True,
                    )
                    sys.exit(1)

        click.echo()
        click.echo(
            "All fleet agents processed."
            + (" (with failures — see above)" if any_failure else "")
        )
        if any_failure and not force:
            sys.exit(1)
        return

    # Single-agent path
    yaml_path = find_agent_yaml(name)  # type: ignore[arg-type]
    if yaml_path is None:
        click.echo(
            f"Error: no yaml found for '{name}'.\n"
            f"  Searched: ~/.scitex/orochi/agents/{{{name},{name}/{name},head-{name}}}.yaml",
            err=True,
        )
        sys.exit(1)

    ok, msg = _call_agent_stop(yaml_path, force=force)
    if ok:
        click.echo(msg)
    else:
        click.echo(f"Error: {msg}", err=True)
        sys.exit(1)
