"""Tests for the Phase 1d Step C noun dispatchers.

Step B (PR #342) introduced empty noun groups. Step C (plan PR #337 §2)
migrates the verb bodies under each noun group (``agent launch`` =
former ``agent-launch``, ``message send`` = former ``send``, etc.).

The legacy flat verb-noun aliases that briefly co-existed as hard-error
rename stubs were deleted in the msg#17078 follow-up — their grace
period under interface-cli §5 has ended. This file therefore asserts
the canonical noun-verb surface only; the post-removal contract for
legacy names is locked in
``test_phase1d_step_c_rename_functional.test_legacy_flat_alias_is_unknown_command``.
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
    "message": {"send", "listen", "react"},
    "push": {"setup"},
    "server": {"start", "status", "deploy"},
    "system": {"doctor"},
    "workspace": {"create", "delete", "list"},
}


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
