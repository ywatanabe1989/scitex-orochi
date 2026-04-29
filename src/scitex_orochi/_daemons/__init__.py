"""Sac-managed daemon-agents.

Per lead msg#23306 / msg#23310, fleet daemon-agents are sac-managed
tmux sessions that wake on a tick (or on inbound messages, in the
auditor-haiku case), do deterministic work, post a one-line summary
to ``#daemons`` (or ``#general`` until that channel exists), and
sleep again. Each tick is a fresh process so context is naturally
cleared (ZOO#04 cost). This package collects the per-daemon
implementations.

Daemons:
    * ``daemon-stale-pr`` — gitea polling for stuck CI-green PRs (FR-N).
    * ``daemon-auditor-haiku`` — fleet-wide ZOO/banned-phrase auditor
      (FR-M). Stage 1 ships regex-only with shadow posts to
      ``#audit-shadow``.
"""
