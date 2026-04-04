"""Management command to create a default workspace with token and #general channel."""

from django.core.management.base import BaseCommand

from hub.models import Channel, Workspace, WorkspaceToken


class Command(BaseCommand):
    help = "Create a default workspace with token and #general channel"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name", default="default", help="Workspace name (default: 'default')"
        )

    def handle(self, *args, **options):
        name = options["name"]
        workspace, created = Workspace.objects.get_or_create(
            name=name, defaults={"description": f"Default workspace '{name}'"}
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created workspace: {name}"))
        else:
            self.stdout.write(f"Workspace '{name}' already exists")

        # Ensure #general channel
        channel, ch_created = Channel.objects.get_or_create(
            workspace=workspace, name="#general"
        )
        if ch_created:
            self.stdout.write(self.style.SUCCESS("Created channel: #general"))

        # Ensure at least one token
        token = WorkspaceToken.objects.filter(workspace=workspace).first()
        if not token:
            token = WorkspaceToken.objects.create(workspace=workspace, label="default")
            self.stdout.write(
                self.style.SUCCESS(f"Created workspace token: {token.token}")
            )
        else:
            self.stdout.write(f"Existing token: {token.token}")
