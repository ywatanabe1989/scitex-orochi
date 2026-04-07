"""Management command to create a workspace token for agent authentication."""

from django.core.management.base import BaseCommand, CommandError

from hub.models import Workspace, WorkspaceToken


class Command(BaseCommand):
    help = "Create a workspace token for agent authentication"

    def add_arguments(self, parser):
        parser.add_argument("workspace", help="Workspace name (slug)")
        parser.add_argument("--label", default="", help="Token label (e.g. agent name)")
        parser.add_argument(
            "--json", action="store_true", dest="as_json", help="Output as JSON"
        )

    def handle(self, *args, **options):
        import json

        name = options["workspace"]
        try:
            workspace = Workspace.objects.get(name=name)
        except Workspace.DoesNotExist:
            raise CommandError(f"Workspace '{name}' does not exist")

        token = WorkspaceToken.objects.create(
            workspace=workspace, label=options["label"]
        )

        if options["as_json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "token": token.token,
                        "workspace": workspace.name,
                        "label": token.label,
                    }
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Token: {token.token}"))
            self.stdout.write(f"Workspace: {workspace.name}")
            if token.label:
                self.stdout.write(f"Label: {token.label}")
