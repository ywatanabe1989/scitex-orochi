"""Identity / auth models — workspaces, members, tokens, invites, profiles."""

from django.conf import settings
from django.db import models

from ._helpers import _generate_workspace_token


class Workspace(models.Model):
    """A workspace groups channels, agents, and members — like a Slack workspace."""

    name = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=10, blank=True, default="")  # emoji
    # Uploaded image URL. Cascade for rendering: icon_image > icon (emoji)
    # > first-letter coloured square. Parallel to UserProfile.icon_image /
    # AgentProfile.icon_image so all three entity types share the same
    # image-upload contract.
    icon_image = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "hub"
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

    class Meta:
        app_label = "hub"

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
        app_label = "hub"
        unique_together = ("workspace", "user")

    def __str__(self):
        return f"{self.user} in {self.workspace} ({self.role})"


class InviteRequest(models.Model):
    """External user invite request submitted from the public landing
    page. Queues a pending row; an admin reviews and approves (which
    creates a WorkspaceInvitation) or denies. TODO.md Real-world
    applicability "External User ... invite users in a secured,
    permission-controlled manner" (Option B). Replaces the Option A
    mailto CTA with an in-app form so requests are tracked in the DB
    instead of an inbox.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_DENIED = "denied"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DENIED, "Denied"),
    ]

    email = models.EmailField()
    name = models.CharField(max_length=150, blank=True, default="")
    affiliation = models.CharField(max_length=200, blank=True, default="")
    message = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    requested_workspace = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invite_requests_reviewed",
    )
    resulting_invite = models.ForeignKey(
        "WorkspaceInvitation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="from_request",
    )

    class Meta:
        app_label = "hub"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email} ({self.status})"


class UserProfile(models.Model):
    """Per-user display settings (icon, colour) for logged-in humans.

    Mirrors :class:`AgentProfile` but keyed on the Django user, not on a
    workspace+name pair: a human's avatar is a personal preference that
    follows them across every workspace they belong to.

    The cascade used by the frontend is the same as for agents:
    ``icon_image`` > ``icon_emoji`` > ``icon_text`` > default person
    glyph. ``color`` is an optional override for the hash-based fallback.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    icon_image = models.CharField(max_length=500, blank=True, default="")
    icon_emoji = models.CharField(max_length=16, blank=True, default="")
    icon_text = models.CharField(max_length=16, blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hub"

    def __str__(self):
        return f"profile({self.user})"


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
    # todo#305 Task 7 (lead msg#15548): persistent per-agent hidden flag
    # toggled by the 👁 eye icon on the agent card. Mirrors
    # ChannelPreference.is_hidden — same semantics (row dropped from
    # sidebar + topology; visible flag restorable via the eye toggle on
    # any ghost/pool representation).
    is_hidden = models.BooleanField(default=False)
    # Last-known caduceus-reported health — persisted so the Agents tab
    # + sidebar pills survive container restarts without agents having
    # to re-POST their diagnosis. Free-form status string per mamba's
    # taxonomy-extension orochi_model; reason capped at 200 chars.
    health_status = models.CharField(max_length=32, blank=True, default="")
    health_reason = models.CharField(max_length=200, blank=True, default="")
    health_source = models.CharField(max_length=64, blank=True, default="")
    health_ts = models.DateTimeField(null=True, blank=True)
    # msg#17078 lane A — DB-persisted auto-dispatch cooldown timestamp.
    # Hydrates the in-memory ``_agents[name]["auto_dispatch_last_fire_ts"]``
    # on first lookup so the 15min cooldown survives hub restarts. Before
    # this field the cooldown lived only in-memory and a hub restart
    # re-enabled auto-dispatches ~1-5min after the previous fire even
    # though the DM text advertised 15min.
    last_auto_dispatch_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hub"
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}@{self.workspace.name}"


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
        app_label = "hub"
        unique_together = ("workspace", "email")

    def __str__(self):
        return f"Invite {self.email} to {self.workspace.name}"
