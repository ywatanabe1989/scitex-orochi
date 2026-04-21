"""``scitex-orochi message {send,listen}`` (Phase 1d Step C).

The underlying verb bodies still live in ``messaging_cmd.py`` — this
module just re-exposes them under the ``message`` noun group with short
names. ``react add/remove`` remain future work (plan §2 lists them in
the noun registry; no flat verb to migrate).

The old flat spellings (``send``, ``listen``) are stubbed in
``_main.py`` to emit ``hard_rename_error`` (plan PR #337 §2, Q1
decision).
"""
# ruff: noqa: E402

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "message",
    short_help="Send and listen to messages",
    help="Send and listen to messages (send, listen).",
)
def message() -> None:
    """Message-scoped verbs (Phase 1d Step C)."""


from scitex_orochi._cli.commands.messaging_cmd import listen as _listen
from scitex_orochi._cli.commands.messaging_cmd import send as _send

message.add_command(_send, name="send")
message.add_command(_listen, name="listen")

annotate_help_with_availability(message)
