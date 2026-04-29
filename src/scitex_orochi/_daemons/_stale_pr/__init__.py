"""``daemon-stale-pr`` — gitea polling daemon for stuck CI-green PRs.

FR-N (lead msg#23297 + msg#23310). Polls the configured gitea repos
every ``tick_interval_s``, finds PRs that are ``mergeable=True`` with
all CI checks ``success`` and age > threshold, and DMs the suggested
merger (head-{host} per repo) at most once per debounce window.

Public surface:
    * :func:`is_stale` — pure predicate over a PR + commit-status pair
    * :func:`select_stale_for_dm` — wrap :func:`is_stale` + state debounce
    * :class:`StalePrState` — JSON-backed last-notified-at store
    * :func:`run_tick` — one wrapper tick (used by ``__main__``)
"""

from scitex_orochi._daemons._stale_pr._check import (
    StalePrFinding,
    is_stale,
    select_stale_for_dm,
)
from scitex_orochi._daemons._stale_pr._state import StalePrState

__all__ = [
    "StalePrFinding",
    "is_stale",
    "select_stale_for_dm",
    "StalePrState",
]
