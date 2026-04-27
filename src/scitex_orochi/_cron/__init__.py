"""Orochi unified cron daemon — scheduler + state access helpers.

Replaces the scattered ``install-*.sh`` -> per-job launchd/systemd/cron
entries with one YAML-declared daemon per host. The daemon owns the
scheduling loop; the OS-native unit only needs to keep *it* alive.

Phase 1 scope (msg#16406 / msg#16410 / lead msg#16408):

* ``Job``, ``JobRun``, ``CronConfig`` dataclasses + ``load_config``
  YAML parser.
* ``CronDaemon`` — long-running scheduler using stdlib threading (no
  new pip deps).
* ``state_read`` helper the CLI + heartbeat pusher both consume so
  ``cron_jobs`` can surface in ``scitex-orochi cron list`` AND in the
  heartbeat payload without a second source of truth.

See ``deployment/host-setup/orochi-cron/cron.yaml.example`` for the
schema + default job list.
"""

from __future__ import annotations

from scitex_orochi._cron._config import (
    CronConfig,
    Job,
    default_config_path,
    default_log_dir,
    default_state_path,
    load_config,
    parse_interval,
)
from scitex_orochi._cron._daemon import CronDaemon
from scitex_orochi._cron._state import JobRun, state_read, state_write

__all__ = [
    "CronConfig",
    "CronDaemon",
    "Job",
    "JobRun",
    "default_config_path",
    "default_log_dir",
    "default_state_path",
    "load_config",
    "parse_interval",
    "state_read",
    "state_write",
]
