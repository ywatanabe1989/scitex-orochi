"""``python -m scitex_orochi._daemons._auditor_haiku`` entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from scitex_orochi._daemons._auditor_haiku._subscriber import (
    AuditorConfig,
    run,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="daemon-auditor-haiku",
        description=(
            "Stage 1 fleet-wide audit daemon. Subscribes to fleet "
            "channels, runs the regex rule layer on every inbound "
            "message, and posts a verdict line to the publish channel "
            "(default #audit-shadow). All config via env: see "
            "AuditorConfig.from_env."
        ),
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = AuditorConfig.from_env()
    if not cfg.hub_host or not cfg.token:
        print(
            "daemon-auditor-haiku: OROCHI_HUB_HOST / OROCHI_HUB_TOKEN unset, "
            "refusing to start (no shadow target).",
            file=sys.stderr,
            flush=True,
        )
        return 2
    asyncio.run(run(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
