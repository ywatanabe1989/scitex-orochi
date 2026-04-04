"""Management command to add a user to a workspace."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from hub.models import Workspace, WorkspaceMember

User = get_user_model()


class Command(BaseCommand):
    help = "Add a user to a workspace"

    def add_arguments(self, parser):
        parser.add_argument("workspace", help="Workspace name (slug)")
        parser.add_argument("username", help="Username to add")
        parser.add_argument(
            "--role",
            choices=["admin", "member"],
            default="member",
            help="Role in workspace (default: member)",
        )

    def handle(self, *args, **options):
        try:
            workspace = Workspace.objects.get(name=options["workspace"])
        except Workspace.DoesNotExist:
            raise CommandError(f"Workspace '{options['workspace']}' does not exist")

        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"User '{options['username']}' does not exist")

        member, created = WorkspaceMember.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": options["role"]},
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Added {user.username} to {workspace.name} as {options['role']}"
                )
            )
        else:
            self.stdout.write(
                f"{user.username} is already a member of {workspace.name} ({member.role})"
            )
