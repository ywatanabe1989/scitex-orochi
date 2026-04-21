"""``scitex-orochi config {init}`` (Phase 1d Step C).

The verb body lives in ``init_cmd.py`` (the flat command was plain
``init``). We re-expose it under the ``config`` noun group with a short
name.

The old flat spelling (``init``) is stubbed in ``_main.py`` to emit
``hard_rename_error`` (plan PR #337 §2, Q1 decision).
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "config",
    short_help="Local scitex-orochi config",
    help="Local scitex-orochi config (init).",
)
def config() -> None:
    """Config-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.init_cmd import init_cmd as _init_cmd  # noqa: E402

config.add_command(_init_cmd, name="init")

annotate_help_with_availability(config)
