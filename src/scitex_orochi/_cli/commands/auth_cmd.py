"""``scitex-orochi auth {login}`` (Phase 1d Step C).

The verb body lives in ``messaging_cmd.py`` (historical wiring — the
flat command was plain ``login``). We re-expose it under the ``auth``
noun group with a short name.

The old flat spelling (``login``) is stubbed in ``_main.py`` to emit
``hard_rename_error`` (plan PR #337 §2, Q1 decision).
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "auth",
    short_help="Credential / session management",
    help="Credential / session management (login).",
)
def auth() -> None:
    """Auth-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.messaging_cmd import login as _login  # noqa: E402

auth.add_command(_login, name="login")

annotate_help_with_availability(auth)
