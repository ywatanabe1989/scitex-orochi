"""Core models for the Orochi communication hub."""

import secrets

from django.conf import settings
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

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="channels"
    )
    name = models.CharField(max_length=100)  # e.g. "#general"
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.workspace.name})"


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
