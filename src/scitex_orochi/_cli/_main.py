"""Orochi CLI -- thin orchestrator that registers all subcommands.

Subcommand imports must be deferred until after the ``orochi`` click group is
defined below (each command attaches itself to this group via
``orochi.add_command``). Ruff's E402 check is suppressed at file level for
that reason.
"""
# ruff: noqa: E402

from __future__ import annotations

import sys

import click


def _get_version() -> str:
    from importlib.metadata import version

    try:
        return version("scitex-orochi")
    except Exception:
        return "dev"


class _HelpRecursiveGroup(click.Group):
    """Click group that supports ``--help-recursive`` to dump every subcommand."""

    def get_help_recursive(self, ctx: click.Context) -> str:
        lines = [
            "=" * 60,
            "scitex-orochi -- Complete Command Reference",
            "=" * 60,
            "",
            self.get_help(ctx),
            "",
        ]
        for name in sorted(self.list_commands(ctx)):
            cmd = self.get_command(ctx, name)
            if cmd is None:
                continue
            lines.append("-" * 60)
            lines.append(f"Command: {name}")
            lines.append("-" * 60)
            sub_ctx = click.Context(cmd, info_name=name, parent=ctx)
            try:
                lines.append(cmd.get_help(sub_ctx))
            except Exception as exc:  # pragma: no cover - defensive
                lines.append(f"<help unavailable: {exc}>")
            lines.append("")
        return "\n".join(lines)


@click.group(
    cls=_HelpRecursiveGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
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
@click.option(
    "--help-recursive",
    "help_recursive",
    is_flag=True,
    default=False,
    help="Show help for all commands recursively, then exit.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit structured JSON output (propagates to subcommands that honour it).",
)
@click.pass_context
def orochi(
    ctx: click.Context,
    host: str | None,
    port: int | None,
    help_recursive: bool,
    as_json: bool,
) -> None:
    """scitex-orochi -- Agent Communication Hub CLI."""
    from scitex_orochi._config import HOST, PORT

    ctx.ensure_object(dict)
    ctx.obj["host"] = host or HOST
    ctx.obj["port"] = port or PORT
    ctx.obj["json"] = as_json
    from scitex_orochi._config import DASHBOARD_PORT

    ctx.obj["dashboard_port"] = DASHBOARD_PORT

    if help_recursive:
        click.echo(ctx.command.get_help_recursive(ctx))  # type: ignore[attr-defined]
        ctx.exit(0)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit(0)


# ── Register subcommands ────────────────────────────────────────
from scitex_orochi._cli.commands.agent_cmd import (
    agent_launch,
    agent_restart,
    agent_status,
    agent_stop,
)
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

# Agent lifecycle (direct screen-based management)
orochi.add_command(agent_launch)
orochi.add_command(agent_restart)
orochi.add_command(agent_stop)
orochi.add_command(agent_status)

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

# Deployment (legacy agent-container based)
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

# Non-agentic heartbeat pusher (consumes scitex-agent-container CLI)
from scitex_orochi._cli.commands.heartbeat_cmd import heartbeat_push

orochi.add_command(heartbeat_push)

# Integration
orochi.add_command(docs)
orochi.add_command(skills)

# Host identity (local-vs-remote resolver)
from scitex_orochi._cli.commands.host_identity_cmd import host_identity

orochi.add_command(host_identity)

# Unified cron daemon (msg#16406 / msg#16410)
from scitex_orochi._cli.commands.cron_cmd import cron as cron_group

orochi.add_command(cron_group)

# ── Host-side ops (migrated from scripts/client/*.sh) ────────
from scitex_orochi._cli.commands.chrome_watchdog_cmd import chrome_watchdog
from scitex_orochi._cli.commands.disk_cmd import disk
from scitex_orochi._cli.commands.host_liveness_cmd import host_liveness
from scitex_orochi._cli.commands.hungry_signal_cmd import hungry_signal
from scitex_orochi._cli.commands.machine_cmd import machine

orochi.add_command(machine)
orochi.add_command(host_liveness)
orochi.add_command(hungry_signal)
orochi.add_command(disk)
orochi.add_command(chrome_watchdog)

# ── Fleet-coordination verbs (Phase 1c, msg#16477) ───────────
from scitex_orochi._cli.commands.dispatch_cmd import dispatch as dispatch_group
from scitex_orochi._cli.commands.todo_cmd import todo as todo_group

orochi.add_command(todo_group)
orochi.add_command(dispatch_group)

# ── Phase 1d Step A: flat-keeper `mcp start` (Q5, plan PR #337) ─
# Only mcp-client configs read this literal path, so it stays flat.
from scitex_orochi._cli.commands.mcp_cmd import mcp as mcp_group

orochi.add_command(mcp_group)

# ── Phase 1d Step B: noun dispatcher skeleton (plan §2, PR #337) ───
# Empty click groups for every canonical top-level noun. Verbs move
# under them in Step C — Step B only wires the dispatchers themselves
# so that `scitex-orochi <noun> --help` is well-formed *before* any
# rename and so nested help can already annotate reachability.
#
# The legacy flat verbs (`list-agents`, `send`, `create-workspace`,
# `serve`, `doctor`, `init`, `login`, `deploy`, `report`, …) stay
# registered and functional in Step B; they are migrated and aliased
# off in Step C.
from scitex_orochi._cli.commands.agent_cmd import agent as agent_group
from scitex_orochi._cli.commands.auth_cmd import auth as auth_group
from scitex_orochi._cli.commands.channel_cmd import channel as channel_group
from scitex_orochi._cli.commands.config_cmd import config as config_group
from scitex_orochi._cli.commands.hook_cmd import hook as hook_group
from scitex_orochi._cli.commands.invite_cmd import invite as invite_group
from scitex_orochi._cli.commands.message_cmd import message as message_group
from scitex_orochi._cli.commands.push_cmd import push as push_group
from scitex_orochi._cli.commands.server_cmd import server as server_group
from scitex_orochi._cli.commands.system_cmd import system as system_group
from scitex_orochi._cli.commands.workspace_cmd import workspace as workspace_group

orochi.add_command(agent_group)
orochi.add_command(auth_group)
orochi.add_command(channel_group)
orochi.add_command(config_group)
orochi.add_command(hook_group)
orochi.add_command(invite_group)
orochi.add_command(message_group)
orochi.add_command(push_group)
orochi.add_command(server_group)
orochi.add_command(system_group)
orochi.add_command(workspace_group)

# ── Phase 1d Step A: (Available Now) help-suffix layer ───────
# Annotates `--help` output of the top-level group with a quiet
# "(Available Now)" next to each reachable subcommand. See plan §9
# (PR #337). Top-level was Step A; Step B extends the probe map to
# cover the new noun groups and applies the same decorator to each
# of them (so Step C's nested verbs inherit it for free).
from scitex_orochi._cli._help_availability import annotate_help_with_availability

annotate_help_with_availability(orochi)


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
