"""``scitex-orochi system {venv-check,venv-heal}`` subcommands.

Periodic integrity probe for the critical Python interpreters used by
the fleet-side scripts. Catches the exact failure mode seen on mba in
msg#16777 / msg#16779, where the shared ``~/.venv`` was missing the
``scitex_orochi`` package -- manually detected, not alerted.

Detection
---------
For each interpreter we care about (``sys.executable`` and, if it
exists, ``~/.venv/bin/python``) and each critical package in the
hard-coded list, we run ``<interp> -c 'import <pkg>'`` in a subprocess
and record the outcome.

Remediation
-----------
If a critical package is missing AND the repo path exists locally, the
failure is an editable-install-that-drifted scenario and ``venv-heal
--yes`` will run ``<interp> -m pip install -e <repo>``. Without
``--yes`` it's always a dry run. If the repo isn't on this host the
package should have come from PyPI; we alert but don't auto-heal.

Output
------
NDJSON lines (one per probe result), schema
``scitex-orochi/venv-integrity-probe/v1``.

Exit codes
----------
* ``0`` -- all critical packages importable from every audited interp.
* ``1`` -- at least one critical import failed (severity ``critical``).
* ``2`` -- probe itself failed (couldn't even launch the interpreter).

Silent-success: no orochi DM, no chat post -- just NDJSON + log. A
future PR can wire the heal events into ``healer-<host>`` for
tmux-level recovery (msg#16777 brief).
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import click

SCHEMA = "scitex-orochi/venv-integrity-probe/v1"


# ---------------------------------------------------------------------------
# Critical-package registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriticalPackage:
    """One entry in the critical-package list.

    ``import_name``  — the dotted name you'd type after ``import``.
    ``repo_path``    — candidate local-checkout paths (first existing wins).
                       ``pip install -e <repo>`` restores an editable install
                       when a package silently disappears.
    """

    import_name: str
    repo_paths: tuple[Path, ...]


def _default_repo_paths(*names: str) -> tuple[Path, ...]:
    """Standard developer-layout candidates for a given project name.

    Handles both ``~/proj/<name>`` (personal checkout) and a few
    ``~/proj/<parent>/<name>`` nestings we've seen in the fleet.
    """
    home = Path.home()
    out: list[Path] = []
    for n in names:
        out.append(home / "proj" / n)
    return tuple(out)


def _build_critical_packages() -> list[CriticalPackage]:
    """The hard-coded critical list. Ordered most-to-least load-bearing.

    Judgment call: we start with the three packages named in the brief
    (scitex, scitex-orochi, scitex-agent-container). Easy to extend.
    """
    return [
        CriticalPackage(
            import_name="scitex",
            repo_paths=_default_repo_paths("scitex"),
        ),
        CriticalPackage(
            import_name="scitex_orochi",
            repo_paths=_default_repo_paths("scitex-orochi"),
        ),
        CriticalPackage(
            import_name="scitex_agent_container",
            repo_paths=_default_repo_paths(
                "scitex-agent-container",
                "scitex_agent_container",
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Interpreter discovery
# ---------------------------------------------------------------------------


def _discover_interpreters() -> list[Path]:
    """Return interpreters to audit, in precedence order.

    * ``sys.executable`` -- the one running us right now. Always audited.
    * ``~/.venv/bin/python`` -- the shared venv common to fleet scripts
      (the one that was broken on mba per msg#16777). Audited if present
      and distinct from ``sys.executable``.
    """
    interps: list[Path] = []
    this = Path(sys.executable).resolve()
    interps.append(this)
    shared = (Path.home() / ".venv" / "bin" / "python").resolve()
    if shared.is_file() and shared != this:
        interps.append(shared)
    return interps


# ---------------------------------------------------------------------------
# Import probe
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    pkg: str
    interpreter: str
    importable: bool
    repo_path_found: str | None
    error: str = ""


def _probe_import(interp: Path, pkg: str, *, timeout: float = 10.0) -> tuple[bool, str]:
    """Return (importable, stderr-tail) for ``<interp> -c 'import <pkg>'``."""
    try:
        proc = subprocess.run(
            [str(interp), "-c", f"import {pkg}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "interpreter_not_found"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if proc.returncode == 0:
        return True, ""
    # Keep error compact -- NDJSON stays one line per probe.
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, (err[-1] if err else f"exit={proc.returncode}")[:240]


def _pick_repo_path(pkg: CriticalPackage) -> Path | None:
    for candidate in pkg.repo_paths:
        if candidate.is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
        # Allow repos that only have setup.py (older layouts).
        if candidate.is_dir() and (candidate / "setup.py").is_file():
            return candidate
    return None


def _run_probe(
    packages: Iterable[CriticalPackage],
    interpreters: Iterable[Path],
) -> list[ProbeResult]:
    out: list[ProbeResult] = []
    for interp in interpreters:
        for pkg in packages:
            ok, err = _probe_import(interp, pkg.import_name)
            repo = _pick_repo_path(pkg)
            out.append(
                ProbeResult(
                    pkg=pkg.import_name,
                    interpreter=str(interp),
                    importable=ok,
                    repo_path_found=str(repo) if repo else None,
                    error=err,
                )
            )
    return out


# ---------------------------------------------------------------------------
# NDJSON emit
# ---------------------------------------------------------------------------


def _emit_ndjson(
    results: list[ProbeResult],
    *,
    host: str,
    mode: str,
    heal_actions: dict[tuple[str, str], str] | None = None,
) -> int:
    """Print one NDJSON line per probe result. Returns count of failures."""
    heal_actions = heal_actions or {}
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fails = 0
    severity_bumped = False
    for r in results:
        key = (r.interpreter, r.pkg)
        was_healed = key in heal_actions and heal_actions[key] == "ok"
        if not r.importable:
            fails += 1
            severity_bumped = True
            # Decide the action label for this probe row.
            if r.repo_path_found:
                default_action = "heal"
            else:
                default_action = "alert"
            heal_result = heal_actions.get(key, "skipped")
            action = default_action
        elif was_healed:
            # Package became importable because we just installed it.
            # Surface that clearly so cron consumers can count heals.
            action = "heal"
            heal_result = "ok"
        else:
            action = "none"
            heal_result = "skipped"
        record = {
            "schema": SCHEMA,
            "ts": ts,
            "host": host,
            "mode": mode,
            "pkg": r.pkg,
            "interpreter": r.interpreter,
            "importable": r.importable,
            "repo_path_found": r.repo_path_found,
            "action": action,
            "heal_result": heal_result,
            "error": r.error,
            "severity": "critical" if not r.importable else "ok",
        }
        click.echo(json.dumps(record, separators=(",", ":"), sort_keys=False))
    # If nothing failed we still emit a summary record so cron logs prove
    # the probe ran (silent-success is per-chat, not per-NDJSON-line).
    if not severity_bumped:
        click.echo(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ts": ts,
                    "host": host,
                    "mode": mode,
                    "summary": "all_ok",
                    "probes": len(results),
                    "severity": "ok",
                },
                separators=(",", ":"),
            )
        )
    return fails


# ---------------------------------------------------------------------------
# Heal
# ---------------------------------------------------------------------------


def _pip_install_editable(
    interp: Path,
    repo: Path,
    *,
    timeout: float = 300.0,
) -> tuple[bool, str]:
    """Run ``<interp> -m pip install -e <repo>`` and return (ok, tail-stderr)."""
    try:
        proc = subprocess.run(
            [str(interp), "-m", "pip", "install", "-e", str(repo)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, "interpreter_not_found"
    except subprocess.TimeoutExpired:
        return False, "pip_timeout"
    if proc.returncode == 0:
        return True, ""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, (tail[-1] if tail else f"exit={proc.returncode}")[:240]


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------


@click.command("venv-check")
def venv_check_cmd() -> None:
    """Probe critical packages are importable; emit NDJSON; exit nonzero on failure.

    Read-only health check. Never installs. Pair with ``venv-heal --yes``
    on hosts where auto-remediation is acceptable.
    """
    host = platform.node().split(".")[0]
    interpreters = _discover_interpreters()
    packages = _build_critical_packages()

    # If the interpreter we're running on can't even start a subprocess
    # of itself, the probe is broken -- exit 2, not 1.
    if not interpreters:
        click.echo(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "host": host,
                    "mode": "check",
                    "error": "no_interpreters_found",
                    "severity": "critical",
                },
                separators=(",", ":"),
            )
        )
        sys.exit(2)

    results = _run_probe(packages, interpreters)
    fails = _emit_ndjson(results, host=host, mode="check")
    sys.exit(1 if fails else 0)


@click.command("venv-heal")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Actually run 'pip install -e <repo>' (default is dry-run).",
)
@click.option(
    "--dry-run",
    "dry_run_flag",
    is_flag=True,
    help="Explicit dry-run (the default).",
)
def venv_heal_cmd(yes: bool, dry_run_flag: bool) -> None:
    """Probe critical packages; for broken + local-repo-present cases run pip install -e.

    Dry-run by default. ``--yes`` enables the actual install. When a
    package is broken but the repo is NOT on this host, we cannot
    auto-heal (the package should come from PyPI); that case is still
    reported with ``action: "alert"`` but ``heal_result: "skipped"``.
    """
    del dry_run_flag
    dry_run = not yes
    host = platform.node().split(".")[0]
    interpreters = _discover_interpreters()
    packages = _build_critical_packages()
    by_name = {p.import_name: p for p in packages}

    if not interpreters:
        click.echo(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "host": host,
                    "mode": "heal",
                    "error": "no_interpreters_found",
                    "severity": "critical",
                },
                separators=(",", ":"),
            )
        )
        sys.exit(2)

    results = _run_probe(packages, interpreters)

    heal_actions: dict[tuple[str, str], str] = {}
    for r in results:
        if r.importable:
            continue
        if not r.repo_path_found:
            # Alert-only; nothing to install from.
            heal_actions[(r.interpreter, r.pkg)] = "skipped"
            continue
        if dry_run:
            heal_actions[(r.interpreter, r.pkg)] = "skipped"
            continue
        pkg = by_name.get(r.pkg)
        if pkg is None:
            heal_actions[(r.interpreter, r.pkg)] = "skipped"
            continue
        ok, err = _pip_install_editable(Path(r.interpreter), Path(r.repo_path_found))
        # Optimistically flip the probe row to importable on success so
        # downstream cron consumers see the fresh state without needing
        # a second probe run. Re-verify with a fast import check.
        if ok:
            verify_ok, _verify_err = _probe_import(Path(r.interpreter), r.pkg)
            heal_actions[(r.interpreter, r.pkg)] = "ok" if verify_ok else "failed"
            if verify_ok:
                r.importable = True
                r.error = ""
        else:
            heal_actions[(r.interpreter, r.pkg)] = "failed"
            r.error = err or r.error

    mode = "heal-dry-run" if dry_run else "heal"
    fails = _emit_ndjson(results, host=host, mode=mode, heal_actions=heal_actions)
    sys.exit(1 if fails else 0)


__all__ = [
    "CriticalPackage",
    "ProbeResult",
    "venv_check_cmd",
    "venv_heal_cmd",
    "_build_critical_packages",
    "_discover_interpreters",
    "_pip_install_editable",
    "_probe_import",
    "_run_probe",
]

# Prevent pytest from collecting the helper dataclass as a test fixture.
ProbeResult.__test__ = False  # type: ignore[attr-defined]
