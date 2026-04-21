"""worker-progress daemon package (todo#272).

Split out of ``scripts/server/worker-progress.py`` so each module stays
well under the 512-line cap used by the rest of the repo.

Modules:
  - ``_cli``      : argparse + main entry point
  - ``_config``   : env/URL resolution + log-path helpers
  - ``_digest``   : 60 s throttle + dedup coalescer (pure, testable)
  - ``_client``   : aiohttp-free websockets WS loop with reconnect
  - ``_daemon``   : top-level ``run()`` glue

Import surface is intentionally small; tests reach into ``_digest`` for
the coalescer logic and into ``_config`` for path resolution. The
``_client`` and ``_daemon`` modules require real network / event-loop
scaffolding so tests stub them.
"""

from __future__ import annotations

__all__ = ["AGENT_NAME", "SUBSCRIBE_CHANNELS"]

# Synthetic agent name under which the daemon registers. Must match the
# ``hub/management/commands/seed_worker_progress.py`` seed so the
# ChannelMembership rows line up (agent user = ``agent-worker-progress``).
AGENT_NAME = "worker-progress"

# Canonical subscribe set for v1. ``#agent`` was abolished 2026-04-21
# (lead directive, PR #293 follow-up) and is explicitly NOT in this
# list. The server-side blocklist in ``hub/consumers/_helpers.py``
# (``ABOLISHED_AGENT_CHANNELS``) would reject it anyway.
SUBSCRIBE_CHANNELS = ("#progress", "#heads", "#ywatanabe")

# The channel we emit digests / acks to. Must be in SUBSCRIBE_CHANNELS
# (so we can actually write to it) and match the seed command.
DIGEST_CHANNEL = "#ywatanabe"
