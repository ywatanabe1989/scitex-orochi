"""Functional parity tests for Phase 1d Step C (plan PR #337 §2).

For each row of the rename table:

1. **(a) New form works** — ``scitex-orochi <new noun verb> --help``
   renders cleanly (exit 0) so we know the verb actually reached its
   target under the noun group.
2. **(b) Old form hard-errors** — ``scitex-orochi <old>`` exits non-zero
   and prints the canonical rename message. (The stronger parametrized
   checks live in ``test_noun_dispatchers_skeleton.py``; this file
   keeps a per-row functional smoke pair so a failure is legible.)

We deliberately avoid running the verb *bodies* here — those hit the
hub/filesystem and already have their own tests. Checking ``--help``
proves the re-registration reached the right group with a callable
command behind it.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi

# Rename table — (old, new_path) where new_path is a list of CLI tokens
# (not a space-joined string) to avoid ambiguity for verbs whose name
# contains a hyphen (``fleet-list``).
RENAMES: list[tuple[str, list[str]]] = [
    ("agent-launch", ["agent", "launch"]),
    ("agent-restart", ["agent", "restart"]),
    ("agent-status", ["agent", "status"]),
    ("agent-stop", ["agent", "stop"]),
    ("list-agents", ["agent", "list"]),
    ("fleet", ["agent", "fleet-list"]),
    ("launch", ["agent", "launch"]),
    ("stop", ["agent", "stop"]),
    ("send", ["message", "send"]),
    ("listen", ["message", "listen"]),
    ("show-history", ["channel", "history"]),
    ("join", ["channel", "join"]),
    ("list-channels", ["channel", "list"]),
    ("list-members", ["channel", "members"]),
    ("create-invite", ["invite", "create"]),
    ("list-invites", ["invite", "list"]),
    ("create-workspace", ["workspace", "create"]),
    ("delete-workspace", ["workspace", "delete"]),
    ("list-workspaces", ["workspace", "list"]),
    ("show-status", ["server", "status"]),
    ("serve", ["server", "start"]),
    ("deploy", ["server", "deploy"]),
    ("setup-push", ["push", "setup"]),
    ("init", ["config", "init"]),
    ("doctor", ["system", "doctor"]),
    ("login", ["auth", "login"]),
    ("heartbeat-push", ["machine", "heartbeat", "send"]),
    ("report", ["hook", "report"]),
]


@pytest.mark.parametrize("old,new_path", RENAMES)
def test_new_form_help_is_reachable(old: str, new_path: list[str]) -> None:
    """The migrated verb is reachable via the nested noun-verb path."""
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        new_path + ["--help"],
        obj={"host": "127.0.0.1", "port": 9559},
    )
    assert result.exit_code == 0, (
        f"`scitex-orochi {' '.join(new_path)} --help` failed for rename "
        f"of {old!r}.\nexit: {result.exit_code}\noutput: {result.output}\n"
        f"exception: {result.exception!r}"
    )
    # Click puts "Usage:" at the top of every help invocation.
    assert "Usage:" in result.output


@pytest.mark.parametrize("old,new_path", RENAMES)
def test_old_form_hard_errors(old: str, new_path: list[str]) -> None:
    """The legacy flat name still exists but now emits a hard rename error."""
    runner = CliRunner()
    result = runner.invoke(
        orochi, [old], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code != 0, (
        f"flat {old!r} should exit non-zero under rename policy; "
        f"got {result.exit_code}\noutput: {result.output}"
    )
    expected_new = " ".join(new_path)
    assert (
        f"error: `scitex-orochi {old}` was renamed to "
        f"`scitex-orochi {expected_new}`."
    ) in result.output
