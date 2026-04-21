"""``scitex-orochi channel`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verbs (``channel list``, ``channel join``,
``channel history``, ``channel members``) move here in Step C. Step B
only ensures ``scitex-orochi channel --help`` works and the group is
visible in top-level help with an ``(Available Now)`` suffix when the
hub is reachable.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "channel",
    short_help="Channel membership and history",
    help="Channel membership and history (list, join, history, members).",
)
def channel() -> None:
    """Channel-scoped verbs. Subcommands populate in Phase 1d Step C."""


# Annotate nested help so Step C's verbs will render with the
# ``(Available Now)`` suffix as soon as they are registered.
annotate_help_with_availability(channel)
