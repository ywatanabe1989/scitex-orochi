"""Tests for ``scitex-orochi disk {reaper-dry-run,pressure-probe}``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import disk_cmd as dc


def test_disk_group_registered() -> None:
    assert "disk" in orochi.commands
    disk = orochi.commands["disk"]
    assert set(disk.commands.keys()) == {"reaper-dry-run", "pressure-probe"}  # type: ignore[attr-defined]


def test_reaper_list_enumerates_targets() -> None:
    runner = CliRunner()
    result = runner.invoke(orochi, ["disk", "reaper-dry-run", "--list"], obj={})
    assert result.exit_code == 0
    # Core targets must be present in the listing.
    for n in (
        "chrome-code-sign-clone",
        "xcode-derived-data",
        "gradle-caches",
        "npm-cache",
        "trash",
    ):
        assert n in result.output


def test_reaper_dry_run_never_calls_rmtree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Default invocation must be dry-run: no shutil.rmtree / unlink ever."""
    fake_dir = tmp_path / "fake-target"
    fake_dir.mkdir()
    (fake_dir / "stuff").write_text("x")

    monkeypatch.setattr(
        dc,
        "_build_targets",
        lambda: [
            dc.ReapTarget(
                name="fake-target",
                category="safe-default",
                description="fake target for tests",
                finder=lambda: [fake_dir],
            )
        ],
    )

    called = {"count": 0}

    def fake_rmtree(*a, **kw):
        called["count"] += 1

    monkeypatch.setattr(dc.shutil, "rmtree", fake_rmtree)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["disk", "reaper-dry-run"],
        obj={},
    )
    assert result.exit_code == 0
    assert called["count"] == 0
    assert "would rm -rf" in result.output
    # Dry-run footer.
    assert "dry-run complete" in result.output
    assert fake_dir.exists()  # still there


def test_reaper_yes_reaps_safe_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_dir = tmp_path / "fake-safe"
    fake_dir.mkdir()
    monkeypatch.setattr(
        dc,
        "_build_targets",
        lambda: [
            dc.ReapTarget(
                name="fake-safe",
                category="safe-default",
                description="fake safe target",
                finder=lambda: [fake_dir],
            )
        ],
    )
    called = {"paths": []}

    def fake_rmtree(p, *a, **kw):
        called["paths"].append(str(p))

    monkeypatch.setattr(dc.shutil, "rmtree", fake_rmtree)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        ["disk", "reaper-dry-run", "--yes"],
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert str(fake_dir) in called["paths"]


def test_reaper_opt_in_requires_include(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """opt-in targets must NOT be processed without --include."""
    fake = tmp_path / "fake-opt-in"
    fake.mkdir()
    monkeypatch.setattr(
        dc,
        "_build_targets",
        lambda: [
            dc.ReapTarget(
                name="fake-opt-in",
                category="opt-in",
                description="fake opt-in",
                finder=lambda: [fake],
            )
        ],
    )
    called = {"count": 0}
    monkeypatch.setattr(
        dc.shutil,
        "rmtree",
        lambda *a, **kw: called.__setitem__("count", called["count"] + 1),
    )
    runner = CliRunner()
    result = runner.invoke(orochi, ["disk", "reaper-dry-run", "--yes"], obj={})
    assert result.exit_code == 0, result.output
    assert called["count"] == 0  # not processed without --include

    # Now with --include.
    result2 = runner.invoke(
        orochi,
        [
            "disk", "reaper-dry-run",
            "--yes", "--include", "fake-opt-in",
        ],
        obj={},
    )
    assert result2.exit_code == 0
    assert called["count"] >= 1


def test_pressure_probe_emits_ndjson(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """df output is parsed into an NDJSON record."""
    class _FakeProc:
        returncode = 0
        stdout = (
            "Filesystem    1024-blocks    Used  Available Capacity  Mounted on\n"
            "/dev/disk3    500000000  200000000 300000000 40%        /\n"
        )
        stderr = ""

    def fake_run(cmd, *a, **kw):
        if cmd[:2] == ["df", "-k"]:
            return _FakeProc()
        # Anything else (du -sh for top consumers) → innocuous return.
        return type(
            "R",
            (),
            {"returncode": 0, "stdout": "100M\t/tmp\n", "stderr": ""},
        )()

    monkeypatch.setattr(dc.subprocess, "run", fake_run)
    runner = CliRunner()
    result = runner.invoke(
        orochi,
        [
            "disk", "pressure-probe",
            "--out-dir", str(tmp_path),
            "--advisory-gib", "9999",  # force 'advisory'
        ],
        obj={},
    )
    # Exit code reflects severity (we forced advisory with huge threshold).
    assert result.exit_code == 1
    lines = [ln for ln in result.output.splitlines() if ln.startswith("{")]
    assert lines, result.output
    obj = json.loads(lines[-1])
    assert obj["schema"] == "scitex-orochi/disk-pressure-probe/v1"
    assert obj["severity"] == "advisory"
    assert obj["avail_gib"] > 0
    # NDJSON was appended to the per-host out file.
    host_files = list(tmp_path.glob("disk-pressure-*.ndjson"))
    assert host_files, "expected disk-pressure-<host>.ndjson on disk"
    assert host_files[0].read_text().strip().startswith("{")
