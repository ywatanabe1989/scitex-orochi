"""Seed the synthetic ``agent-worker-progress`` user + ChannelMemberships.

Implements the data-plane side of todo#272. Idempotent: running it
multiple times is a no-op. Mirrors the ``agent-*`` synthetic-user
pattern used by ``hub/consumers/_helpers.py::_persist_agent_subscription``
and the hub auth layer.

Usage:
    python manage.py seed_worker_progress --workspace <workspace-name>

Exits non-zero only if the workspace can't be found. The
``#agent`` channel is explicitly skipped — it was abolished 2026-04-21
(lead directive, PR #293 follow-up) and the server-side blocklist in
``ABOLISHED_AGENT_CHANNELS`` would reject any attempt to add it.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from hub.consumers._helpers import ABOLISHED_AGENT_CHANNELS
from hub.models import Channel, ChannelMembership, Workspace, WorkspaceMember

User = get_user_model()

# Keep in sync with ``scripts/server/worker_progress_pkg/__init__.py``
# (AGENT_NAME, SUBSCRIBE_CHANNELS). Duplicated here so the mgmt
# command doesn't have to import the server-side package.
AGENT_NAME = "worker-progress"
AGENT_USERNAME = f"agent-{AGENT_NAME}"
DEFAULT_CHANNELS = ("#progress", "#heads", "#ywatanabe")


class Command(BaseCommand):
    help = (
        "Seed agent-worker-progress synthetic user + read-write memberships "
        "for #progress, #heads, #ywatanabe (todo#272). Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            default="default",
            help="Workspace slug to seed into (default: default)",
        )
        parser.add_argument(
            "--channels",
            nargs="*",
            default=list(DEFAULT_CHANNELS),
            help=(
                "Channel names to grant read-write to. Defaults to "
                "#progress, #heads, #ywatanabe. ``#agent`` is always "
                "skipped (abolished 2026-04-21)."
            ),
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

        member, member_created = WorkspaceMember.objects.get_or_create(
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

        created, existed, skipped = 0, 0, 0
        for raw in options["channels"]:
            name = raw if raw.startswith(("#", "dm:")) else f"#{raw}"
            if name in ABOLISHED_AGENT_CHANNELS:
                self.stdout.write(
                    self.style.WARNING(f"skipping abolished channel: {name}")
                )
                skipped += 1
                continue
            channel, _ = Channel.objects.get_or_create(
                workspace=workspace,
                name=name,
                defaults={"kind": Channel.KIND_GROUP},
            )
            membership, was_created = ChannelMembership.objects.get_or_create(
                user=user,
                channel=channel,
                defaults={"permission": ChannelMembership.PERM_READ_WRITE},
            )
            if was_created:
                created += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  + membership: {name} (read-write)")
                )
            else:
                existed += 1
                # Ensure permission is read-write even if it was previously
                # demoted; the daemon needs to both read and post digests.
                if membership.permission != ChannelMembership.PERM_READ_WRITE:
                    membership.permission = ChannelMembership.PERM_READ_WRITE
                    membership.save(update_fields=["permission"])
                    self.stdout.write(
                        self.style.WARNING(
                            f"  ~ upgraded to read-write: {name}"
                        )
                    )
                else:
                    self.stdout.write(f"  = membership exists: {name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"done: {created} created, {existed} existed, {skipped} skipped."
            )
        )
