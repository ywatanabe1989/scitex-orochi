"""Verify ``heartbeat-push`` surfaces ``cron_jobs`` in the outgoing payload.

Phase 2 will wire the Machines tab UI panel directly off
``/api/agents/register/`` body's ``cron_jobs`` field, so Phase 1 needs
to guarantee that field is populated from the cron daemon's state
file whenever the daemon is running — and is an empty list otherwise
(no crash, no NPE).
"""

from __future__ import annotations

import textwrap

from scitex_orochi._cli.commands.heartbeat_cmd import _wrap_with_orochi_fields
from scitex_orochi._cron import CronDaemon


def test_cron_jobs_empty_when_no_state(monkeypatch, tmp_path):
    # Point the cron module at an empty state path so the helper
    # degrades gracefully.
    from scitex_orochi import _cron

    monkeypatch.setattr(
        _cron, "default_state_path", lambda: tmp_path / "missing.json"
    )
    body = _wrap_with_orochi_fields({"name": "head-test"}, token="t", channels=None)
    assert body["cron_jobs"] == []


def test_cron_jobs_populated(monkeypatch, tmp_path):
    cfg = tmp_path / "cron.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            jobs:
              - name: ping
                interval: 5m
                command: "/bin/true"
            """
        )
    )
    state_path = tmp_path / "state.json"
    d = CronDaemon(
        config_path=cfg,
        state_path=state_path,
        pid_path=tmp_path / "pid",
        log_dir=tmp_path / "logs",
    )
    d.load()

    from scitex_orochi import _cron

    monkeypatch.setattr(_cron, "default_state_path", lambda: state_path)

    body = _wrap_with_orochi_fields({"name": "head-test"}, token="t", channels=None)
    assert isinstance(body["cron_jobs"], list)
    assert len(body["cron_jobs"]) == 1
    row = body["cron_jobs"][0]
    assert row["name"] == "ping"
    assert row["interval"] == 300
    assert row["disabled"] is False
