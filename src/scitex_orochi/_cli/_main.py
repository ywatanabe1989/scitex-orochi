"""Orochi CLI -- thin orchestrator that registers all subcommands."""

from __future__ import annotations

import sys

import click


def _get_version() -> str:
    from importlib.metadata import version

    try:
        return version("scitex-orochi")
    except Exception:
        return "dev"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=_get_version(), prog_name="scitex-orochi")
@click.option(
    "--host",
    default=None,
    envvar="SCITEX_OROCHI_HOST",
    help="Server host [$SCITEX_OROCHI_HOST].",
)
@click.option(
    "--port",
    default=None,
    type=int,
    envvar="SCITEX_OROCHI_PORT",
    help="Server port [$SCITEX_OROCHI_PORT].",
)
@click.pass_context
def orochi(ctx: click.Context, host: str | None, port: int | None) -> None:
    """scitex-orochi -- Agent Communication Hub CLI."""
    from scitex_orochi._config import HOST, PORT

    ctx.ensure_object(dict)
    ctx.obj["host"] = host or HOST
    ctx.obj["port"] = port or PORT
    from scitex_orochi._config import DASHBOARD_PORT

    ctx.obj["dashboard_port"] = DASHBOARD_PORT


# ── Register subcommands ────────────────────────────────────────
from scitex_orochi._cli.commands.deploy_cmd import deploy
from scitex_orochi._cli.commands.docs_cmd import docs
from scitex_orochi._cli.commands.doctor_cmd import doctor_cmd
from scitex_orochi._cli.commands.fleet_cmd import fleet
from scitex_orochi._cli.commands.init_cmd import init_cmd
from scitex_orochi._cli.commands.launch_cmd import launch
from scitex_orochi._cli.commands.messaging_cmd import join, listen, login, send
from scitex_orochi._cli.commands.query_cmd import (
    list_agents,
    list_channels,
    list_members,
    show_history,
    show_status,
)
from scitex_orochi._cli.commands.report_cmd import report
from scitex_orochi._cli.commands.server_cmd import serve, setup_push
from scitex_orochi._cli.commands.skills_cmd import skills

# Fleet
orochi.add_command(fleet)

# Messaging
orochi.add_command(send)
orochi.add_command(listen)
orochi.add_command(login)
orochi.add_command(join)

# Queries
orochi.add_command(list_agents)
orochi.add_command(show_status)
orochi.add_command(list_channels)
orochi.add_command(list_members)
orochi.add_command(show_history)

# Server
orochi.add_command(serve)
orochi.add_command(doctor_cmd)
orochi.add_command(setup_push)

from scitex_orochi._cli.commands.stop_cmd import stop as stop_cmd

# Deployment
orochi.add_command(init_cmd)
orochi.add_command(launch)
orochi.add_command(deploy)
orochi.add_command(stop_cmd)

# Workspace
from scitex_orochi._cli.commands.workspace_cmd import (
    create_invite,
    create_workspace,
    delete_workspace,
    list_invites,
    list_workspaces,
)

orochi.add_command(create_workspace)
orochi.add_command(delete_workspace)
orochi.add_command(list_workspaces)
orochi.add_command(create_invite)
orochi.add_command(list_invites)

# Hook-driven liveness reporting (#143)
orochi.add_command(report)

# Integration
orochi.add_command(docs)
orochi.add_command(skills)


def main() -> None:
    try:
        orochi(standalone_mode=True)
    except KeyboardInterrupt:
        pass
    except ConnectionRefusedError:
        from scitex_orochi._config import HOST, PORT

        click.echo(
            f"Error: Connection refused at {HOST}:{PORT}\n"
            f"\n"
            f"  Start the server:  scitex-orochi serve\n"
            f"  Or connect elsewhere:"
            f"  scitex-orochi --host <IP> --port <PORT> <command>",
            err=True,
        )
        sys.exit(1)
    except OSError as exc:
        from scitex_orochi._config import HOST, PORT

        click.echo(
            f"Error: Cannot reach {HOST}:{PORT} -- {exc}\n"
            f"\n"
            f"  Check the host:"
            f"  scitex-orochi --host <IP> --port <PORT> <command>\n"
            f"  Or set env var:  export SCITEX_OROCHI_HOST=<IP>",
            err=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
