"""Allow ``python -m agent_meta_pkg`` invocation."""

from __future__ import annotations

import sys

from ._cli import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
