"""Tests for ``scitex-orochi chrome-watchdog check``."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import chrome_watchdog_cmd as cwc


def test_chrome_watchdog_registered() -> None:
    assert "chrome-watchdog" in orochi.commands
    assert "check" in orochi.commands["chrome-watchdog"].commands  # type: ignore[attr-defined]


def test_non_macos_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cwc.platform, "system", lambda: "Linux")
    runner = CliRunner()
    result = runner.invoke(orochi, ["chrome-watchdog", "check"], obj={})
    assert result.exit_code == 0
    assert "not macOS" in result.output


def test_no_candidates_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cwc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cwc.glob, "glob", lambda p: [])
    runner = CliRunner()
    result = runner.invoke(orochi, ["chrome-watchdog", "check"], obj={})
    assert result.exit_code == 0
    assert "no Chrome code_sign_clone paths" in result.output


def test_dry_run_never_deletes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "com.google.Chrome.code_sign_clone"
    fake.mkdir()
    monkeypatch.setattr(cwc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cwc.glob, "glob", lambda p: [str(fake)])
    # Pretend it's 10 GiB.
    monkeypatch.setattr(cwc, "_du_kib", lambda p: 10 * 1024 * 1024)
    called = {"n": 0}

    def fake_rmtree(*a, **kw):
        called["n"] += 1

    monkeypatch.setattr(cwc.shutil, "rmtree", fake_rmtree)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["chrome-watchdog", "check", "--dry-run", "--reap-gib", "5"],
        obj={},
    )
    assert result.exit_code == 0
    assert called["n"] == 0
    assert "WOULD REAP" in result.output


def test_reap_threshold_triggers_rmtree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "com.google.Chrome.code_sign_clone"
    fake.mkdir()
    monkeypatch.setattr(cwc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cwc.glob, "glob", lambda p: [str(fake)])
    monkeypatch.setattr(cwc, "_du_kib", lambda p: 10 * 1024 * 1024)
    called = {"paths": []}

    def fake_rmtree(p, *a, **kw):
        called["paths"].append(str(p))

    monkeypatch.setattr(cwc.shutil, "rmtree", fake_rmtree)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["chrome-watchdog", "check", "--reap-gib", "5"],
        obj={},
    )
    assert result.exit_code == 0
    assert called["paths"] == [str(fake)]
    assert "REAPING" in result.output


def test_advisory_range_does_not_reap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Size in [advise, reap) → advisory only, no delete."""
    fake = tmp_path / "com.google.Chrome.code_sign_clone"
    fake.mkdir()
    monkeypatch.setattr(cwc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cwc.glob, "glob", lambda p: [str(fake)])
    monkeypatch.setattr(cwc, "_du_kib", lambda p: 3 * 1024 * 1024)  # 3 GiB
    called = {"n": 0}
    monkeypatch.setattr(
        cwc.shutil,
        "rmtree",
        lambda *a, **kw: called.__setitem__("n", called["n"] + 1),
    )
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["chrome-watchdog", "check", "--advise-gib", "2", "--reap-gib", "5"],
        obj={},
    )
    assert result.exit_code == 0
    assert "ADVISORY" in result.output
    assert called["n"] == 0
