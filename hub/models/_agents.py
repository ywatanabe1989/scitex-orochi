"""Agent presence / scheduling models — pinned agents, container registry,
scheduled actions, and user-defined agent groups."""

from django.contrib.auth.models import User
from django.db import models

from ._identity import Workspace


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
        app_label = "hub"
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        return f"pin:{self.name}@{self.workspace.name}"


class AgentGroup(models.Model):
    """User-defined named group of agents for @mention expansion (todo#428).

    Hardcoded built-in groups (``heads``, ``mambas``, ``all``, …) are
    seeded as rows here on workspace creation so all expansion logic
    can go through a single DB query path instead of the legacy
    ``_GROUP_PATTERNS`` dict.

    ``name`` is the mention key — e.g. ``@paper-team`` uses ``name="paper-team"``.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="agent_groups"
    )
    name = models.CharField(
        max_length=64,
        help_text="Mention key used in @<name> tokens.",
    )
    display_name = models.CharField(max_length=128, blank=True, default="")
    description = models.TextField(blank=True, default="")
    # For built-in groups (heads, mambas, …) members is not used —
    # expansion falls back to the predicate in mentions.py. For custom
    # groups, members is the authoritative membership list.
    members = models.ManyToManyField(
        User,
        blank=True,
        related_name="agent_groups",
    )
    is_builtin = models.BooleanField(
        default=False,
        help_text="True for system-seeded groups (heads, mambas, …). "
        "Builtin groups cannot be deleted via the API.",
    )
    owner = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_agent_groups",
        help_text="Creator; null for system-seeded groups.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hub"
        unique_together = ("workspace", "name")
        ordering = ["name"]

    def __str__(self):
        tag = "builtin" if self.is_builtin else "custom"
        return f"group:{self.name}@{self.workspace.name} ({tag})"


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
        app_label = "hub"
        ordering = ["machine", "name"]
        indexes = [
            models.Index(fields=["workspace", "machine"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"container:{self.name}@{self.machine} ({self.status})"


class ScheduledAction(models.Model):
    """A time-based action reservation for an agent (issue #95).

    When ``run_at`` is in the past and status=='pending', the hub scheduler
    posts a task message to ``agent`` in ``channel`` and marks it as fired.
    """

    STATUS_PENDING = "pending"
    STATUS_FIRED = "fired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_FIRED, "Fired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="scheduled_actions"
    )
    agent = models.CharField(max_length=128, help_text="Target agent name")
    task = models.TextField(help_text="Task description to deliver to the agent")
    channel = models.CharField(
        max_length=128, default="#general", help_text="Channel to deliver the task in"
    )
    run_at = models.DateTimeField(help_text="UTC datetime when the action should fire")
    cron = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional cron expression for recurring actions (blank = one-shot)",
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    created_by = models.CharField(max_length=128, default="", help_text="Creator name")
    created_at = models.DateTimeField(auto_now_add=True)
    fired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "hub"
        ordering = ["run_at"]

    def __str__(self):
        return f"ScheduledAction({self.agent}, {self.run_at}, {self.status})"


class AgentSnapshot(models.Model):
    """Per-agent state snapshot for cross-host handover (FR-A).

    A lead-class agent POSTs its memory + recent transcript on graceful
    stop (and periodically) to ``/api/agents/<name>/snapshot``; a fresh
    instance booting on another host GETs ``/snapshot/latest`` and
    hydrates its workspace before launching Claude. One row per
    (workspace, agent_name) — newest write wins.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="agent_snapshots"
    )
    agent_name = models.CharField(max_length=200, db_index=True)
    payload = models.JSONField(default=dict)
    owner_host = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "hub"
        unique_together = ("workspace", "agent_name")
        ordering = ["agent_name"]

    def __str__(self):
        return f"snapshot:{self.agent_name}@{self.owner_host}"


class AgentSession(models.Model):
    """Active agent WebSocket session, keyed by instance UUID (FR-E).

    Each agent generates ``instance_uuid = uuid4()`` on start and sends
    it to the hub on WS connect. The hub persists the (agent_name,
    instance_uuid) pair plus host/PID metadata so:

      - cardinality enforcement (FR-C) can detect "same name, different
        UUID, both active" rogue-instance situations,
      - outgoing messages can be stamped with
        ``agent_id = "<name>:<uuid>"`` for end-to-end provenance,
      - operators can resolve a short ``name:uuid_prefix`` back to a
        host/PID pair via ``/api/agents/<name>/<uuid>/meta``.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="agent_sessions"
    )
    agent_name = models.CharField(max_length=200, db_index=True)
    instance_uuid = models.CharField(max_length=64, unique=True, db_index=True)
    hostname = models.CharField(max_length=200, blank=True, default="")
    pid = models.IntegerField(null=True, blank=True)
    ws_session_id = models.CharField(max_length=200, blank=True, default="")
    cardinality_enforced = models.BooleanField(default=False)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat = models.DateTimeField(auto_now=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "hub"
        ordering = ["agent_name", "-connected_at"]
        indexes = [
            models.Index(fields=["agent_name", "disconnected_at"]),
        ]

    def __str__(self):
        short = self.instance_uuid[:8] if self.instance_uuid else "?"
        return f"session:{self.agent_name}:{short}@{self.hostname}"
