"""Unit tests for ``scitex-orochi system {venv-check,venv-heal}``.

The probe shells out to Python subprocesses to validate imports. Tests
monkeypatch the subprocess helpers so we don't actually launch real
interpreters -- a pure unit-test cost profile.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pytest
from click.testing import CliRunner

from scitex_orochi._cli._main import orochi
from scitex_orochi._cli.commands import venv_check_cmd as vcc

# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_system_group_has_venv_verbs() -> None:
    """Both verbs must be registered under the ``system`` noun group."""
    assert "system" in orochi.commands
    system = orochi.commands["system"]
    cmds = set(system.commands.keys())  # type: ignore[attr-defined]
    assert "venv-check" in cmds
    assert "venv-heal" in cmds
    # The existing ``doctor`` verb must still be present (regression).
    assert "doctor" in cmds


# ---------------------------------------------------------------------------
# Helpers for tests
# ---------------------------------------------------------------------------


def _make_fake_packages(
    tmp_path: Path,
    *,
    create_repos: Iterable[str] = (),
) -> list[vcc.CriticalPackage]:
    """Build a small critical-package list pointing at ``tmp_path`` dirs.

    For each name in ``create_repos`` we drop a ``pyproject.toml`` so
    ``_pick_repo_path`` accepts the dir.
    """
    pkgs: list[vcc.CriticalPackage] = []
    all_names = [
        ("alpha_pkg", "alpha"),
        ("beta_pkg", "beta"),
        ("gamma_pkg", "gamma"),
    ]
    for import_name, dirname in all_names:
        candidate = tmp_path / dirname
        if dirname in create_repos:
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / "pyproject.toml").write_text("[project]\nname='x'\n")
        pkgs.append(
            vcc.CriticalPackage(
                import_name=import_name,
                repo_paths=(candidate,),
            )
        )
    return pkgs


def _parse_ndjson(stdout: str) -> list[dict]:
    return [
        json.loads(ln)
        for ln in stdout.splitlines()
        if ln.strip().startswith("{")
    ]


# ---------------------------------------------------------------------------
# _probe_import behaviour
# ---------------------------------------------------------------------------


def test_probe_import_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(
        vcc.subprocess, "run", lambda *a, **kw: _Proc()
    )
    ok, err = vcc._probe_import(Path("/fake/python"), "whatever")
    assert ok is True
    assert err == ""


def test_probe_import_failure_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Proc:
        returncode = 1
        stderr = "Traceback (most recent call last):\n  ...\nModuleNotFoundError: No module named 'X'"
        stdout = ""

    monkeypatch.setattr(
        vcc.subprocess, "run", lambda *a, **kw: _Proc()
    )
    ok, err = vcc._probe_import(Path("/fake/python"), "X")
    assert ok is False
    assert "ModuleNotFoundError" in err


def test_probe_import_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_timeout(*a, **kw):
        raise vcc.subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(vcc.subprocess, "run", _raise_timeout)
    ok, err = vcc._probe_import(Path("/fake/python"), "X")
    assert ok is False
    assert err == "timeout"


def test_probe_import_interpreter_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_fnf(*a, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(vcc.subprocess, "run", _raise_fnf)
    ok, err = vcc._probe_import(Path("/fake/python"), "X")
    assert ok is False
    assert err == "interpreter_not_found"


# ---------------------------------------------------------------------------
# venv-check: NDJSON + exit code
# ---------------------------------------------------------------------------


def test_venv_check_all_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All imports succeed → exit 0, NDJSON summary record 'all_ok'."""
    monkeypatch.setattr(
        vcc, "_build_critical_packages",
        lambda: _make_fake_packages(tmp_path, create_repos=()),
    )
    monkeypatch.setattr(
        vcc, "_discover_interpreters",
        lambda: [Path("/fake/python")],
    )
    monkeypatch.setattr(
        vcc, "_probe_import", lambda *a, **kw: (True, "")
    )

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-check"], obj={})
    assert result.exit_code == 0, result.output
    objs = _parse_ndjson(result.output)
    assert objs, result.output
    # We emit a summary record when nothing failed.
    assert objs[-1].get("summary") == "all_ok"
    assert objs[-1]["severity"] == "ok"


def test_venv_check_partial_failure_exit1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pkg fails → exit 1, NDJSON has severity=critical."""
    pkgs = _make_fake_packages(tmp_path, create_repos=("beta",))
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )

    def _probe(interp, pkg, *, timeout=10.0):
        # alpha_pkg fails, rest succeed.
        if pkg == "alpha_pkg":
            return False, "ModuleNotFoundError"
        return True, ""

    monkeypatch.setattr(vcc, "_probe_import", _probe)

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-check"], obj={})
    assert result.exit_code == 1, result.output
    objs = _parse_ndjson(result.output)
    # One of the NDJSON rows is the failing alpha_pkg, action=alert.
    alpha = [o for o in objs if o.get("pkg") == "alpha_pkg"]
    assert alpha and alpha[0]["importable"] is False
    assert alpha[0]["severity"] == "critical"
    # alpha has no repo present → action=alert, heal_result=skipped.
    assert alpha[0]["action"] == "alert"
    assert alpha[0]["heal_result"] == "skipped"


def test_venv_check_failure_with_repo_tags_heal_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure + repo-present → action=heal (check mode still exits 1)."""
    pkgs = _make_fake_packages(tmp_path, create_repos=("alpha",))
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )
    monkeypatch.setattr(
        vcc, "_probe_import",
        lambda interp, pkg, **kw: (False, "boom") if pkg == "alpha_pkg" else (True, ""),
    )

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-check"], obj={})
    assert result.exit_code == 1
    objs = _parse_ndjson(result.output)
    alpha = [o for o in objs if o.get("pkg") == "alpha_pkg"][0]
    assert alpha["action"] == "heal"
    # venv-check never installs; heal_result stays 'skipped'.
    assert alpha["heal_result"] == "skipped"
    # And the repo_path_found got set.
    assert alpha["repo_path_found"] and alpha["repo_path_found"].endswith("alpha")


def test_venv_check_multiple_interpreters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two interpreters × N pkgs → 2N NDJSON data rows."""
    pkgs = _make_fake_packages(tmp_path, create_repos=())
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters",
        lambda: [Path("/fake/python-a"), Path("/fake/python-b")],
    )
    monkeypatch.setattr(vcc, "_probe_import", lambda *a, **kw: (True, ""))

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-check"], obj={})
    assert result.exit_code == 0
    objs = _parse_ndjson(result.output)
    per_pkg = [o for o in objs if "pkg" in o]
    assert len(per_pkg) == len(pkgs) * 2


# ---------------------------------------------------------------------------
# venv-heal: dry-run vs --yes
# ---------------------------------------------------------------------------


def test_venv_heal_default_is_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--yes`` no pip install fires, even for broken+local-repo pkgs."""
    pkgs = _make_fake_packages(tmp_path, create_repos=("alpha",))
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )
    monkeypatch.setattr(
        vcc, "_probe_import",
        lambda interp, pkg, **kw: (False, "boom") if pkg == "alpha_pkg" else (True, ""),
    )
    pip_called: dict[str, int] = {"n": 0}

    def _pip(interp, repo, **kw):
        pip_called["n"] += 1
        return True, ""

    monkeypatch.setattr(vcc, "_pip_install_editable", _pip)

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-heal"], obj={})
    assert result.exit_code == 1  # still broken
    assert pip_called["n"] == 0
    objs = _parse_ndjson(result.output)
    alpha = [o for o in objs if o.get("pkg") == "alpha_pkg"][0]
    assert alpha["action"] == "heal"
    # Dry-run mode: no install, heal_result is 'skipped'.
    assert alpha["heal_result"] == "skipped"
    assert alpha["mode"] == "heal-dry-run"


def test_venv_heal_yes_runs_pip_install_editable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkgs = _make_fake_packages(tmp_path, create_repos=("alpha",))
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )

    call_log: list[tuple[str, str]] = []
    state = {"healed": set()}

    def _probe(interp, pkg, **kw):
        # alpha fails until it's "healed".
        if pkg == "alpha_pkg" and pkg not in state["healed"]:
            return False, "ModuleNotFoundError"
        return True, ""

    def _pip(interp, repo, **kw):
        call_log.append((str(interp), str(repo)))
        # Simulate successful install → probe now passes.
        state["healed"].add("alpha_pkg")
        return True, ""

    monkeypatch.setattr(vcc, "_probe_import", _probe)
    monkeypatch.setattr(vcc, "_pip_install_editable", _pip)

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-heal", "--yes"], obj={})
    assert result.exit_code == 0, result.output
    # pip install ran exactly once (for the one failing pkg).
    assert len(call_log) == 1
    assert call_log[0][1].endswith("alpha")
    objs = _parse_ndjson(result.output)
    alpha = [o for o in objs if o.get("pkg") == "alpha_pkg"][0]
    assert alpha["importable"] is True  # re-verified after heal
    assert alpha["heal_result"] == "ok"
    assert alpha["mode"] == "heal"


def test_venv_heal_yes_pip_failure_records_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkgs = _make_fake_packages(tmp_path, create_repos=("alpha",))
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )
    monkeypatch.setattr(
        vcc, "_probe_import",
        lambda interp, pkg, **kw: (False, "boom") if pkg == "alpha_pkg" else (True, ""),
    )
    monkeypatch.setattr(
        vcc, "_pip_install_editable",
        lambda interp, repo, **kw: (False, "ResolutionImpossible"),
    )

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-heal", "--yes"], obj={})
    assert result.exit_code == 1  # still failing
    objs = _parse_ndjson(result.output)
    alpha = [o for o in objs if o.get("pkg") == "alpha_pkg"][0]
    assert alpha["heal_result"] == "failed"


def test_venv_heal_yes_alert_only_when_no_local_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broken pkg but no local checkout → never calls pip; action=alert."""
    pkgs = _make_fake_packages(tmp_path, create_repos=())  # none on disk
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )
    monkeypatch.setattr(
        vcc, "_probe_import",
        lambda interp, pkg, **kw: (False, "boom") if pkg == "alpha_pkg" else (True, ""),
    )
    pip_called: dict[str, int] = {"n": 0}
    monkeypatch.setattr(
        vcc, "_pip_install_editable",
        lambda *a, **kw: (pip_called.__setitem__("n", pip_called["n"] + 1), (True, ""))[-1],
    )

    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-heal", "--yes"], obj={})
    assert result.exit_code == 1
    assert pip_called["n"] == 0  # no local repo → no pip
    objs = _parse_ndjson(result.output)
    alpha = [o for o in objs if o.get("pkg") == "alpha_pkg"][0]
    assert alpha["action"] == "alert"
    assert alpha["heal_result"] == "skipped"


# ---------------------------------------------------------------------------
# Interpreter discovery
# ---------------------------------------------------------------------------


def test_discover_interpreters_dedupes_self_and_shared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``~/.venv/bin/python`` resolves to the same file as sys.executable,
    we should not audit it twice."""
    fake_self = tmp_path / "python-real"
    fake_self.write_text("#!/bin/sh\nexit 0\n")

    monkeypatch.setattr(vcc.sys, "executable", str(fake_self))
    # Point Path.home() at a dir with no ``.venv``.
    monkeypatch.setattr(vcc.Path, "home", classmethod(lambda cls: tmp_path))

    interps = vcc._discover_interpreters()
    assert len(interps) == 1
    assert interps[0] == fake_self.resolve()


def test_discover_interpreters_adds_shared_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_self = tmp_path / "python-real"
    fake_self.write_text("#!/bin/sh\nexit 0\n")
    shared_dir = tmp_path / ".venv" / "bin"
    shared_dir.mkdir(parents=True)
    shared = shared_dir / "python"
    shared.write_text("#!/bin/sh\nexit 0\n")

    monkeypatch.setattr(vcc.sys, "executable", str(fake_self))
    monkeypatch.setattr(vcc.Path, "home", classmethod(lambda cls: tmp_path))

    interps = vcc._discover_interpreters()
    assert len(interps) == 2
    paths = [str(p) for p in interps]
    assert str(shared.resolve()) in paths


# ---------------------------------------------------------------------------
# Repo-path discovery
# ---------------------------------------------------------------------------


def test_pick_repo_path_accepts_pyproject(tmp_path: Path) -> None:
    repo = tmp_path / "mypkg"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    pkg = vcc.CriticalPackage(import_name="mypkg", repo_paths=(repo,))
    assert vcc._pick_repo_path(pkg) == repo


def test_pick_repo_path_accepts_setup_py(tmp_path: Path) -> None:
    repo = tmp_path / "mypkg"
    repo.mkdir()
    (repo / "setup.py").write_text("from setuptools import setup; setup()\n")
    pkg = vcc.CriticalPackage(import_name="mypkg", repo_paths=(repo,))
    assert vcc._pick_repo_path(pkg) == repo


def test_pick_repo_path_returns_none_when_missing(tmp_path: Path) -> None:
    pkg = vcc.CriticalPackage(
        import_name="mypkg",
        repo_paths=(tmp_path / "nope",),
    )
    assert vcc._pick_repo_path(pkg) is None


# ---------------------------------------------------------------------------
# Severity escalation
# ---------------------------------------------------------------------------


def test_severity_critical_when_any_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkgs = _make_fake_packages(tmp_path, create_repos=())
    monkeypatch.setattr(vcc, "_build_critical_packages", lambda: pkgs)
    monkeypatch.setattr(
        vcc, "_discover_interpreters", lambda: [Path("/fake/python")]
    )
    monkeypatch.setattr(
        vcc, "_probe_import",
        lambda interp, pkg, **kw: (False, "boom") if pkg == "gamma_pkg" else (True, ""),
    )
    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-check"], obj={})
    assert result.exit_code == 1
    objs = _parse_ndjson(result.output)
    # No summary line in failure mode; at least one per-pkg row must be
    # severity=critical.
    assert any(
        o.get("severity") == "critical" for o in objs if "pkg" in o
    )
    # The green rows still report severity=ok.
    ok_rows = [o for o in objs if o.get("pkg") in ("alpha_pkg", "beta_pkg")]
    assert all(o["severity"] == "ok" for o in ok_rows)


# ---------------------------------------------------------------------------
# Empty-interpreter edge case
# ---------------------------------------------------------------------------


def test_venv_check_no_interpreters_exits_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vcc, "_discover_interpreters", lambda: [])
    runner = CliRunner()
    result = runner.invoke(orochi, ["system", "venv-check"], obj={})
    assert result.exit_code == 2
    objs = _parse_ndjson(result.output)
    assert objs[0]["error"] == "no_interpreters_found"
    assert objs[0]["severity"] == "critical"
