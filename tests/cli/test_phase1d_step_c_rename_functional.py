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


# ---------------------------------------------------------------------------
# Hidden-from-help discipline (msg#17078 follow-up)
# ---------------------------------------------------------------------------
#
# The rename stubs must keep working (back-compat for scripts and muscle
# memory) but they must NOT appear in the top-level ``scitex-orochi --help``
# Commands listing — the canonical noun-verb groups are what users discover.


@pytest.mark.parametrize("old,_new_path", RENAMES)
def test_old_form_hidden_from_top_level_help(
    old: str, _new_path: list[str]
) -> None:
    """Rename stubs are registered with ``hidden=True`` and so must not
    appear as bullet entries in the top-level ``--help`` Commands list.

    We look for the stub's short-help signature (``Renamed -- use``) on a
    line that also begins with the legacy name. A naive substring check
    on ``old`` alone would false-match noun groups whose names overlap
    (e.g. ``stop`` matches inside ``host-liveness`` short-help).
    """
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["--help"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 0, result.output

    rename_marker = "Renamed -- use"
    offending = [
        ln
        for ln in result.output.splitlines()
        if rename_marker in ln and ln.lstrip().startswith(old + " ")
    ]
    assert not offending, (
        f"deprecated stub {old!r} should be hidden from top-level help "
        f"but appeared on line(s): {offending}\nfull output:\n{result.output}"
    )


@pytest.mark.parametrize("old,_new_path", RENAMES)
def test_old_form_help_subcommand_still_resolves(
    old: str, _new_path: list[str]
) -> None:
    """Even though hidden from the top-level listing, ``<old> --help``
    must still resolve cleanly so back-compat is preserved (a script
    introspecting the legacy name does not break)."""
    runner = CliRunner()
    result = runner.invoke(
        orochi, [old, "--help"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 0, (
        f"hidden stub {old!r} --help must still resolve; "
        f"got exit {result.exit_code}\noutput: {result.output}"
    )
    assert "Usage:" in result.output
