"""``scitex-orochi system`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verb (``system doctor``, replacing top-level
``doctor``) moves here in Step C. Step B only ensures ``scitex-orochi
system --help`` works and the group appears in top-level help with an
``(Available Now)`` suffix when the hub is reachable.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "system",
    short_help="Host-side self-diagnosis",
    help="Host-side self-diagnosis (doctor).",
)
def system() -> None:
    """System-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(system)
