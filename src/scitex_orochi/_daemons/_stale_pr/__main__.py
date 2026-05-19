"""``python -m scitex_orochi._daemons._stale_pr`` entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scitex_orochi._daemons._stale_pr._state import StalePrState
from scitex_orochi._daemons._stale_pr._wrapper import StalePrConfig, run_loop


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="daemon-stale-pr",
        description=(
            "Sac-managed daemon-agent that polls gitea for stuck CI-green "
            "PRs and DMs the suggested merger. Tick interval and repo "
            "list come from --config (default: "
            "~/.scitex/orochi/daemons.yaml)."
        ),
    )
    p.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".scitex" / "orochi" / "daemons.yaml",
        help="Path to daemons.yaml.",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit (smoke test).",
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
    cfg = StalePrConfig.from_env_and_yaml(args.config)
    state = StalePrState()
    state.load()
    run_loop(cfg, state, max_ticks=1 if args.once else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
