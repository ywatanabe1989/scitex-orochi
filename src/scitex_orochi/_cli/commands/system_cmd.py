"""``scitex-orochi system {doctor,venv-check,venv-heal}`` (Phase 1d Step C).

``doctor``      -- existing full-stack health check (see ``doctor_cmd``).
``venv-check``  -- critical-package import probe (msg#16777 regression).
``venv-heal``   -- ``venv-check`` + opt-in ``pip install -e`` remediation.

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
    help="Host-side self-diagnosis (doctor, venv-check, venv-heal).",
)
def system() -> None:
    """System-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.doctor_cmd import doctor_cmd as _doctor_cmd
from scitex_orochi._cli.commands.venv_check_cmd import (
    venv_check_cmd as _venv_check_cmd,
)
from scitex_orochi._cli.commands.venv_check_cmd import (
    venv_heal_cmd as _venv_heal_cmd,
)

system.add_command(_doctor_cmd, name="doctor")
system.add_command(_venv_check_cmd, name="venv-check")
system.add_command(_venv_heal_cmd, name="venv-heal")

annotate_help_with_availability(system)
