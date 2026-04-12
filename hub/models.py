"""Core models for the Orochi communication hub."""

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def _generate_workspace_token():
    return f"wks_{secrets.token_hex(16)}"


class Workspace(models.Model):
    """A workspace groups channels, agents, and members — like a Slack workspace."""

    name = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=10, blank=True, default="")  # emoji
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class WorkspaceToken(models.Model):
    """Token for agent authentication — scoped to a workspace."""

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=_generate_workspace_token,
    )
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="tokens"
    )
    label = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label or 'token'} ({self.workspace.name})"


class WorkspaceMember(models.Model):
    """Human user membership in a workspace."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "user")

    def __str__(self):
        return f"{self.user} in {self.workspace} ({self.role})"


class AgentProfile(models.Model):
    """Per-agent display settings (icon, label) that persist across
    WebSocket reconnects and container restarts. The in-memory registry
    reads this at agent-join time and falls back to the transient fields
    the agent registered with when there's no profile yet."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="agent_profiles"
    )
    name = models.CharField(max_length=150, db_index=True)
    icon_emoji = models.CharField(max_length=16, blank=True, default="")
    icon_image = models.CharField(max_length=500, blank=True, default="")
    icon_text = models.CharField(max_length=16, blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")
    # Last-known caduceus-reported health — persisted so the Agents tab
    # + sidebar pills survive container restarts without agents having
    # to re-POST their diagnosis. Free-form status string per mamba's
    # taxonomy-extension model; reason capped at 200 chars.
    health_status = models.CharField(max_length=32, blank=True, default="")
    health_reason = models.CharField(max_length=200, blank=True, default="")
    health_source = models.CharField(max_length=64, blank=True, default="")
    health_ts = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}@{self.workspace.name}"


class Channel(models.Model):
    """A channel within a workspace — like a Slack channel."""

    KIND_GROUP = "group"
    KIND_DM = "dm"
    KIND_CHOICES = [
        (KIND_GROUP, "Group"),
        (KIND_DM, "Direct Message"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="channels"
    )
    name = models.CharField(max_length=100)  # e.g. "#general"
    description = models.TextField(blank=True, default="")
    kind = models.CharField(
        max_length=8,
        choices=KIND_CHOICES,
        default=KIND_GROUP,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.workspace.name})"

    def clean(self):
        """Reject ``dm:`` prefix on non-DM channels (spec v3 §9 Q5).

        The ``dm:`` namespace is reserved for ``kind="dm"`` channels so
        that group channels can never collide with the canonical DM
        channel-name format ``dm:<a>|<b>`` described in spec §2.3.
        """
        super().clean()
        if self.kind == self.KIND_GROUP and self.name.startswith("dm:"):
            raise ValidationError(
                {
                    "name": (
                        "Channel names starting with 'dm:' are reserved "
                        "for direct-message channels (kind='dm')."
                    )
                }
            )


class DMParticipant(models.Model):
    """Participant row for a direct-message channel (spec v3 §2.2).

    Unified on :class:`WorkspaceMember` — ``WorkspaceMember`` already
    models both humans (real Django ``User``) and agents (synthetic
    ``agent-<name>`` users created by ``hub/views/auth.py``). The
    ``principal_type`` column is a display discriminator only; identity
    resolution goes through the ``member`` FK. The denormalized
    ``identity_name`` column is the hot-path lookup key used by the
    ``chat_message`` ACL filter (PR 2) to skip the FK→User join.
    """

    PRINCIPAL_AGENT = "agent"
    PRINCIPAL_HUMAN = "human"
    PRINCIPAL_CHOICES = [
        (PRINCIPAL_AGENT, "Agent"),
        (PRINCIPAL_HUMAN, "Human"),
    ]

    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="dm_participants",
    )
    member = models.ForeignKey(
        WorkspaceMember,
        on_delete=models.CASCADE,
        related_name="dm_memberships",
    )
    principal_type = models.CharField(max_length=8, choices=PRINCIPAL_CHOICES)
    identity_name = models.CharField(max_length=150, db_index=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("channel", "member")]
        indexes = [
            models.Index(fields=["identity_name", "channel"]),
            models.Index(fields=["member"]),
        ]

    def __str__(self):
        return f"{self.identity_name} in {self.channel.name}"


class Message(models.Model):
    """A message in a channel."""

    SENDER_TYPE_CHOICES = [
        ("agent", "Agent"),
        ("human", "Human"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="messages"
    )
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.CharField(max_length=100)
    sender_type = models.CharField(
        max_length=10, choices=SENDER_TYPE_CHOICES, default="human"
    )
    content = models.TextField()
    ts = models.DateTimeField(auto_now_add=True)
    edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["ts"]
        indexes = [
            models.Index(fields=["channel", "ts"]),
            models.Index(fields=["workspace", "ts"]),
        ]

    def __str__(self):
        return f"{self.sender} in {self.channel.name}: {self.content[:50]}"


class MessageReaction(models.Model):
    """An emoji reaction on a message."""

    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="reactions"
    )
    emoji = models.CharField(max_length=32)
    reactor = models.CharField(max_length=100)  # username or agent name
    reactor_type = models.CharField(max_length=10, default="human")
    ts = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "emoji", "reactor")
        indexes = [models.Index(fields=["message", "emoji"])]

    def __str__(self):
        return f"{self.reactor} {self.emoji} on msg#{self.message_id}"


class MessageThread(models.Model):
    """Thread association — a message is a reply to another message."""

    parent = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="thread_replies"
    )
    reply = models.OneToOneField(
        Message, on_delete=models.CASCADE, related_name="thread_parent"
    )
    ts = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"reply#{self.reply_id} → parent#{self.parent_id}"


class PinnedAgent(models.Model):
    """An agent pinned to a workspace so it always appears in the dashboard,
    even when offline or not in the live registry."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="pinned_agents"
    )
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=100, blank=True, default="")
    machine = models.CharField(max_length=200, blank=True, default="")
    icon_emoji = models.CharField(max_length=16, blank=True, default="")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        return f"pin:{self.name}@{self.workspace.name}"


class ContainerAgent(models.Model):
    """Central registry of scitex-agent-container processes across the fleet.

    Distinct from the in-memory WebSocket presence registry: this tracks the
    container/process state (yaml path, machine, tmux-ish session info,
    restart history) so fleet-wide visibility and cross-machine management
    are possible without relying on local ``~/.scitex/agent-container/registry/``.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        STOPPED = "stopped", "Stopped"
        ERROR = "error", "Error"

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="container_agents"
    )
    name = models.CharField(max_length=200, unique=True, db_index=True)
    machine = models.CharField(max_length=200, db_index=True)
    yaml_path = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RUNNING
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["machine", "name"]
        indexes = [
            models.Index(fields=["workspace", "machine"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"container:{self.name}@{self.machine} ({self.status})"


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
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "workspace"]),
        ]

    def __str__(self):
        return f"push:{self.user}@{self.endpoint[:40]}"


class WorkspaceInvitation(models.Model):
    """Email invitation to join a workspace."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    token = models.CharField(
        max_length=64, unique=True, default=_generate_workspace_token
    )
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    accepted = models.BooleanField(default=False)

    class Meta:
        unique_together = ("workspace", "email")

    def __str__(self):
        return f"Invite {self.email} to {self.workspace.name}"
