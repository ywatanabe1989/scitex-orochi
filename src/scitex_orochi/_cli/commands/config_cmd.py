"""``scitex-orochi config`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verb (``config init``, replacing top-level
``init``) moves here in Step C. Step B only ensures ``scitex-orochi
config --help`` works. ``config`` is pure-local so no ``(Available
Now)`` suffix is ever shown — its backing operations write local
state only.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
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
    """Config-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(config)
