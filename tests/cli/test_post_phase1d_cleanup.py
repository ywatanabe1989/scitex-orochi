"""Regression tests for the post-Phase-1d CLI cleanup.

After Phase 1d shipped (PRs #341–#344), the ``scitex-orochi --help``
output still felt "dirty" (ywatanabe msg#16746) because the 28 rename
stubs were *visible* in the top-level command listing. Each one showed
a ``Renamed -- use ...`` short-help line next to a legit command,
burying the actual noun groups under legacy clutter.

Fix:

1. Rename stubs are now ``hidden=True`` by default
   (:func:`scitex_orochi._cli._deprecation.make_rename_stub`).
2. The custom ``--help-recursive`` dumper in
   :class:`scitex_orochi._cli._main._HelpRecursiveGroup` skips hidden
   commands, so they don't appear in the recursive dump either.
3. The top-level ``--help`` output now ends with a one-line pointer
   at the noun-verb convention doc (plan §11.2).

Invariants this file pins (so the dirt cannot come back):

* ``--help`` never prints any ``Renamed -- use`` short-help line
  (the 28 stubs stay out of the listing).
* ``--help-recursive`` never renders a ``Command: <old-name>`` header
  for any of the renamed flat legacy names.
* The convention pointer (docs/cli.md) appears at the end of ``--help``.
* Invoking the old flat name STILL hard-errors with the canonical
  rename message (hidden ≠ removed). We re-assert one representative
  case here; the full matrix stays in ``test_phase1d_step_c_rename_*``.
* Every rename stub object carries ``hidden=True`` on its click.Command.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi

# Same canonical rename table the Phase 1d Step C tests use. Kept
# inline (not imported) so a refactor of that file can't silently
# desync this invariant.
RENAMED_FLAT_NAMES: list[str] = [
    "agent-launch",
    "agent-restart",
    "agent-status",
    "agent-stop",
    "list-agents",
    "fleet",
    "launch",
    "stop",
    "send",
    "listen",
    "show-history",
    "join",
    "list-channels",
    "list-members",
    "create-invite",
    "list-invites",
    "create-workspace",
    "delete-workspace",
    "list-workspaces",
    "show-status",
    "serve",
    "deploy",
    "setup-push",
    "init",
    "doctor",
    "login",
    "heartbeat-push",
    "report",
]


# ---------------------------------------------------------------------------
# 1. Top-level `--help` is free of rename clutter.
# ---------------------------------------------------------------------------


def _help_text() -> str:
    runner = CliRunner()
    result = runner.invoke(orochi, ["--help"], obj={"host": "127.0.0.1", "port": 9559})
    assert result.exit_code == 0, result.output
    return result.output


def test_top_level_help_has_no_rename_clutter() -> None:
    """The top-level ``--help`` must not advertise any ``Renamed -- use``
    short-help line. The 28 stubs are hidden per post-Phase-1d cleanup."""
    text = _help_text()
    assert "Renamed -- use" not in text, (
        "top-level --help still prints 'Renamed -- use' clutter; "
        "rename stubs must carry hidden=True.\n--- help output ---\n"
        f"{text}"
    )


@pytest.mark.parametrize("old", RENAMED_FLAT_NAMES)
def test_top_level_help_omits_each_rename_stub(old: str) -> None:
    """Each rename stub is *invokable* but must not show up as a
    visible command name at the start of a help line."""
    text = _help_text()
    # A visible command in click's default formatter appears as
    # ``  <name>  <short-help>`` (two leading spaces). Match that shape
    # so we don't false-positive on the rename stub names appearing
    # inside noun group one-liners (e.g. 'agent' mentions 'launch'
    # legitimately).
    needle = f"\n  {old} "
    assert needle not in text, (
        f"rename stub {old!r} still listed at top-level --help; it must be hidden=True."
    )


def test_top_level_help_ends_with_convention_pointer() -> None:
    """Plan §11.2: top-level --help ends with a pointer at the
    noun-verb convention doc."""
    text = _help_text()
    assert "docs/cli.md" in text, (
        "top-level --help must reference docs/cli.md per plan §11.2.\n"
        f"--- help output ---\n{text}"
    )
    assert "noun-verb convention" in text


# ---------------------------------------------------------------------------
# 2. `--help-recursive` skips hidden commands.
# ---------------------------------------------------------------------------


def _help_recursive_text() -> str:
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["--help-recursive"],
        obj={"host": "127.0.0.1", "port": 9559},
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_help_recursive_has_no_rename_clutter() -> None:
    """``--help-recursive`` must not dump help for any rename stub.
    The custom ``_HelpRecursiveGroup.get_help_recursive`` now filters
    on ``hidden=True``."""
    text = _help_recursive_text()
    assert "Renamed. Use" not in text, (
        "--help-recursive still renders rename-stub help blocks; "
        "the recursive dumper must skip hidden commands.\n--- tail ---\n"
        f"{text[-2000:]}"
    )


@pytest.mark.parametrize("old", RENAMED_FLAT_NAMES)
def test_help_recursive_skips_each_rename_stub_header(old: str) -> None:
    """No ``Command: <old-name>`` section appears in the recursive dump."""
    text = _help_recursive_text()
    needle = f"Command: {old}\n"
    assert needle not in text, f"--help-recursive still prints a section for {old!r}"


# ---------------------------------------------------------------------------
# 3. Hidden ≠ removed: invoking a stub by name still hard-errors.
# ---------------------------------------------------------------------------


def test_hidden_stub_still_hard_errors_when_invoked() -> None:
    """Hiding a rename stub from ``--help`` must not regress the
    behaviour: typing the old name still prints the canonical rename
    error and exits non-zero. Representative spot-check; the full
    matrix is in ``test_phase1d_step_c_rename_functional``."""
    runner = CliRunner()
    result = runner.invoke(
        orochi, ["list-agents"], obj={"host": "127.0.0.1", "port": 9559}
    )
    assert result.exit_code == 2
    assert (
        "error: `scitex-orochi list-agents` was renamed to `scitex-orochi agent list`."
    ) in result.output


# ---------------------------------------------------------------------------
# 4. Every rename stub carries hidden=True on its click.Command object.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("old", RENAMED_FLAT_NAMES)
def test_rename_stub_command_is_hidden_attribute(old: str) -> None:
    """The click.Command object registered at ``old`` must report
    ``hidden is True`` so any future contributor re-rendering --help
    via a non-standard formatter still gets clean output."""
    cmd = orochi.commands.get(old)
    assert cmd is not None, f"rename stub {old!r} not registered"
    assert isinstance(cmd, click.Command)
    assert cmd.hidden is True, (
        f"rename stub {old!r} must have hidden=True; got {cmd.hidden!r}"
    )
