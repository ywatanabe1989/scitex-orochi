#!/usr/bin/env -S python3 -u
"""worker-progress daemon — throttled digest relay for @ywatanabe (todo#272).

This is a plain long-running Python daemon (NOT a Claude process, NOT an
``sac``-managed agent, NOT a ``.claude/agents/*`` definition). It:

1. Opens a WebSocket to the Orochi hub as the synthetic agent
   ``worker-progress`` using the workspace token in
   ``$SCITEX_OROCHI_TOKEN`` (same env used by every other hub client;
   see ``scripts/client/agent_meta.py`` and
   ``scripts/client/fleet-watch/fleet_watch.sh``).
2. Hydrates its channel subscriptions from the server-authoritative
   ``ChannelMembership`` rows (spec v3 §3.1 — register's client-side
   ``channels`` array is ignored by the hub; run
   ``python manage.py seed_worker_progress`` once to create the rows
   for ``#progress``, ``#heads``, ``#ywatanabe``).
3. Coalesces inbound events with a 60 s throttle and, on each tick,
   emits ONE short summary line to ``#ywatanabe``. Zero events in a
   window → silent (no heartbeat post).
4. On ``@worker-progress`` mention or DM, bypasses the throttle and
   posts a single-line polite-ack. The full ``claude-code`` spawn is
   out of scope for v1 and tracked under todo#272.

The daemon is split across sibling modules under
``scripts/server/worker_progress_pkg/`` so each file stays under the
512-line cap that the rest of the repo follows. Entry-point kept here
so existing ``scripts/server/`` conventions still work; the real code
lives next door.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from worker_progress_pkg._cli import cli_main  # noqa: E402


if __name__ == "__main__":
    sys.exit(cli_main())
