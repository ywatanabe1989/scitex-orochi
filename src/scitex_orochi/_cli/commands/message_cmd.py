"""``scitex-orochi message`` — empty noun group (Phase 1d Step B).

Step B (PR plan §2 / #337) lays the dispatcher skeleton. This group is
deliberately empty — the verbs (``message send``, ``message listen``,
``message react add``, ``message react remove``) move here in Step C.
Step B only ensures ``scitex-orochi message --help`` works and the
group appears in top-level help with an ``(Available Now)`` suffix
when the hub is reachable.

See ``src/scitex_orochi/_skills/scitex-orochi/convention-cli.md`` §1.1
for the full noun-group registry.
"""

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "message",
    short_help="Send, listen, and react to messages",
    help="Send, listen, and react to messages (send, listen, react add/remove).",
)
def message() -> None:
    """Message-scoped verbs. Subcommands populate in Phase 1d Step C."""


annotate_help_with_availability(message)
