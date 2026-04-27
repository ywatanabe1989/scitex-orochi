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
    """Explicit per-member channel permissions (todo#407, lead msg#16884).

    Stores the access level for a given (user, channel) pair via two
    independent boolean bits — ``can_read`` and ``can_write`` — so the
    four combinations (RW / R-only / W-only / no-op) are representable
    without juggling an enum string.

    The legacy ``permission`` CharField is preserved for one release
    cycle (data migration 0029 backfills it in both directions); new
    consumer code should rely exclusively on the bits. The field will be
    dropped in a follow-up migration once every deploy has rolled past
    0029.

    Default is ``can_read=True``, ``can_write=True`` (full read-write,
    matching the pre-bit-split default) so rows that exist only to
    track presence keep behaving identically. Admins can flip either
    bit False to restrict a specific member (e.g. write-only digest
    targets: ``can_read=False, can_write=True``).

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
    # Deprecated — kept for one release cycle (lead msg#16884). Consumer
    # code must use ``can_read`` / ``can_write`` instead. The
    # post_save/migration bridge in 0029 keeps the string in sync with the
    # bits so admin UIs / legacy callers that still read the enum see the
    # right value, and a future migration will drop the column.
    permission = models.CharField(
        max_length=12,
        choices=PERM_CHOICES,
        default=PERM_READ_WRITE,
    )
    can_read = models.BooleanField(
        default=True,
        help_text=(
            "Whether the member receives chat/reaction/edit/delete "
            "fan-out for this channel. False = write-only (no read)."
        ),
    )
    can_write = models.BooleanField(
        default=True,
        help_text=(
            "Whether the member is allowed to post to this channel. "
            "False = read-only."
        ),
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "hub"
        unique_together = ("user", "channel")

    def __str__(self):
        bits = f"r={int(self.can_read)},w={int(self.can_write)}"
        return f"{self.user.username} → {self.channel.name} ({bits})"

    # -- bit <-> legacy-string bridge (msg#16884, deprecated string) -----

    @staticmethod
    def perm_to_bits(permission: str) -> tuple[bool, bool]:
        """Map the legacy ``permission`` enum to ``(can_read, can_write)``.

        Unknown values fall through to ``(True, True)`` — the historical
        default — so garbage data never locks a member out silently.
        """
        if permission == ChannelMembership.PERM_READ_ONLY:
            return (True, False)
        if permission == ChannelMembership.PERM_WRITE_ONLY:
            return (False, True)
        return (True, True)

    @staticmethod
    def bits_to_perm(can_read: bool, can_write: bool) -> str:
        """Map ``(can_read, can_write)`` back to the legacy enum.

        The ``(False, False)`` case (admin lockout) has no legacy enum —
        we map it to ``read-only`` (the most restrictive value the old
        enum could express) so legacy readers continue to treat the row
        as no-write. Callers that care about lockout must check the
        bits directly.
        """
        if can_read and can_write:
            return ChannelMembership.PERM_READ_WRITE
        if can_read and not can_write:
            return ChannelMembership.PERM_READ_ONLY
        if (not can_read) and can_write:
            return ChannelMembership.PERM_WRITE_ONLY
        # (False, False) — admin lockout, no legacy enum for it.
        return ChannelMembership.PERM_READ_ONLY

    def __init__(self, *args, **kwargs):
        """One-release-cycle deprecation bridge for the ``permission`` enum.

        Legacy callers that still pass ``permission=...`` at construct
        time (without bits) deserve to keep working — the test suite in
        particular leans on this shape. When a caller supplies
        ``permission`` but NOT the bits, derive the bits from the enum
        so both views stay consistent. When bits are explicitly set they
        win (they are the new source of truth).
        """
        has_perm = "permission" in kwargs
        has_read = "can_read" in kwargs
        has_write = "can_write" in kwargs
        super().__init__(*args, **kwargs)
        if has_perm and not (has_read or has_write):
            bits = ChannelMembership.perm_to_bits(self.permission)
            self.can_read, self.can_write = bits

    def save(self, *args, **kwargs):
        """Keep ``permission`` in sync with the bits on every write.

        Bits are the authoritative source. ``__init__`` already converts
        a legacy ``permission=...`` construct into the matching bits, so
        by save-time the bits reflect the caller's intent regardless of
        which surface they used. We then normalize the string from the
        bits so the deprecated column stays truthful for one-release
        readers.

        When ``save(update_fields=...)`` is used (Django's partial-update
        path — ``update_or_create`` and ``save(update_fields=[...])``),
        we must include ``permission`` in the update-fields set so the
        normalized string actually hits the DB. Without this the bridge
        silently no-ops on partial writes.
        """
        self.permission = self.bits_to_perm(self.can_read, self.can_write)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            fields = set(update_fields)
            if "can_read" in fields or "can_write" in fields:
                fields.add("permission")
                kwargs["update_fields"] = list(fields)
        super().save(*args, **kwargs)


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
