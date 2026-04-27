"""Seed the synthetic ``agent-worker-progress`` user + ChannelMemberships.

Implements the data-plane side of todo#272 (sac-managed Claude agent
re-spec, `#heads` msg#15416 — replaces closed PR #300 which shipped a
Python daemon). Idempotent: running multiple times is a no-op.

The synthetic ``agent-worker-progress`` user is granted the following
``ChannelMembership`` bits (lead msg#16884 bit-split):

  - ``#progress``  → ``can_read=True, can_write=True``  (read-write)
  - ``#heads``     → ``can_read=True, can_write=True``  (read-write)
  - ``#ywatanabe`` → ``can_read=False, can_write=True`` (write-only digest
    target — posts summaries but must NOT consume the firehose back,
    msg#16880 / msg#16884)
  - every ``#proj-*`` channel that exists in the DB **at seed time** →
    ``can_read=True, can_write=True``  (read-write)

The ``#proj-*`` set is enumerated at orochi_runtime (not hardcoded) so new
orochi_project channels are picked up without code changes — just re-run the
seed after creating a new ``#proj-foo``.

``#agent`` was abolished 2026-04-21 (PR #293 follow-up) and the
server-side blocklist in ``ABOLISHED_AGENT_CHANNELS`` rejects it; we
never subscribe to it here either.

Usage:
    python manage.py seed_worker_progress [--workspace <name>]
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from hub.consumers._helpers import ABOLISHED_AGENT_CHANNELS
from hub.models import Channel, ChannelMembership, Workspace, WorkspaceMember

User = get_user_model()

AGENT_NAME = "worker-progress"
AGENT_USERNAME = f"agent-{AGENT_NAME}"

# Base channels are always seeded (created if missing).
BASE_CHANNELS = ("#progress", "#heads", "#ywatanabe")

# Per-channel bit overrides. Any channel not listed gets the default
# full read-write (True, True). ``#ywatanabe`` is seeded write-only
# (msg#16880 / msg#16884 bit-split) so the worker can publish digest
# summaries into the channel without consuming the firehose back.
CHANNEL_BITS: dict[str, tuple[bool, bool]] = {
    "#ywatanabe": (False, True),  # (can_read, can_write)
}

# Prefix for per-orochi_project channels. All existing channels whose name
# starts with this prefix are added to the worker's membership set.
PROJ_CHANNEL_PREFIX = "#proj-"


class Command(BaseCommand):
    help = (
        "Seed agent-worker-progress synthetic user + read-write "
        "memberships for #progress, #heads, #ywatanabe, and all "
        "#proj-* channels that currently exist in the workspace "
        "(todo#272). Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            default="default",
            help="Workspace slug to seed into (default: default)",
        )

    def handle(self, *args, **options):
        ws_name = options["workspace"]
        try:
            workspace = Workspace.objects.get(name=ws_name)
        except Workspace.DoesNotExist as exc:
            raise CommandError(f"Workspace '{ws_name}' does not exist") from exc

        user, user_created = User.objects.get_or_create(
            username=AGENT_USERNAME,
            defaults={
                "email": f"{AGENT_USERNAME}@agents.orochi.local",
                "is_active": True,
                "is_staff": False,
            },
        )
        if user_created:
            self.stdout.write(self.style.SUCCESS(f"created user: {AGENT_USERNAME}"))
        else:
            self.stdout.write(f"user exists: {AGENT_USERNAME}")

        _, member_created = WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": "member"},
        )
        if member_created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"added {AGENT_USERNAME} to workspace '{ws_name}'"
                )
            )
        else:
            self.stdout.write(
                f"{AGENT_USERNAME} already in workspace '{ws_name}'"
            )

        channels = self._collect_channels(workspace)

        created, existed, skipped = 0, 0, 0
        for name in channels:
            if name in ABOLISHED_AGENT_CHANNELS:
                self.stdout.write(
                    self.style.WARNING(f"skipping abolished channel: {name}")
                )
                skipped += 1
                continue

            # Base channels are created if missing; orochi_project channels
            # are only enumerated if they already exist, so they will
            # always resolve to an existing row.
            channel, _ = Channel.objects.get_or_create(
                workspace=workspace,
                name=name,
                defaults={"kind": Channel.KIND_GROUP},
            )
            want_read, want_write = CHANNEL_BITS.get(name, (True, True))
            label = self._bits_label(want_read, want_write)
            membership, was_created = ChannelMembership.objects.get_or_create(
                user=user,
                channel=channel,
                defaults={
                    "can_read": want_read,
                    "can_write": want_write,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  + membership: {name} ({label})")
                )
            else:
                existed += 1
                if (
                    membership.can_read != want_read
                    or membership.can_write != want_write
                ):
                    prev_label = self._bits_label(
                        membership.can_read, membership.can_write
                    )
                    membership.can_read = want_read
                    membership.can_write = want_write
                    membership.save(update_fields=["can_read", "can_write"])
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ~ updated {name}: {prev_label} → {label}"
                        )
                    )
                else:
                    self.stdout.write(f"  = membership exists: {name} ({label})")

        self.stdout.write(
            self.style.SUCCESS(
                f"done: {created} created, {existed} existed, {skipped} skipped."
            )
        )

    @staticmethod
    def _bits_label(can_read: bool, can_write: bool) -> str:
        """Human-readable label for a ``(can_read, can_write)`` pair."""
        if can_read and can_write:
            return "read-write"
        if can_read and not can_write:
            return "read-only"
        if (not can_read) and can_write:
            return "write-only"
        return "locked-out"

    def _collect_channels(self, workspace: Workspace) -> list[str]:
        """Return the ordered channel-name set to seed.

        Base channels first (so they always land, even in a pristine
        DB), then every ``#proj-*`` channel that already exists in
        the workspace. De-duplicated while preserving order.
        """
        seen: set[str] = set()
        ordered: list[str] = []

        for name in BASE_CHANNELS:
            if name not in seen:
                seen.add(name)
                ordered.append(name)

        proj_names = (
            Channel.objects.filter(
                workspace=workspace,
                kind=Channel.KIND_GROUP,
                name__startswith=PROJ_CHANNEL_PREFIX,
            )
            .order_by("name")
            .values_list("name", flat=True)
        )
        for name in proj_names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)

        return ordered
