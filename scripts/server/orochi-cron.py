#!/usr/bin/env -S python3 -u
"""Orochi unified cron daemon (msg#16406 / msg#16410 / lead msg#16408).

One process per host replaces the per-job scatter of launchd plists /
systemd timers / crontab lines. Reads ``~/.scitex/orochi/cron.yaml``,
runs each declared job at its cadence, captures structured results,
and writes a shared state file the CLI + heartbeat pusher both read.

All scheduling logic lives in ``scitex_orochi._cron.CronDaemon`` — this
script is a thin CLI wrapper so the OS-native unit only has to know
how to exec a Python file with the right flags.

Usage::

    orochi-cron.py                            # normal daemon
    orochi-cron.py --config /path/cron.yaml   # override YAML location
    orochi-cron.py --dry-run                  # log "would run" only

Exit codes:
    0  — clean shutdown after SIGTERM/SIGINT
    2  — config parse error at startup (log to stderr, crash-visibly)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scitex_orochi._cron import (
    CronDaemon,
    default_config_path,
    default_log_dir,
    default_state_path,
)
from scitex_orochi._cron._config import default_pid_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="orochi-cron",
        description=(
            "Unified Orochi cron daemon. One process replaces the "
            "scatter of per-job launchd plists / systemd timers."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=f"Path to cron.yaml (default: {default_config_path()})",
    )
    parser.add_argument(
        "--state",
        default=None,
        help=f"Path to state.json (default: {default_state_path()})",
    )
    parser.add_argument(
        "--pid",
        default=None,
        help=f"Path to pid file (default: {default_pid_path()})",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help=f"Per-job NDJSON log dir (default: {default_log_dir()})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tick the scheduler but only log 'would run' (no subprocesses).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = CronDaemon(
        config_path=Path(args.config) if args.config else None,
        state_path=Path(args.state) if args.state else None,
        pid_path=Path(args.pid) if args.pid else None,
        log_dir=Path(args.log_dir) if args.log_dir else None,
        dry_run=args.dry_run,
    )
    try:
        return daemon.run()
    except FileNotFoundError as exc:
        print(f"orochi-cron: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"orochi-cron: config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
