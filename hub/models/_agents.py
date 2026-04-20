"""Agent presence / scheduling models — pinned agents, container registry,
scheduled actions."""

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
