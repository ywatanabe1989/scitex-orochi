"""``scitex-orochi channel {list,join,history,members}`` (Phase 1d Step C).

The underlying verb bodies still live in ``query_cmd.py`` and
``messaging_cmd.py`` — this module just re-exposes them under the
``channel`` noun group with short names.

The old flat spellings (``list-channels``, ``join``, ``show-history``,
``list-members``) are stubbed in ``_main.py`` to emit
``hard_rename_error`` (plan PR #337 §2, Q1 decision).
"""
# ruff: noqa: E402
# (E402 is ignored file-wide so the noun-group decorator can run before
# the deferred verb imports below — the pattern mirrors ``_main.py``.)

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "channel",
    short_help="Channel membership and history",
    help="Channel membership and history (list, join, history, members).",
)
def channel() -> None:
    """Channel-scoped verbs (Phase 1d Step C)."""


# Deferred registrations — ``query_cmd`` / ``messaging_cmd`` import
# lightweight helpers only, so we can pull them at module-import time
# without a cycle.
from scitex_orochi._cli.commands.messaging_cmd import join as _join
from scitex_orochi._cli.commands.query_cmd import list_channels as _list_channels
from scitex_orochi._cli.commands.query_cmd import list_members as _list_members
from scitex_orochi._cli.commands.query_cmd import show_history as _show_history

channel.add_command(_list_channels, name="list")
channel.add_command(_join, name="join")
channel.add_command(_show_history, name="history")
channel.add_command(_list_members, name="members")

annotate_help_with_availability(channel)
