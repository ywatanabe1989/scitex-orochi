"""Tests for the ``scitex-orochi cron`` CLI group.

Validates each subcommand's behavior via ``click.testing.CliRunner``:

* ``cron list`` reads the state file and prints JSON on ``--json``.
* ``cron list`` with no state file emits an empty array (JSON) /
  a friendly text line.
* ``cron run <name>`` shells out a trivial command + returns its exit.
* ``cron status`` distinguishes "no orochi_pid file" vs "live orochi_pid" vs "stale orochi_pid".
* ``cron reload`` errors clearly when the daemon isn't running.

These tests don't actually load or spawn the OS-native unit — they
exercise the Python surface that the unit is wrapping.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

from click.testing import CliRunner

from scitex_orochi._cli.commands.cron_cmd import cron
from scitex_orochi._cron import CronDaemon


def _invoke_list(runner: CliRunner, state_path: Path, as_json: bool):
    # Match how _main.py threads ctx.obj through — use obj= to seed it.
    args = ["list", "--state", str(state_path)]
    return runner.invoke(cron, args, obj={"json": as_json})


def test_list_no_state_json(tmp_path):
    runner = CliRunner()
    result = _invoke_list(runner, tmp_path / "nope.json", as_json=True)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_list_no_state_text(tmp_path):
    runner = CliRunner()
    result = _invoke_list(runner, tmp_path / "nope.json", as_json=False)
    assert result.exit_code == 0
    assert "no jobs registered" in result.output


def test_list_with_state(tmp_path):
    # Populate state by loading a daemon against a small yaml.
    cfg = tmp_path / "cron.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            jobs:
              - name: a
                interval: 1m
                command: "/bin/true"
              - name: b
                interval: 2m
                command: "/bin/true"
            """
        )
    )
    state_path = tmp_path / "state.json"
    d = CronDaemon(config_path=cfg, state_path=state_path, pid_path=tmp_path / "p", log_dir=tmp_path / "l")
    d.load()

    runner = CliRunner()
    result = _invoke_list(runner, state_path, as_json=True)
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert {r["name"] for r in rows} == {"a", "b"}
    assert rows[0]["interval"] in (60, 120)


def test_run_happy(tmp_path):
    cfg = tmp_path / "cron.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            jobs:
              - name: ping
                interval: 5m
                command: "/bin/echo hello"
            """
        )
    )
    runner = CliRunner()
    result = runner.invoke(
        cron, ["run", "ping", "--config", str(cfg)], obj={"json": True}
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["exit_code"] == 0
    assert "hello" in payload["stdout_tail"]


def test_run_unknown_job(tmp_path):
    cfg = tmp_path / "cron.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            jobs:
              - name: ping
                interval: 5m
                command: "/bin/echo hello"
            """
        )
    )
    runner = CliRunner()
    result = runner.invoke(
        cron, ["run", "missing", "--config", str(cfg)], obj={"json": True}
    )
    assert result.exit_code != 0


def test_status_no_pid(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cron,
        [
            "status",
            "--orochi_pid",
            str(tmp_path / "nope.orochi_pid"),
            "--state",
            str(tmp_path / "nope.json"),
        ],
        obj={"json": True},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["daemon_pid"] == 0
    assert payload["daemon_running"] is False


def test_status_alive_pid(tmp_path):
    # Use our own PID — guaranteed alive for the duration of the test.
    pid_path = tmp_path / "daemon.orochi_pid"
    pid_path.write_text(str(os.getpid()))
    runner = CliRunner()
    result = runner.invoke(
        cron,
        ["status", "--orochi_pid", str(pid_path), "--state", str(tmp_path / "nope.json")],
        obj={"json": True},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["daemon_pid"] == os.getpid()
    assert payload["daemon_running"] is True


def test_status_stale_pid(tmp_path):
    # Pick a PID far outside the kernel's typical range so os.kill(p, 0)
    # reliably returns ProcessLookupError. If the chosen PID happens to
    # be live on this CI host we fall back to an also-unlikely-live PID.
    pid_path = tmp_path / "daemon.orochi_pid"
    # 99999999 is > max_pid on all reasonable kernels (default 2^22).
    pid_path.write_text("99999999")
    runner = CliRunner()
    result = runner.invoke(
        cron,
        ["status", "--orochi_pid", str(pid_path), "--state", str(tmp_path / "nope.json")],
        obj={"json": True},
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["daemon_pid"] == 99999999
    assert payload["daemon_running"] is False


def test_reload_not_running(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cron, ["reload", "--orochi_pid", str(tmp_path / "nope.orochi_pid")])
    assert result.exit_code != 0
    assert "not running" in result.output
