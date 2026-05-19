"""JSON-backed last-notified-at store for ``daemon-stale-pr``.

Tiny by design: a flat ``{key -> unix_ts}`` map, atomic-write on
update, tolerant of corrupt files (treats them as empty so a single
bad write doesn't lock the daemon out forever — operator can inspect
the ``.bak`` if needed).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("orochi.daemon.stale_pr.state")

DEFAULT_STATE_PATH = (
    Path.home() / ".scitex" / "orochi" / "state" / "daemon-stale-pr.json"
)


class StalePrState:
    """Last-notified-at debounce store.

    Not thread-safe — the daemon is a single-threaded sleep loop, so
    locking would be ceremony. If we ever multi-thread, wrap the
    mutator methods in a ``threading.Lock``.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STATE_PATH
        self.last_notified_ts: dict[str, float] = {}
        self._loaded = False

    def load(self) -> None:
        """Read the state file. Missing or corrupt → empty in-memory map."""
        self._loaded = True
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.last_notified_ts = {}
            return
        except OSError as exc:
            logger.warning("stale-pr state: read failed %s: %s", self.path, exc)
            self.last_notified_ts = {}
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "stale-pr state: corrupt JSON at %s — treating as empty (%s)",
                self.path,
                exc,
            )
            # Preserve the corrupt file as .bak for forensic inspection
            # rather than silently overwriting the operator's evidence.
            try:
                self.path.replace(self.path.with_suffix(".json.bak"))
            except OSError:
                pass
            self.last_notified_ts = {}
            return
        # Defensive: only keep keys whose values look like numbers.
        cleaned: dict[str, float] = {}
        for k, v in data.items():
            try:
                cleaned[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        self.last_notified_ts = cleaned

    def save(self) -> None:
        """Atomic-write the state file."""
        if not self._loaded:
            # Avoid clobbering an unread file with an empty map.
            self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.last_notified_ts, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def record_notified(self, key: str, when: float | None = None) -> None:
        """Record that a DM was successfully sent for ``key``."""
        if not self._loaded:
            self.load()
        self.last_notified_ts[key] = when if when is not None else time.time()
        self.save()


__all__ = ["StalePrState", "DEFAULT_STATE_PATH"]
