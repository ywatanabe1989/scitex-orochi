"""``scitex-orochi system {doctor}`` (Phase 1d Step C).

The verb body lives in ``doctor_cmd.py`` (the flat command was plain
``doctor``). We re-expose it under the ``system`` noun group with a
short name.

The old flat spelling (``doctor``) is stubbed in ``_main.py`` to emit
``hard_rename_error`` (plan PR #337 §2, Q1 decision).
"""
# ruff: noqa: E402
# (E402 is ignored file-wide so the noun-group decorator can run before
# the deferred verb imports below — the pattern mirrors ``_main.py``.)

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "system",
    short_help="Host-side self-diagnosis",
    help="Host-side self-diagnosis (doctor).",
)
def system() -> None:
    """System-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.doctor_cmd import doctor_cmd as _doctor_cmd

system.add_command(_doctor_cmd, name="doctor")

annotate_help_with_availability(system)
