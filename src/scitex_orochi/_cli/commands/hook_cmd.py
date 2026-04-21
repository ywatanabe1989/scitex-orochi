"""``scitex-orochi hook {report ...}`` (Phase 1d Step C).

The verb bodies live in ``report_cmd.py`` as a nested click group
(``report activity`` / ``report stuck`` / ``report heartbeat``). The
entire group moves under ``hook`` wholesale so those three verbs are
reachable as ``scitex-orochi hook report activity`` / ``stuck`` /
``heartbeat``.

The old flat spelling (``report …``) is stubbed in ``_main.py`` to
emit ``hard_rename_error`` (plan PR #337 §2, Q1 decision).
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "hook",
    short_help="Claude Code / framework hook reports",
    help="Claude Code / framework hook reports (report activity/stuck/heartbeat).",
)
def hook() -> None:
    """Hook-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.report_cmd import report as _report_group  # noqa: E402

hook.add_command(_report_group, name="report")

annotate_help_with_availability(hook)
