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
    """Click group that supports ``--help-recursive`` to dump every subcommand.

    Hidden subcommands (e.g. the Phase-1d rename stubs whose presence in
    ``--help`` would clutter the listing) are skipped entirely: they don't
    appear in the top-level ``Commands`` block and they don't appear in
    the recursive dump either. Invoking them by name still works — the
    hard-error still fires — the goal here is simply to avoid advertising
    dead paths in help output.
    """

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
            if getattr(cmd, "hidden", False):
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


# Plan §11.2: the top-level ``--help`` output ends with a one-line
# pointer at the noun-verb convention doc so fleet agents can grep
# ``scitex-orochi --help`` and land on the skill directly.
_CLI_CONVENTION_EPILOG = (
    "See docs/cli.md for the noun-verb convention (scitex-orochi/convention-cli skill)."
)


@click.group(
    cls=_HelpRecursiveGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    epilog=_CLI_CONVENTION_EPILOG,
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
# Phase 1d Step C (plan PR #337 §2, Q1 decision): flat command names
# are now hard-error stubs that tell the user the new form. The verb
# bodies live under the noun dispatchers below.
from scitex_orochi._cli._deprecation import make_rename_stub
from scitex_orochi._cli.commands.docs_cmd import docs
from scitex_orochi._cli.commands.skills_cmd import skills

# Rename table (plan §2). Each tuple is (old_flat_name, new_noun_verb).
# The stub accepts any trailing args so users who still run the old
# form with its old flags still hit the rename error rather than a
# confusing click parse failure.
_RENAMES: list[tuple[str, str]] = [
    # Agent lifecycle
    ("agent-launch", "agent launch"),
    ("agent-restart", "agent restart"),
    ("agent-status", "agent status"),
    ("agent-stop", "agent stop"),
    ("list-agents", "agent list"),
    ("fleet", "agent fleet-list"),
    # Flat `launch` (group with master/head/all) and flat `stop` both
    # mapped to the agent-lifecycle nouns per plan §2 (ambiguous-stop
    # resolution: implementation targets fleet agents).
    ("launch", "agent launch"),
    ("stop", "agent stop"),
    # Messaging
    ("send", "message send"),
    ("listen", "message listen"),
    # Channels
    ("show-history", "channel history"),
    ("join", "channel join"),
    ("list-channels", "channel list"),
    ("list-members", "channel members"),
    # Invites
    ("create-invite", "invite create"),
    ("list-invites", "invite list"),
    # Workspaces
    ("create-workspace", "workspace create"),
    ("delete-workspace", "workspace delete"),
    ("list-workspaces", "workspace list"),
    # Server
    ("show-status", "server status"),
    ("serve", "server start"),
    ("deploy", "server deploy"),
    # Push
    ("setup-push", "push setup"),
    # Config
    ("init", "config init"),
    # System
    ("doctor", "system doctor"),
    # Auth
    ("login", "auth login"),
    # Machine (Q1 rename, even though `machine heartbeat send` already
    # exists from PR #336 — the flat form still needs a hard error).
    ("heartbeat-push", "machine heartbeat send"),
    # Hook
    ("report", "hook report"),
]

for _old, _new in _RENAMES:
    orochi.add_command(make_rename_stub(_old, _new))

# Flat keepers (Q5): docs and skills stay flat, no rename.
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

# ── Phase 1d Step C: noun dispatchers with migrated verbs (plan §2, PR #337) ─
# Click groups for every canonical top-level noun. Verbs have been
# migrated under them (Step C). Flat legacy verbs now hard-error via
# the rename table above.
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
