"""``scitex-orochi invite {create,list}`` (Phase 1d Step C).

The verb bodies live in ``workspace_cmd.py`` (historical wiring — the
original flat commands were ``create-invite`` / ``list-invites`` which
are workspace-scoped operations). We re-expose them under the
``invite`` noun group with short names.

The old flat spellings (``create-invite``, ``list-invites``) are
stubbed in ``_main.py`` to emit ``hard_rename_error`` (plan PR #337
§2, Q1 decision).
"""
# ruff: noqa: E402

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "invite",
    short_help="Workspace invite codes",
    help="Workspace invite codes (create, list).",
)
def invite() -> None:
    """Invite-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.workspace_cmd import create_invite as _create_invite
from scitex_orochi._cli.commands.workspace_cmd import list_invites as _list_invites

invite.add_command(_create_invite, name="create")
invite.add_command(_list_invites, name="list")

annotate_help_with_availability(invite)
