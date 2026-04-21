"""Tests for ``scitex_orochi._cli._deprecation``.

Phase 1d Step A — PR #337 plan §2.

Asserts:

* ``hard_rename_error(old, new)`` prints the canonical one-line error to
  stderr and exits non-zero.
* ``soft_notice(command, msg)`` prints at most once per shell session
  per command, gated by a marker file.
* ``SCITEX_OROCHI_NO_DEPRECATION=1`` suppresses the soft path entirely
  but does **not** un-fail the hard path.
"""

from __future__ import annotations

import io

import pytest

from scitex_orochi._cli import _deprecation as dep


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Redirect XDG_STATE_HOME to a tmpdir so marker files are isolated
    per-test, and force a stable session key."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("SCITEX_OROCHI_SHELL_SESSION", "test-session")
    monkeypatch.delenv("SCITEX_OROCHI_NO_DEPRECATION", raising=False)
    yield
    dep.reset_soft_notice_state()


# ---------------------------------------------------------------------------
# hard_rename_error
# ---------------------------------------------------------------------------


def test_hard_rename_error_prints_canonical_one_liner() -> None:
    buf = io.StringIO()
    exits: list[int] = []
    dep.hard_rename_error(
        "list-agents",
        "agent list",
        stream=buf,
        exit_func=exits.append,
    )
    out = buf.getvalue().strip()
    assert out == (
        "error: `scitex-orochi list-agents` was renamed to "
        "`scitex-orochi agent list`."
    )
    assert exits == [2]


def test_hard_rename_error_ignores_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with NO_DEPRECATION=1 the error still prints and exits — a
    misspelling must not succeed silently."""
    monkeypatch.setenv("SCITEX_OROCHI_NO_DEPRECATION", "1")
    buf = io.StringIO()
    exits: list[int] = []
    dep.hard_rename_error("send", "message send", stream=buf, exit_func=exits.append)
    assert "was renamed" in buf.getvalue()
    assert exits == [2]


# ---------------------------------------------------------------------------
# soft_notice: one-time-per-shell semantics
# ---------------------------------------------------------------------------


def test_soft_notice_first_call_prints() -> None:
    buf = io.StringIO()
    printed = dep.soft_notice("list-agents", "use `agent list` instead", stream=buf)
    assert printed is True
    assert buf.getvalue().strip() == "note: use `agent list` instead"


def test_soft_notice_second_call_in_same_session_is_silent() -> None:
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    assert dep.soft_notice("list-agents", "use `agent list` instead", stream=buf1) is True
    assert (
        dep.soft_notice("list-agents", "use `agent list` instead", stream=buf2) is False
    )
    assert buf2.getvalue() == ""


def test_soft_notice_distinct_commands_are_independent() -> None:
    assert dep.soft_notice("list-agents", "a", stream=io.StringIO()) is True
    assert dep.soft_notice("send", "b", stream=io.StringIO()) is True
    # Both fired once; a second hit on either should now be silent.
    assert dep.soft_notice("list-agents", "a", stream=io.StringIO()) is False
    assert dep.soft_notice("send", "b", stream=io.StringIO()) is False


def test_soft_notice_distinct_sessions_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two shells (different SCITEX_OROCHI_SHELL_SESSION) each get the note once."""
    monkeypatch.setenv("SCITEX_OROCHI_SHELL_SESSION", "shell-A")
    assert dep.soft_notice("list-agents", "a", stream=io.StringIO()) is True
    monkeypatch.setenv("SCITEX_OROCHI_SHELL_SESSION", "shell-B")
    assert dep.soft_notice("list-agents", "a", stream=io.StringIO()) is True


def test_soft_notice_respects_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCITEX_OROCHI_NO_DEPRECATION", "1")
    buf = io.StringIO()
    printed = dep.soft_notice("list-agents", "use `agent list` instead", stream=buf)
    assert printed is False
    assert buf.getvalue() == ""


def test_is_opted_out_truthy_variants() -> None:
    for val in ("1", "true", "yes", "on", "TRUE", "YES"):
        assert dep.is_opted_out({"SCITEX_OROCHI_NO_DEPRECATION": val}) is True
    for val in ("", "0", "false", "no", "off"):
        assert dep.is_opted_out({"SCITEX_OROCHI_NO_DEPRECATION": val}) is False


def test_reset_soft_notice_state_allows_reemit() -> None:
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    assert dep.soft_notice("cmd", "x", stream=buf1) is True
    dep.reset_soft_notice_state()
    assert dep.soft_notice("cmd", "x", stream=buf2) is True
