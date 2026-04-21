"""``scitex-orochi push`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verbs (``push setup``, ``push send``) move
here in Step C. Step B only ensures ``scitex-orochi push --help``
works and the group appears in top-level help with an ``(Available
Now)`` suffix when the hub is reachable.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "push",
    short_help="APNs / push-notification plumbing",
    help="APNs / push-notification plumbing (setup, send).",
)
def push() -> None:
    """Push-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(push)
