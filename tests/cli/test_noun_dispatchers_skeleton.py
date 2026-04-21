"""Tests for the Phase 1d Step C noun dispatchers + rename stubs.

Step B (PR #342) introduced empty noun groups. Step C (plan PR #337 §2)
now:

* migrates the verb bodies under each noun group (``agent launch`` =
  former ``agent-launch``, ``message send`` = former ``send``, etc.);
* replaces the flat command registrations in ``_main.py`` with
  hard-error stubs that exit non-zero with the rename message.

This test file asserts both invariants for every row of the rename
table in plan §2.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from scitex_orochi._cli._help_availability import (
    AvailabilityAnnotatedGroup,
)
from scitex_orochi._cli._main import orochi

NEW_NOUNS: list[str] = [
    "agent",
    "auth",
    "channel",
    "config",
    "hook",
    "invite",
    "message",
    "push",
    "server",
    "system",
    "workspace",
]


#: Expected verb registry under each noun group after Step C.
EXPECTED_NOUN_VERBS: dict[str, set[str]] = {
    "agent": {"launch", "restart", "stop", "status", "list", "fleet-list"},
    "auth": {"login"},
    "channel": {"list", "join", "history", "members"},
    "config": {"init"},
    "hook": {"report"},
    "invite": {"create", "list"},
    "message": {"send", "listen"},
    "push": {"setup"},
    "server": {"start", "status", "deploy"},
    "system": {"doctor"},
    "workspace": {"create", "delete", "list"},
}


#: Rename table — (old_flat_name, new_noun_verb_path) per plan §2.
RENAME_TABLE: list[tuple[str, str]] = [
    ("agent-launch", "agent launch"),
    ("agent-restart", "agent restart"),
    ("agent-status", "agent status"),
    ("agent-stop", "agent stop"),
    ("list-agents", "agent list"),
    ("fleet", "agent fleet-list"),
    ("launch", "agent launch"),
    ("stop", "agent stop"),
    ("send", "message send"),
    ("listen", "message listen"),
    ("show-history", "channel history"),
    ("join", "channel join"),
    ("list-channels", "channel list"),
    ("list-members", "channel members"),
    ("create-invite", "invite create"),
    ("list-invites", "invite list"),
    ("create-workspace", "workspace create"),
    ("delete-workspace", "workspace delete"),
    ("list-workspaces", "workspace list"),
    ("show-status", "server status"),
    ("serve", "server start"),
    ("deploy", "server deploy"),
    ("setup-push", "push setup"),
    ("init", "config init"),
    ("doctor", "system doctor"),
    ("login", "auth login"),
    ("heartbeat-push", "machine heartbeat send"),
    ("report", "hook report"),
]

#: Flat keepers (Q5) that must remain registered and functional.
FLAT_KEEPERS: list[str] = ["docs", "skills", "mcp"]


# ---------------------------------------------------------------------------
# Noun groups + verb migration (Step C)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_group_is_registered(noun: str) -> None:
    """Every noun group is present on the top-level group."""
    assert noun in orochi.commands, (
        f"noun group {noun!r} missing from scitex-orochi root "
        f"(plan PR #337 §2 / Step C)"
    )
    cmd = orochi.commands[noun]
    assert isinstance(cmd, click.Group), (
        f"{noun!r} must be a click.Group — got {type(cmd).__name__}"
    )


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_group_has_expected_verbs(noun: str) -> None:
    """Step C scope: each noun group contains its migrated verbs."""
    group = orochi.commands[noun]
    assert isinstance(group, click.Group)
    actual = set(group.commands.keys())
    expected = EXPECTED_NOUN_VERBS[noun]
    assert expected.issubset(actual), (
        f"{noun!r} missing verbs: {expected - actual}. Got: {sorted(actual)}"
    )


# ---------------------------------------------------------------------------
# `<noun> --help` renders cleanly with exit 0.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_help_runs_cleanly(noun: str) -> None:
    """``scitex-orochi <noun> --help`` succeeds and prints usage / help."""
    runner = CliRunner()
    result = runner.invoke(
        orochi, [noun, "--help"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 0, (
        f"{noun} --help exited {result.exit_code}\n"
        f"stderr/stdout:\n{result.output}\n"
        f"exception: {result.exception!r}"
    )
    assert "Usage:" in result.output, (
        f"{noun} --help did not print a Usage line; got:\n{result.output}"
    )


# ---------------------------------------------------------------------------
# Availability annotation: each noun group's class is the annotated variant,
# so nested subcommands render with the `(Available Now)` suffix correctly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_group_is_availability_annotated(noun: str) -> None:
    """Each noun group is annotated by :func:`annotate_help_with_availability`."""
    group = orochi.commands[noun]
    assert isinstance(group, AvailabilityAnnotatedGroup), (
        f"{noun!r} must be annotated; got class {type(group).__name__}"
    )


# ---------------------------------------------------------------------------
# Rename stubs (Step C Q1: hard-error, not alias)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("old,new", RENAME_TABLE)
def test_rename_stub_registered(old: str, new: str) -> None:
    """Each legacy flat name is still reachable as a command (the stub)."""
    assert old in orochi.commands, (
        f"legacy flat command {old!r} must remain registered as a "
        f"hard-error rename stub (plan PR #337 §2, Q1 decision)"
    )


@pytest.mark.parametrize("old,new", RENAME_TABLE)
def test_rename_stub_exits_nonzero_with_canonical_message(old: str, new: str) -> None:
    """Invoking the old flat command prints the canonical rename error
    to stderr and exits non-zero (exit code 2 per Step A helper).

    Note: Click 8.3 dropped ``CliRunner(mix_stderr=False)``; stdout and
    stderr are merged into ``result.output`` in the default runner. The
    assertion below therefore checks the combined stream — sufficient
    because ``hard_rename_error`` targets stderr exclusively and the
    stub emits nothing on stdout before exiting.
    """
    runner = CliRunner()
    result = runner.invoke(orochi, [old], obj={"host": "127.0.0.1", "port": 9559})
    assert result.exit_code != 0, (
        f"{old!r} stub should exit non-zero; got {result.exit_code}\n"
        f"output: {result.output!r}"
    )
    expected_line = (
        f"error: `scitex-orochi {old}` was renamed to "
        f"`scitex-orochi {new}`."
    )
    assert expected_line in result.output, (
        f"{old!r} stub did not print expected rename message.\n"
        f"Expected line: {expected_line!r}\n"
        f"Got output: {result.output!r}"
    )


@pytest.mark.parametrize("old,new", RENAME_TABLE)
def test_rename_stub_swallows_extra_args(old: str, new: str) -> None:
    """Users who still run the old form with old flags/args must hit the
    rename error (not a click usage error). The stub accepts arbitrary
    trailing tokens."""
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        [old, "--some-old-flag", "extra", "args"],
        obj={"host": "127.0.0.1", "port": 9559},
    )
    assert result.exit_code != 0
    assert "was renamed" in result.output, (
        f"{old!r} stub should print rename message even with trailing "
        f"args; got output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Flat keepers (Q5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", FLAT_KEEPERS)
def test_flat_keeper_still_registered(name: str) -> None:
    """`docs`, `skills`, `mcp` stay flat with their original behaviour."""
    assert name in orochi.commands
    cmd = orochi.commands[name]
    # All three keepers are groups with subcommands (docs: list/get,
    # skills: list/index, mcp: start); they must not be rename stubs.
    assert isinstance(cmd, click.Group), (
        f"flat keeper {name!r} must remain a click.Group, not a stub"
    )
