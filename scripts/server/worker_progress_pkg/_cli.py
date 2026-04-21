"""CLI entry point for the worker-progress daemon."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ._config import default_log_path
from ._daemon import run


def _setup_logging(log_path: Path, level: int = logging.INFO) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    # File handler — persistent log.
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    # Stderr handler — launchd / systemd also capture stderr.
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="worker-progress",
        description=(
            "Headless Orochi daemon that coalesces #progress / #heads / "
            "#ywatanabe traffic into one 60 s digest line per window "
            "(todo#272)."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't connect to the hub; log would-post lines to stderr "
            "instead. Useful for install smoke-tests."
        ),
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run one tick cycle, then exit (test harness only).",
    )
    p.add_argument(
        "--url",
        default="",
        help=(
            "Override the hub WS base URL (default: $SCITEX_OROCHI_URL_WS "
            "else wss://scitex-orochi.com)."
        ),
    )
    p.add_argument(
        "--log-path",
        default="",
        help=(
            "Override log file path (default: ~/Library/Logs/scitex/"
            "worker-progress.log on macOS, ~/.local/state/scitex/"
            "worker-progress.log on Linux)."
        ),
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p


def cli_main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log_path = Path(args.log_path) if args.log_path else default_log_path()
    _setup_logging(log_path, logging.DEBUG if args.verbose else logging.INFO)
    try:
        return asyncio.run(
            run(
                dry_run=args.dry_run,
                once=args.once,
                url=args.url,
            )
        )
    except KeyboardInterrupt:
        logging.getLogger("worker-progress").info("KeyboardInterrupt → exiting")
        return 0
