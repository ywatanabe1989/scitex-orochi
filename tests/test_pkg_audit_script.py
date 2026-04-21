"""Integration tests for scripts/client/pkg-audit.sh.

We drive the real bash script against stub ``pip`` and ``python`` binaries
on a tmpdir PATH so we can simulate every combination of
(pip-show-ok, python-import-ok) without touching the real venv.

The script's three exit codes under normal operation:
    0 — all packages ok (or fixed cleanly with --auto-fix)
    1 — drift/missing observed without fix
    2 — --auto-fix attempted but at least one install failed
    3 — pip not found (covered by its own test)

Plus NDJSON shape: one ``{"package": ..., "status": ..., ...}`` line per
package, emitted strictly to stdout.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "client" / "pkg-audit.sh"


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_pip_stub(
    bindir: Path,
    *,
    known: set[str],
    install_fail: set[str] | None = None,
    log_file: Path | None = None,
) -> None:
    """Write a fake 'pip' binary.

    * `pip show <pkg>` exits 0 iff pkg in `known`.
    * `pip install -e <path>` exits 0 unless the basename of <path> is in
      `install_fail`; also appends the install target to `log_file`.
    """
    install_fail = install_fail or set()
    log_file = log_file or (bindir / "pip.log")
    known_list = " ".join(sorted(known))
    fail_list = " ".join(sorted(install_fail))
    script = f"""#!/usr/bin/env bash
LOG="{log_file}"
KNOWN="{known_list}"
FAIL="{fail_list}"
case "$1" in
    show)
        pkg="$2"
        for k in $KNOWN; do
            if [ "$k" = "$pkg" ]; then exit 0; fi
        done
        exit 1
        ;;
    install)
        # pip install -e <path>
        # argv: install -e <path>
        shift
        target=""
        while [ $# -gt 0 ]; do
            case "$1" in
                -e) shift; target="$1"; shift ;;
                *) shift ;;
            esac
        done
        echo "install $target" >> "$LOG"
        base="$(basename "$target")"
        for f in $FAIL; do
            if [ "$f" = "$base" ]; then exit 1; fi
        done
        exit 0
        ;;
    *)
        exit 1
        ;;
esac
"""
    p = bindir / "pip"
    p.write_text(script)
    _make_executable(p)


def _write_python_stub(
    bindir: Path,
    *,
    importable: set[str],
) -> None:
    """Write a fake 'python' binary.

    Only supports the `python -c "import <name>"` call shape used by the
    audit script. Exits 0 iff the imported module is in `importable`.
    """
    importable_list = " ".join(sorted(importable))
    script = f"""#!/usr/bin/env bash
# argv: -c "import <name>"
if [ "$1" != "-c" ]; then exit 2; fi
code="$2"
# Strip "import " prefix.
mod="${{code#import }}"
OK="{importable_list}"
for m in $OK; do
    if [ "$m" = "$mod" ]; then exit 0; fi
done
exit 1
"""
    p = bindir / "python"
    p.write_text(script)
    _make_executable(p)


def _run(
    tmp_path: Path,
    *,
    known: set[str],
    importable: set[str],
    args: list[str],
    install_fail: set[str] | None = None,
    packages: str | None = None,
    create_repos: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _write_pip_stub(bindir, known=known, install_fail=install_fail)
    _write_python_stub(bindir, importable=importable)

    # Optional fake HOME with the repo dirs the script's auto-fix map
    # will look up.
    home = tmp_path / "home"
    proj = home / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    for repo in create_repos or []:
        (proj / repo).mkdir(parents=True, exist_ok=True)

    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "HOME": str(home),
    }
    if packages is not None:
        env["PACKAGES"] = packages

    proc = subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc, bindir


def _parse_ndjson(stdout: str) -> list[dict]:
    return [json.loads(ln) for ln in stdout.splitlines() if ln.startswith("{")]


# ---------------------------------------------------------------------------
# Exit-code tests
# ---------------------------------------------------------------------------


def test_all_ok_exit_zero(tmp_path):
    """Every package present in pip AND importable → exit 0."""
    proc, _ = _run(
        tmp_path,
        known={"scitex", "scitex_orochi_pkg"},
        importable={"scitex", "scitex_orochi_pkg"},
        packages="scitex",
        args=["--json"],
    )
    assert proc.returncode == 0, proc.stderr
    rows = _parse_ndjson(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["package"] == "scitex"
    assert rows[0]["status"] == "ok"
    assert rows[0]["pip_ok"] is True
    assert rows[0]["import_ok"] is True


def test_drift_detected_exit_one(tmp_path):
    """pip show ok but python import fails → drift, exit 1."""
    proc, _ = _run(
        tmp_path,
        known={"scitex-orochi"},   # pip knows it
        importable=set(),          # but it won't import
        packages="scitex-orochi",
        args=["--json"],
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    rows = _parse_ndjson(proc.stdout)
    assert rows[0]["status"] == "drift"
    assert rows[0]["pip_ok"] is True
    assert rows[0]["import_ok"] is False


def test_missing_detected_exit_one(tmp_path):
    """pip show fails → missing, exit 1."""
    proc, _ = _run(
        tmp_path,
        known=set(),
        importable=set(),
        packages="scitex-cloud",
        args=["--json"],
    )
    assert proc.returncode == 1
    rows = _parse_ndjson(proc.stdout)
    assert rows[0]["status"] == "missing"


def test_pip_not_found_exit_three(tmp_path):
    """No pip in PATH → exit 3."""
    # Empty bindir with only python; no pip stub at all.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _write_python_stub(bindir, importable=set())
    # PATH includes /usr/bin:/bin only so the bash child can still exec
    # basic utilities, but pip is deliberately absent.
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    # Force an absolute pip target so the shim bindir can't accidentally
    # satisfy `command -v pip`.
    env["PIP_BIN"] = "/nonexistent/definitely-not-pip"
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--quiet", "--pkg", "scitex"],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert proc.returncode == 3


# ---------------------------------------------------------------------------
# --auto-fix behaviour
# ---------------------------------------------------------------------------


def test_auto_fix_repairs_drift_when_repo_present(tmp_path):
    """Drift + repo dir present + pip install succeeds → fixed, exit 0."""
    proc, bindir = _run(
        tmp_path,
        known={"scitex-orochi"},
        importable=set(),
        packages="scitex-orochi",
        args=["--auto-fix", "--json"],
        create_repos=["scitex-orochi"],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = _parse_ndjson(proc.stdout)
    assert rows[0]["status"] == "fixed"
    assert rows[0]["fixed"] is True

    # Confirm pip install -e was invoked at the expected path.
    log = (bindir / "pip.log").read_text()
    assert "install" in log
    assert "scitex-orochi" in log


def test_auto_fix_failure_exit_two(tmp_path):
    """--auto-fix attempts install but pip returns nonzero → exit 2."""
    proc, _ = _run(
        tmp_path,
        known=set(),                      # missing
        importable=set(),
        packages="scitex-orochi",
        args=["--auto-fix", "--json"],
        create_repos=["scitex-orochi"],
        install_fail={"scitex-orochi"},  # pip install will fail
    )
    assert proc.returncode == 2
    rows = _parse_ndjson(proc.stdout)
    assert rows[0]["status"] == "fix_failed"


def test_auto_fix_skips_when_repo_absent(tmp_path):
    """--auto-fix but repo dir doesn't exist → stay drift, exit 1."""
    proc, _ = _run(
        tmp_path,
        known={"scitex"},
        importable=set(),
        packages="scitex",
        args=["--auto-fix", "--json"],
        create_repos=[],   # no scitex-python repo on disk
    )
    assert proc.returncode == 1
    rows = _parse_ndjson(proc.stdout)
    assert rows[0]["status"] == "drift"
    assert rows[0]["fixed"] is False


# ---------------------------------------------------------------------------
# Output mode tests
# ---------------------------------------------------------------------------


def test_quiet_suppresses_stdout(tmp_path):
    """--quiet emits nothing on stdout regardless of status."""
    proc, _ = _run(
        tmp_path,
        known=set(),
        importable=set(),
        packages="scitex",
        args=["--quiet"],
    )
    assert proc.stdout == ""
    assert proc.returncode == 1


def test_json_emits_one_line_per_package(tmp_path):
    """Default package list produces one NDJSON object per package."""
    proc, _ = _run(
        tmp_path,
        known={"scitex", "scitex-orochi"},
        importable={"scitex", "scitex_orochi"},
        packages="scitex scitex-orochi scitex-clew",
        args=["--json"],
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    assert len(lines) == 3
    statuses = [json.loads(ln)["status"] for ln in lines]
    assert statuses == ["ok", "ok", "missing"]


def test_import_name_uses_underscore(tmp_path):
    """scitex-orochi is imported as scitex_orochi, not scitex-orochi."""
    # If the script used the literal package name, `python -c "import
    # scitex-orochi"` would fail even when the module is importable.
    proc, _ = _run(
        tmp_path,
        known={"scitex-orochi"},
        importable={"scitex_orochi"},   # underscore form
        packages="scitex-orochi",
        args=["--json"],
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = _parse_ndjson(proc.stdout)
    assert rows[0]["status"] == "ok"


def test_single_pkg_flag_restricts_scope(tmp_path):
    """--pkg <name> audits exactly that one package, ignoring PACKAGES env."""
    proc, _ = _run(
        tmp_path,
        known={"scitex"},
        importable={"scitex"},
        packages="scitex scitex-orochi scitex-clew",  # env says 3 pkgs
        args=["--pkg", "scitex", "--json"],
    )
    rows = _parse_ndjson(proc.stdout)
    assert len(rows) == 1
    assert rows[0]["package"] == "scitex"
