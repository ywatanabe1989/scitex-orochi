"""``scitex-orochi message {send,listen,react}`` (Phase 1d Step C + follow-up).

The underlying verb bodies for ``send``/``listen`` still live in
``messaging_cmd.py``; ``react add|remove`` bodies live in
``_message_react_cmd.py`` (msg#16489 queue). This module just re-exposes
them under the ``message`` noun group with short names.

The old flat spellings (``send``, ``listen``) are stubbed in
``_main.py`` to emit ``hard_rename_error`` (plan PR #337 §2, Q1
decision). ``react`` has no flat-legacy form to rename — it was added
directly under the noun group.
"""
# ruff: noqa: E402

from __future__ import annotations

import click

from scitex_orochi._cli._help_availability import annotate_help_with_availability


@click.group(
    "message",
    short_help="Send, listen, and react to messages",
    help="Send, listen, and react to messages (send, listen, react).",
)
def message() -> None:
    """Message-scoped verbs (Phase 1d Step C + react follow-up)."""


from scitex_orochi._cli.commands._message_react_cmd import react as _react
from scitex_orochi._cli.commands.messaging_cmd import listen as _listen
from scitex_orochi._cli.commands.messaging_cmd import send as _send

message.add_command(_send, name="send")
message.add_command(_listen, name="listen")
message.add_command(_react, name="react")

annotate_help_with_availability(message)
