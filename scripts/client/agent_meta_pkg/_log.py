"""Shared logger for agent_meta submodules."""

from __future__ import annotations

import logging

log = logging.getLogger("agent_meta")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s agent_meta %(message)s",
    )
