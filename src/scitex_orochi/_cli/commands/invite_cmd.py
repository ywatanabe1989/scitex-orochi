"""``scitex-orochi invite`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verbs (``invite create``, ``invite list``)
move here in Step C. Step B only ensures ``scitex-orochi invite --help``
works and the group appears in top-level help with an ``(Available
Now)`` suffix when the hub is reachable.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "invite",
    short_help="Workspace invite codes",
    help="Workspace invite codes (create, list).",
)
def invite() -> None:
    """Invite-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(invite)
