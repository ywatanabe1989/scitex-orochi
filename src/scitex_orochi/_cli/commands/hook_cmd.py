"""``scitex-orochi hook`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verbs (``hook report activity``, ``hook report
stuck``, ``hook report heartbeat``) move here in Step C. Step B only
ensures ``scitex-orochi hook --help`` works and the group appears in
top-level help with an ``(Available Now)`` suffix when the hub is
reachable.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
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
    """Hook-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(hook)
