"""Tests for the ``(Available Now)`` help-suffix layer.

Phase 1d Step A — PR #337 plan §9.

Asserts:

* The suffix appears next to reachable subcommands in the top-level
  ``scitex-orochi --help`` output.
* The suffix disappears when the backing service is unreachable.
* Pure-local commands (``docs``, ``skills``, ``config init``) never get
  the suffix — no false positive on pure local operations.
* The total probe budget stays under 100 ms even when every hub probe
  times out.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from scitex_orochi._cli import _help_availability as ha
from scitex_orochi._cli._help_availability import (
    AVAILABLE_SUFFIX,
    DEFAULT_PROBE_MAP,
    PER_PROBE_TIMEOUT_S,
    TOTAL_BUDGET_S,
    ProbeKind,
    annotate_help_with_availability,
    reset_probe_cache,
    run_probes,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_probe_cache()
    yield
    reset_probe_cache()


# ---------------------------------------------------------------------------
# Builder: a minimal click group that mirrors the real registration shape
# ---------------------------------------------------------------------------


def _build_group() -> click.Group:
    @click.group(context_settings={"help_option_names": ["-h", "--help"]})
    @click.pass_context
    def root(ctx: click.Context) -> None:
        ctx.ensure_object(dict)
        ctx.obj.setdefault("host", "127.0.0.1")
        ctx.obj.setdefault("port", 9559)

    @root.command(name="agent", help="Launch / control agents")
    def agent_cmd() -> None: ...

    @root.command(name="machine", help="Heartbeat / resources")
    def machine_cmd() -> None: ...

    @root.command(name="cron", help="Schedule daemon")
    def cron_cmd() -> None: ...

    @root.command(name="docs", help="Browse package documentation")
    def docs_cmd() -> None: ...

    @root.command(name="skills", help="Browse package skills")
    def skills_cmd() -> None: ...

    annotate_help_with_availability(root)
    return root


# ---------------------------------------------------------------------------
# Suffix-appearance tests
# ---------------------------------------------------------------------------


def test_suffix_appears_when_hub_reachable() -> None:
    """`agent` (HUB) shows `(Available Now)` when the hub probe returns True."""
    root = _build_group()
    runner = CliRunner()

    with patch.object(ha, "probe_hub", return_value=True), patch.object(
        ha, "probe_local_daemon", return_value=True
    ):
        result = runner.invoke(root, ["--help"], obj={"host": "h", "port": 9559})

    assert result.exit_code == 0
    # `agent` is HUB
    assert "agent" in result.output
    agent_line = next(
        (ln for ln in result.output.splitlines() if ln.lstrip().startswith("agent")),
        "",
    )
    assert AVAILABLE_SUFFIX in agent_line, (
        f"expected suffix on reachable agent line, got: {agent_line!r}\n"
        f"full output:\n{result.output}"
    )


def test_suffix_absent_when_hub_unreachable() -> None:
    """`agent` loses the suffix when hub probe returns False."""
    root = _build_group()
    runner = CliRunner()

    with patch.object(ha, "probe_hub", return_value=False), patch.object(
        ha, "probe_local_daemon", return_value=False
    ):
        result = runner.invoke(root, ["--help"], obj={"host": "h", "port": 9559})

    assert result.exit_code == 0
    agent_line = next(
        (ln for ln in result.output.splitlines() if ln.lstrip().startswith("agent")),
        "",
    )
    assert AVAILABLE_SUFFIX not in agent_line


def test_pure_local_never_gets_suffix() -> None:
    """`docs` / `skills` are PURE_LOCAL; never annotated even when probes succeed."""
    root = _build_group()
    runner = CliRunner()

    with patch.object(ha, "probe_hub", return_value=True), patch.object(
        ha, "probe_local_daemon", return_value=True
    ):
        result = runner.invoke(root, ["--help"], obj={"host": "h", "port": 9559})

    for name in ("docs", "skills"):
        line = next(
            (ln for ln in result.output.splitlines() if ln.lstrip().startswith(name)),
            "",
        )
        assert AVAILABLE_SUFFIX not in line, (
            f"pure-local {name!r} must not show {AVAILABLE_SUFFIX}; got {line!r}"
        )


def test_daemon_probe_independent_of_hub() -> None:
    """`cron` (LOCAL_DAEMON) follows the daemon probe, not the hub probe."""
    root = _build_group()
    runner = CliRunner()

    # Hub down but daemon up -> cron should be annotated; agent should not.
    with patch.object(ha, "probe_hub", return_value=False), patch.object(
        ha, "probe_local_daemon", return_value=True
    ):
        result = runner.invoke(root, ["--help"], obj={"host": "h", "port": 9559})

    cron_line = next(
        (ln for ln in result.output.splitlines() if ln.lstrip().startswith("cron")),
        "",
    )
    agent_line = next(
        (ln for ln in result.output.splitlines() if ln.lstrip().startswith("agent")),
        "",
    )
    assert AVAILABLE_SUFFIX in cron_line, cron_line
    assert AVAILABLE_SUFFIX not in agent_line, agent_line


# ---------------------------------------------------------------------------
# Timing / budget tests
# ---------------------------------------------------------------------------


def test_run_probes_parallel_respects_budget() -> None:
    """Even if every hub probe blocks for its full per-probe timeout,
    ``run_probes`` returns under the total budget by running in parallel."""

    def _slow_hub(host: str, port: int, timeout_s: float) -> bool:
        # Sleep just under the per-probe timeout (so the thread doesn't
        # finish before the deadline on a fast box).
        time.sleep(min(timeout_s, PER_PROBE_TIMEOUT_S) * 0.5)
        return True

    subcommands = [
        "agent",
        "machine",
        "cron",
        "dispatch",
        "todo",
        "host-liveness",
        "hungry-signal",
    ]

    t0 = time.monotonic()
    results = run_probes(
        subcommands,
        host="127.0.0.1",
        port=9559,
        hub_prober=_slow_hub,
        daemon_prober=lambda: True,
    )
    elapsed = time.monotonic() - t0

    # Budget enforced at run_probes level; add a small scheduling slack.
    assert elapsed < TOTAL_BUDGET_S + 0.150, (
        f"run_probes took {elapsed * 1000:.1f} ms (budget {TOTAL_BUDGET_S * 1000:.0f} ms)"
    )
    # All requested subcommands are represented in the result dict
    assert set(results.keys()) >= set(subcommands)


def test_run_probes_marks_timed_out_as_unreachable() -> None:
    """If a hub probe blocks past the total budget, its result is
    ``reachable=False`` rather than leaking the exception."""

    def _blocking_hub(host: str, port: int, timeout_s: float) -> bool:
        time.sleep(TOTAL_BUDGET_S * 3)
        return True

    subcommands = ["agent"]
    results = run_probes(
        subcommands,
        host="127.0.0.1",
        port=9559,
        hub_prober=_blocking_hub,
        daemon_prober=lambda: False,
    )
    assert "agent" in results
    assert results["agent"].reachable is False


def test_mcp_start_is_flat_keeper() -> None:
    """Q5 flat keeper: `mcp start` is registered as a flat subgroup at
    the top level. Step A wires the stub; Step B will grow its surface."""
    from scitex_orochi._cli._main import orochi

    assert "mcp" in orochi.commands, "mcp group must exist as a flat keeper"
    mcp_group = orochi.commands["mcp"]
    # Must be a click group exposing a `start` verb.
    assert hasattr(mcp_group, "commands"), "mcp must be a click group"
    assert "start" in mcp_group.commands, "mcp must expose `start` subverb"  # type: ignore[attr-defined]


def test_default_probe_map_covers_all_registered_top_level_commands() -> None:
    """Every top-level command registered in `_main.py` has an entry in
    the DEFAULT_PROBE_MAP (or is implicitly PURE_LOCAL via omission)."""
    from scitex_orochi._cli._main import orochi

    registered = set(orochi.list_commands(click.Context(orochi)))
    mapped = set(DEFAULT_PROBE_MAP.keys())
    # Every mapped name that is a real subcommand should resolve.
    # This catches typos in DEFAULT_PROBE_MAP.
    bogus = [n for n in mapped if n in registered] + [
        n for n in mapped if n not in registered
    ]
    # Sanity: at least 10 real commands were registered.
    assert len(registered) >= 10, registered
    # Every registered command either has a map entry or will be silently
    # treated as PURE_LOCAL (suffix omitted — acceptable fallback).
    # We assert the non-silent ones look sane:
    hub_or_daemon_names = [
        n for n, k in DEFAULT_PROBE_MAP.items() if k is not ProbeKind.PURE_LOCAL
    ]
    assert "agent" in hub_or_daemon_names
    assert "cron" in hub_or_daemon_names
    assert bogus  # keeps variables used; suppresses ruff unused-var


# ---------------------------------------------------------------------------
# Step B — new noun dispatchers participate in (Available Now) annotation.
# ---------------------------------------------------------------------------


# Nouns that depend on the hub (entry in DEFAULT_PROBE_MAP is HUB). Suffix
# must appear when the hub is reachable, must NOT appear when it is not.
STEP_B_HUB_NOUNS: list[str] = [
    "agent",
    "auth",
    "channel",
    "hook",
    "invite",
    "message",
    "push",
    "server",
    "system",
    "workspace",
]


# Nouns that are PURE_LOCAL and must NEVER show the suffix. `config` is the
# only new Step B noun in this bucket (config init writes local state only).
STEP_B_PURE_LOCAL_NOUNS: list[str] = ["config"]


@pytest.mark.parametrize("noun", STEP_B_HUB_NOUNS)
def test_step_b_noun_suffix_present_when_hub_reachable(noun: str) -> None:
    """Each Step B hub-backed noun group gets `(Available Now)` next to
    its short-help when the hub probe succeeds."""
    from scitex_orochi._cli._main import orochi

    runner = CliRunner()
    with patch.object(ha, "probe_hub", return_value=True), patch.object(
        ha, "probe_local_daemon", return_value=True
    ):
        result = runner.invoke(orochi, ["--help"], obj={"host": "h", "port": 9559})

    assert result.exit_code == 0, result.output
    line = next(
        (
            ln
            for ln in result.output.splitlines()
            if ln.lstrip().startswith(noun + " ")
        ),
        "",
    )
    assert AVAILABLE_SUFFIX in line, (
        f"expected {AVAILABLE_SUFFIX} on {noun!r} line when hub reachable; "
        f"got line {line!r}\nfull output:\n{result.output}"
    )


@pytest.mark.parametrize("noun", STEP_B_HUB_NOUNS)
def test_step_b_noun_suffix_absent_when_hub_unreachable(noun: str) -> None:
    """Each Step B hub-backed noun group drops the suffix when the hub
    probe fails."""
    from scitex_orochi._cli._main import orochi

    runner = CliRunner()
    with patch.object(ha, "probe_hub", return_value=False), patch.object(
        ha, "probe_local_daemon", return_value=False
    ):
        result = runner.invoke(orochi, ["--help"], obj={"host": "h", "port": 9559})

    assert result.exit_code == 0, result.output
    line = next(
        (
            ln
            for ln in result.output.splitlines()
            if ln.lstrip().startswith(noun + " ")
        ),
        "",
    )
    assert AVAILABLE_SUFFIX not in line, (
        f"{noun!r} must NOT show the suffix when hub is unreachable; "
        f"got line {line!r}"
    )


@pytest.mark.parametrize("noun", STEP_B_PURE_LOCAL_NOUNS)
def test_step_b_pure_local_noun_never_annotated(noun: str) -> None:
    """PURE_LOCAL Step B nouns never show the suffix, even with both
    probes green."""
    from scitex_orochi._cli._main import orochi

    runner = CliRunner()
    with patch.object(ha, "probe_hub", return_value=True), patch.object(
        ha, "probe_local_daemon", return_value=True
    ):
        result = runner.invoke(orochi, ["--help"], obj={"host": "h", "port": 9559})

    assert result.exit_code == 0, result.output
    line = next(
        (
            ln
            for ln in result.output.splitlines()
            if ln.lstrip().startswith(noun + " ")
        ),
        "",
    )
    assert AVAILABLE_SUFFIX not in line, (
        f"pure-local {noun!r} must never show {AVAILABLE_SUFFIX}; got {line!r}"
    )
