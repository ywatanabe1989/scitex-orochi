"""Command-line argv parsing for agent_meta.

Preserves the legacy flag set:
    agent_meta.py <agent>
    agent_meta.py --push [--url URL] [--token TOKEN]
"""

from __future__ import annotations

import json
import sys

from ._collect import main
from ._push import push_all


def cli_main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch. Returns the desired sys.exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--push":
        url = None
        token = None
        i = 1
        while i < len(args):
            if args[i] == "--url" and i + 1 < len(args):
                url = args[i + 1]
                i += 2
            elif args[i] == "--token" and i + 1 < len(args):
                token = args[i + 1]
                i += 2
            else:
                i += 1
        n = push_all(url=url, token=token)
        print(json.dumps({"pushed": n}))
        return 0
    if len(args) != 1:
        print(
            "Usage: agent_meta.py <agent>  |  agent_meta.py --push [--url URL] [--token TOKEN]",
            file=sys.stderr,
        )
        return 2
    main(args[0])
    return 0
