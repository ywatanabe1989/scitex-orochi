"""Messaging models — channels, memberships, messages, reactions, threads."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from ._helpers import normalize_channel_name
from ._identity import Workspace, WorkspaceMember


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
    icon_emoji = models.CharField(max_length=16, blank=True, default="")
    icon_image = models.CharField(max_length=500, blank=True, default="")
    icon_text = models.CharField(max_length=16, blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "hub"
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

    def save(self, *args, **kwargs):
        if self.kind == self.KIND_GROUP and self.name:
            self.name = normalize_channel_name(self.name)
        super().save(*args, **kwargs)


class ChannelPreference(models.Model):
    """Per-user channel preferences — starred, muted, notifications (todo#391).

    Mirrors Slack's per-member channel settings:
    - starred: appears in "Starred" section at the top of the sidebar
    - muted: no notification badge, messages still visible
    - notification_level: all / mentions / nothing
    - hidden: channel removed from sidebar (opt-in to re-add)
    """

    NOTIF_ALL = "all"
    NOTIF_MENTIONS = "mentions"
    NOTIF_NOTHING = "nothing"
    NOTIF_CHOICES = [
        (NOTIF_ALL, "All messages"),
        (NOTIF_MENTIONS, "Mentions only"),
        (NOTIF_NOTHING, "Nothing"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_preferences",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="user_preferences",
    )
    is_starred = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    notification_level = models.CharField(
        max_length=10,
        choices=NOTIF_CHOICES,
        default=NOTIF_ALL,
    )
    sort_order = models.IntegerField(
        default=0,
        db_index=True,
        help_text="Manual sort order within sidebar section (drag-and-drop)",
    )

    class Meta:
        app_label = "hub"
        unique_together = ("user", "channel")

    def __str__(self):
        return f"{self.user.username} → {self.channel.name}"


class ChannelMembership(models.Model):
    """Explicit per-member channel permissions (todo#407).

    Stores the access level for a given (user, channel) pair.
    Default is read-write — only entries that deviate from the default
    need explicit rows. All agents and humans can post by default;
    admins can create read-only rows to restrict specific members.

    This model serves humans and agent-synthetic-users equally (spec §2.1).
    """

    PERM_READ_WRITE = "read-write"
    PERM_READ_ONLY = "read-only"
    PERM_WRITE_ONLY = "write-only"
    PERM_CHOICES = [
        (PERM_READ_WRITE, "Read & Write"),
        (PERM_READ_ONLY, "Read Only"),
        (PERM_WRITE_ONLY, "Write Only"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_memberships",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    permission = models.CharField(
        max_length=12,
        choices=PERM_CHOICES,
        default=PERM_READ_WRITE,
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "hub"
        unique_together = ("user", "channel")

    def __str__(self):
        return f"{self.user.username} → {self.channel.name} ({self.permission})"


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
        app_label = "hub"
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
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "hub"
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
        app_label = "hub"
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

    class Meta:
        app_label = "hub"

    def __str__(self):
        return f"reply#{self.reply_id} → parent#{self.parent_id}"
