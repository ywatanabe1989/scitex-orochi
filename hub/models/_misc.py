"""Miscellaneous models — push subscriptions, fleet reports, tracked repos."""

from django.conf import settings
from django.db import models

from ._identity import Workspace


class PushSubscription(models.Model):
    """A Web Push subscription registered by a browser/PWA client.

    todo#263 — server side of the existing ``hub/static/hub/push.js``
    PWA client. The endpoint+keys triple is what ``pywebpush.webpush()``
    needs to deliver a notification. ``channels`` is an optional
    per-subscription channel filter (empty list means "all channels the
    user can read"); ``workspace`` scopes the subscription so cross-
    workspace fan-out never bleeds.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        null=True,
        blank=True,
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=100)
    auth = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    # Optional channel filter — empty list = no filter (push for any
    # channel the user can read).
    channels = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "hub"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "workspace"]),
        ]

    def __str__(self):
        return f"push:{self.user}@{self.endpoint[:40]}"


class FleetReport(models.Model):
    ENTITY_TYPES = [
        ("machine", "Machine"),
        ("agent", "Agent"),
        ("server", "Orochi Server"),
        ("session", "Claude Session"),
    ]
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPES)
    entity_id = models.CharField(max_length=128)  # e.g. "nas", "head-mba", etc.
    ts = models.DateTimeField(auto_now_add=True, db_index=True)
    payload = models.JSONField(default=dict)
    source = models.CharField(max_length=128)  # who reported this

    class Meta:
        app_label = "hub"
        indexes = [
            models.Index(fields=["entity_type", "entity_id", "-ts"]),
        ]

    def __str__(self):
        return f"{self.entity_type}:{self.entity_id} @ {self.ts}"


class TrackedRepo(models.Model):
    """A GitHub repository whose CHANGELOG.md appears as a sub-tab in the
    Releases view.

    Repos are per-workspace so each team can curate its own release feed.
    The pair ``(owner, repo)`` is unique within a workspace. ``order`` is
    the manual sort position managed by the drag-and-drop UI (todo#91);
    ties fall back to insertion order via ``id``.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="tracked_repos"
    )
    owner = models.CharField(max_length=100)
    repo = models.CharField(max_length=100)
    label = models.CharField(max_length=100, blank=True, default="")
    order = models.IntegerField(default=0, db_index=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tracked_repos",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "hub"
        unique_together = ("workspace", "owner", "repo")
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.owner}/{self.repo}@{self.workspace.name}"

    @property
    def display_label(self) -> str:
        return self.label or self.repo
