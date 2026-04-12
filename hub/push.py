"""Web Push fan-out for Orochi message events.

todo#263 — server-side counterpart to ``hub/static/hub/push.js``. The
``send_push_to_subscribers`` function is the single hook called from
both the WS consumer path (``AgentConsumer.receive_json``,
``DashboardConsumer.receive_json``) and the REST POST
``api_messages`` path so that any persisted message reaches every
PWA-subscribed user via VAPID Web Push.

Failures (no VAPID config, dead endpoint, network error) are logged
but never raised — push is best-effort and must not break the
message-write code path.
"""

import json
import logging
import threading

from django.conf import settings

log = logging.getLogger("orochi.push")


def _vapid_claims():
    return {"sub": settings.SCITEX_OROCHI_VAPID_SUBJECT}


def _is_self_send(sender: str, sub_username: str) -> bool:
    """Return True iff this push subscription belongs to the sender.

    Senders may be a Django username (humans) or a bare agent name
    (``agent-<name>`` Django stand-in). Match both shapes.
    """
    if not sender or not sub_username:
        return False
    if sub_username == sender:
        return True
    if sub_username == f"agent-{sender}":
        return True
    return False


def send_push_to_subscribers(
    workspace_id,
    channel,
    sender,
    content,
    message_id=None,
):
    """Fan a single message out to every matching ``PushSubscription``.

    - Filters subscriptions by workspace + optional per-row channel list.
    - Excludes the sender's own subscriptions.
    - Deletes stale (404/410) endpoints reported by the push service.
    - Returns the count of attempted deliveries (for tests).
    """
    public_key = getattr(settings, "SCITEX_OROCHI_VAPID_PUBLIC", "")
    private_key = getattr(settings, "SCITEX_OROCHI_VAPID_PRIVATE", "")
    if not public_key or not private_key:
        log.debug("VAPID not configured — skipping push fan-out")
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except Exception as exc:
        log.warning("pywebpush import failed: %s", exc)
        return 0

    from hub.models import PushSubscription

    qs = PushSubscription.objects.filter(workspace_id=workspace_id).select_related(
        "user"
    )

    payload = json.dumps(
        {
            "title": f"{channel} — {sender}",
            "body": (content or "")[:200],
            "url": f"/?channel={channel}",
            "tag": f"msg-{message_id}" if message_id else f"ch-{channel}",
        }
    )

    attempted = 0
    for sub in qs:
        # Per-subscription channel filter (empty == no filter).
        if sub.channels and channel not in sub.channels:
            continue
        # Skip the sender's own devices.
        if _is_self_send(sender, getattr(sub.user, "username", "")):
            continue

        attempted += 1
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=dict(_vapid_claims()),
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                log.info(
                    "Pruning stale push subscription #%s (status=%s)",
                    sub.pk,
                    status,
                )
                try:
                    sub.delete()
                except Exception:
                    log.exception("Failed to delete stale push sub #%s", sub.pk)
            else:
                log.warning(
                    "WebPush delivery failed for #%s: %s", sub.pk, exc
                )
        except Exception:
            log.exception("Unexpected error sending push to #%s", sub.pk)

    return attempted


def send_push_to_subscribers_async(
    workspace_id,
    channel,
    sender,
    content,
    message_id=None,
):
    """Background-thread variant — fire-and-forget for hot WS paths."""
    t = threading.Thread(
        target=send_push_to_subscribers,
        args=(workspace_id, channel, sender, content, message_id),
        daemon=True,
    )
    t.start()
    return t
