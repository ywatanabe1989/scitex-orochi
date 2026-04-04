"""Orochi CLI -- thin orchestrator that registers all subcommands."""

from __future__ import annotations

import sys

import click


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
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


# ── Register subcommands ────────────────────────────────────────
from scitex_orochi._cli.commands.deploy_cmd import deploy
from scitex_orochi._cli.commands.health_cmd import health_cmd
from scitex_orochi._cli.commands.init_cmd import init_cmd
from scitex_orochi._cli.commands.launch_cmd import launch
from scitex_orochi._cli.commands.messaging_cmd import join, listen, login, send
from scitex_orochi._cli.commands.query_cmd import (
    channels_cmd,
    heartbeat,
    history,
    members,
    status,
    who,
)
from scitex_orochi._cli.commands.server_cmd import serve, vapid_generate

# Messaging
orochi.add_command(send)
orochi.add_command(listen)
orochi.add_command(login)
orochi.add_command(join)

# Queries
orochi.add_command(who)
orochi.add_command(status)
orochi.add_command(channels_cmd)
orochi.add_command(members)
orochi.add_command(history)
orochi.add_command(heartbeat)

# Server
orochi.add_command(serve)
orochi.add_command(vapid_generate)

# Deployment
orochi.add_command(init_cmd)
orochi.add_command(launch)
orochi.add_command(health_cmd)
orochi.add_command(deploy)


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
