"""Django app config for hub — wires up DM rename signals (spec v3 §2.2)."""

import logging
import os
import threading
import time

from django.apps import AppConfig

log = logging.getLogger("orochi.scheduler")


def _scheduler_loop():
    """Background thread: fire due ScheduledActions every 60s (issue #95)."""
    # Wait for Django to fully initialize before using ORM
    time.sleep(5)
    while True:
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            from django.utils import timezone

            from apps.hub.models import (
                Channel,
                Message,
                ScheduledAction,
                normalize_channel_name,
            )

            now = timezone.now()
            due = ScheduledAction.objects.filter(
                status=ScheduledAction.STATUS_PENDING,
                run_at__lte=now,
            ).select_related("workspace")

            for action in due:
                try:
                    channel_name = normalize_channel_name(action.channel or "general")
                    ch, _ = Channel.objects.get_or_create(
                        workspace=action.workspace, name=channel_name
                    )
                    text = (
                        f"[scheduled task for @{action.agent}] {action.task}"
                        f"\n_(scheduled by {action.created_by or 'system'} at {action.run_at.isoformat()})_"
                    )
                    msg = Message.objects.create(
                        workspace=action.workspace,
                        channel=ch,
                        sender="hub",
                        sender_type="system",
                        content=text,
                        metadata={"source": "scheduled_action", "action_id": action.id},
                    )
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        group = f"workspace_{action.workspace_id}"
                        async_to_sync(channel_layer.group_send)(
                            group,
                            {
                                "type": "chat.message",
                                "id": msg.id,
                                "sender": "hub",
                                "sender_type": "system",
                                "channel": channel_name,
                                "kind": "group",
                                "text": text,
                                "ts": msg.ts.isoformat(),
                                "metadata": {"source": "scheduled_action"},
                            },
                        )
                    action.status = ScheduledAction.STATUS_FIRED
                    action.fired_at = now
                    action.save(update_fields=["status", "fired_at"])
                    log.info(
                        "Fired scheduled action %s for agent %s",
                        action.id,
                        action.agent,
                    )
                except Exception:
                    log.exception("Error firing scheduled action %s", action.id)
        except Exception:
            log.exception("Scheduler loop error")
        time.sleep(60)


class HubConfig(AppConfig):
    # Module path after the ADR-0002 migration is ``apps.hub``; the
    # Django *app_label* is pinned to ``hub`` so existing migrations
    # (``("hub", "0001_...")``), model references (``to="hub.message"``)
    # and the ``hub_*`` DB table names stay valid without a data
    # migration.
    name = "apps.hub"
    label = "hub"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Importing the module registers the post_save handlers.
        from django.conf import settings

        from apps.hub import signals  # noqa: F401

        # Start scheduled-action background thread (issue #95).
        #
        # Skipped under the test suite: the long-lived loop queries
        # ``ScheduledAction`` on its own connection, but the Django/pytest test
        # runner creates and tears down an ephemeral per-run database around it.
        # The thread then races that lifecycle and intermittently raises
        # ``no such table: hub_scheduledaction`` / ``database is locked``. The
        # ``RUN_BACKGROUND_SCHEDULER`` setting (False under tests by default,
        # see ``settings_shared``) gates it; operators can still force it via
        # ``SCITEX_OROCHI_RUN_SCHEDULER``.
        if not getattr(settings, "RUN_BACKGROUND_SCHEDULER", True):
            return

        # Guard against double-start during Django auto-reload.
        if os.environ.get("RUN_MAIN") != "true" and not os.environ.get(
            "SCHEDULER_STARTED"
        ):
            os.environ["SCHEDULER_STARTED"] = "1"
            t = threading.Thread(
                target=_scheduler_loop, name="orochi-scheduler", daemon=True
            )
            t.start()
            log.info("Scheduled-action background thread started")
