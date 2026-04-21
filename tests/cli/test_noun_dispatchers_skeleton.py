"""Tests for the Phase 1d Step B noun dispatcher skeleton.

Plan PR #337 §2 / Step B scope:

* 11 new empty noun groups (``agent``, ``channel``, ``workspace``,
  ``invite``, ``message``, ``push``, ``server``, ``config``, ``system``,
  ``auth``, ``hook``) are registered under the top-level ``scitex-orochi``
  click group.
* Each new group's ``--help`` must succeed with exit 0, must print the
  group's short-help, and must NOT have any subcommands yet — Step C
  adds the verbs.
* Each new group's class must be annotated by
  :func:`annotate_help_with_availability` (the decorator is a no-op on
  empty groups today, but the attribute check protects Step C from
  regressing: nested help needs the annotated class already in place
  the moment a verb lands).
* The pre-existing flat verbs (``list-agents``, ``send``,
  ``create-workspace``, ``serve``, ``doctor``, ``init``, ``login``,
  ``deploy``, ``report``, …) must still be registered unchanged —
  Step B is additive only.
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


#: Legacy flat commands that must remain registered in Step B. Step C
#: will migrate / alias them; Step B touches none of them.
LEGACY_FLAT_COMMANDS: list[str] = [
    "agent-launch",
    "agent-restart",
    "agent-status",
    "agent-stop",
    "create-invite",
    "create-workspace",
    "delete-workspace",
    "deploy",
    "doctor",
    "fleet",
    "heartbeat-push",
    "init",
    "join",
    "launch",
    "list-agents",
    "list-channels",
    "list-invites",
    "list-members",
    "list-workspaces",
    "listen",
    "login",
    "report",
    "send",
    "serve",
    "setup-push",
    "show-history",
    "show-status",
    "stop",
]


# ---------------------------------------------------------------------------
# Registration: every new noun is a click group hanging off the root.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_group_is_registered(noun: str) -> None:
    """Every Phase 1d Step B noun group is present on the top-level group."""
    assert noun in orochi.commands, (
        f"noun group {noun!r} missing from scitex-orochi root "
        f"(plan PR #337 §2 / Step B)"
    )
    cmd = orochi.commands[noun]
    assert isinstance(cmd, click.Group), (
        f"{noun!r} must be a click.Group — got {type(cmd).__name__}"
    )


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_group_has_no_verbs_yet(noun: str) -> None:
    """Step B scope: empty groups only. Verbs land in Step C."""
    group = orochi.commands[noun]
    assert isinstance(group, click.Group)
    assert dict(group.commands) == {}, (
        f"{noun!r} must be empty in Step B; found verbs: "
        f"{sorted(group.commands.keys())}"
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
    # Click always prints "Usage: ..." on --help; that's a safe canary.
    assert "Usage:" in result.output, (
        f"{noun} --help did not print a Usage line; got:\n{result.output}"
    )


# ---------------------------------------------------------------------------
# Availability annotation: each new group's class is the annotated variant,
# so nested subcommands (arriving in Step C) inherit the `(Available Now)`
# rendering without a second wiring step.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("noun", NEW_NOUNS)
def test_noun_group_is_availability_annotated(noun: str) -> None:
    """Each Step B noun group has been passed through
    :func:`annotate_help_with_availability` so Step C's nested verbs get
    the suffix treatment automatically."""
    group = orochi.commands[noun]
    assert isinstance(group, AvailabilityAnnotatedGroup), (
        f"{noun!r} must be annotated by annotate_help_with_availability; "
        f"got class {type(group).__name__}"
    )


# ---------------------------------------------------------------------------
# Legacy commands stay registered (Step B is additive only).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", LEGACY_FLAT_COMMANDS)
def test_legacy_flat_command_still_registered(name: str) -> None:
    """Step B must not remove / rename any flat command — Step C handles that."""
    assert name in orochi.commands, (
        f"legacy flat command {name!r} disappeared in Step B; "
        f"registration should be unchanged"
    )
