"""Push notification support for Orochi dashboard PWA.

Handles VAPID key generation, subscription storage, and sending
web push notifications via the pywebpush library.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger("orochi.push")

PUSH_SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint    TEXT PRIMARY KEY,
    keys_p256dh TEXT NOT NULL,
    keys_auth   TEXT NOT NULL,
    user_agent  TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class PushStore:
    """Manages push notification subscriptions in SQLite."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(PUSH_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def add_subscription(
        self,
        endpoint: str,
        keys_p256dh: str,
        keys_auth: str,
        user_agent: str = "",
    ) -> None:
        """Store a push subscription (upsert)."""
        if not self._db:
            raise RuntimeError("PushStore not open")
        await self._db.execute(
            "INSERT OR REPLACE INTO push_subscriptions "
            "(endpoint, keys_p256dh, keys_auth, user_agent) "
            "VALUES (?, ?, ?, ?)",
            (endpoint, keys_p256dh, keys_auth, user_agent),
        )
        await self._db.commit()
        log.info("Push subscription added: %s...", endpoint[:60])

    async def remove_subscription(self, endpoint: str) -> bool:
        """Remove a push subscription. Returns True if found."""
        if not self._db:
            raise RuntimeError("PushStore not open")
        cursor = await self._db.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        )
        await self._db.commit()
        removed = cursor.rowcount > 0
        if removed:
            log.info("Push subscription removed: %s...", endpoint[:60])
        return removed

    async def get_all_subscriptions(self) -> list[dict[str, Any]]:
        """Return all active subscriptions."""
        if not self._db:
            raise RuntimeError("PushStore not open")
        cursor = await self._db.execute(
            "SELECT endpoint, keys_p256dh, keys_auth, user_agent "
            "FROM push_subscriptions"
        )
        rows = await cursor.fetchall()
        return [
            {
                "endpoint": r[0],
                "keys": {"p256dh": r[1], "auth": r[2]},
                "user_agent": r[3],
            }
            for r in rows
        ]

    async def subscription_count(self) -> int:
        """Return number of active subscriptions."""
        if not self._db:
            raise RuntimeError("PushStore not open")
        cursor = await self._db.execute("SELECT COUNT(*) FROM push_subscriptions")
        row = await cursor.fetchone()
        return row[0] if row else 0


def generate_vapid_keys() -> dict[str, str]:
    """Generate a VAPID key pair for web push.

    Returns dict with 'private_key' (PEM) and 'public_key' (base64url).
    """
    import base64

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    assert vapid.public_key is not None, "generate_keys() must populate public_key"
    raw_pub = vapid.public_key.public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(raw_pub).decode("utf-8").rstrip("=")
    return {
        "private_key": vapid.private_pem().decode("utf-8"),
        "public_key": pub_b64,
    }


def load_vapid_keys(path: str | Path) -> dict[str, str] | None:
    """Load VAPID keys from a JSON file. Returns None if not found."""
    p = Path(path)
    if not p.exists():
        return None
    with open(p) as f:
        data = json.load(f)
    if "private_key" not in data or "public_key" not in data:
        return None
    return data


def save_vapid_keys(keys: dict[str, str], path: str | Path) -> None:
    """Save VAPID keys to a JSON file with restricted permissions."""
    import os
    import stat

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(keys, f, indent=2)
    # Restrict file permissions to owner only
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
    log.info("VAPID keys saved to %s", p)


def get_vapid_keys_path() -> Path:
    """Return the default path for VAPID keys."""
    return Path("/data/vapid-keys.json")


async def send_push_notification(
    subscription: dict[str, Any],
    payload: dict[str, str],
    vapid_private_key: str,
    vapid_claims: dict[str, str | int],
) -> bool:
    """Send a push notification to a single subscription.

    Returns True on success, False on failure.
    The subscription dict must have 'endpoint' and 'keys' (p256dh, auth).
    """
    from pywebpush import WebPushException, webpush

    try:
        subscription_info = {
            "endpoint": subscription["endpoint"],
            "keys": subscription["keys"],
        }

        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
            content_encoding="aes128gcm",
        )
        return True
    except WebPushException as exc:
        status_code = getattr(exc, "response", None)
        if status_code is not None:
            status_code = getattr(status_code, "status_code", None)
        log.error(
            "Push notification failed (status=%s): %s",
            status_code,
            str(exc)[:200],
        )
        return False
    except Exception:
        log.exception("Unexpected error sending push notification")
        return False


async def send_push_to_all(
    push_store: PushStore,
    payload: dict[str, str],
    vapid_private_key: str,
    vapid_claims: dict[str, str | int],
) -> int:
    """Send a push notification to all subscribers.

    Returns the number of successful deliveries.
    Removes subscriptions that return 404/410 (unsubscribed).
    """
    subscriptions = await push_store.get_all_subscriptions()
    if not subscriptions:
        return 0

    success_count = 0
    stale_endpoints: list[str] = []

    for sub in subscriptions:
        ok = await send_push_notification(
            subscription=sub,
            payload=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        if ok:
            success_count += 1
        else:
            # Mark stale subscriptions for removal
            stale_endpoints.append(sub["endpoint"])

    # Clean up stale subscriptions
    for endpoint in stale_endpoints:
        await push_store.remove_subscription(endpoint)

    log.info(
        "Push sent: %d/%d successful, %d stale removed",
        success_count,
        len(subscriptions),
        len(stale_endpoints),
    )
    return success_count
