"""Allow ``python -m _collect_agent_metadata`` invocation."""

from __future__ import annotations

import sys

from ._cli import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
