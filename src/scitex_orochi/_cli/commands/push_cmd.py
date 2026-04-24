"""``scitex-orochi push {setup}`` (Phase 1d Step C).

The verb body lives in ``server_cmd.py`` (historical wiring — the flat
command was ``setup-push``). We re-expose it under the ``push`` noun
group with a short name.

``push send`` is listed in the plan noun registry but has no flat
predecessor to migrate; that's Phase 2 work.

The old flat spelling (``setup-push``) is stubbed in ``_main.py`` to
emit ``hard_rename_error`` (plan PR #337 §2, Q1 decision).
"""
# ruff: noqa: E402

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "push",
    short_help="Push-notification plumbing",
    help="Push-notification plumbing (setup).",
)
def push() -> None:
    """Push-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.server_cmd import setup_push as _setup_push

push.add_command(_setup_push, name="setup")

annotate_help_with_availability(push)
