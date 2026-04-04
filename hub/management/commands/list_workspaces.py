"""Management command to list all workspaces."""

from django.core.management.base import BaseCommand

from hub.models import Channel, Workspace, WorkspaceMember, WorkspaceToken


class Command(BaseCommand):
    help = "List all workspaces with their channels and token counts"

    def add_arguments(self, parser):
        parser.add_argument(
            "--json", action="store_true", dest="as_json", help="Output as JSON"
        )

    def handle(self, *args, **options):
        import json

        workspaces = Workspace.objects.all()

        if options["as_json"]:
            data = []
            for ws in workspaces:
                data.append(
                    {
                        "name": ws.name,
                        "description": ws.description,
                        "channels": list(
                            Channel.objects.filter(workspace=ws).values_list(
                                "name", flat=True
                            )
                        ),
                        "tokens": WorkspaceToken.objects.filter(workspace=ws).count(),
                        "members": WorkspaceMember.objects.filter(workspace=ws).count(),
                    }
                )
            self.stdout.write(json.dumps(data, indent=2))
            return

        if not workspaces.exists():
            self.stdout.write("No workspaces found.")
            return

        for ws in workspaces:
            channels = Channel.objects.filter(workspace=ws)
            tokens = WorkspaceToken.objects.filter(workspace=ws).count()
            members = WorkspaceMember.objects.filter(workspace=ws).count()
            ch_names = ", ".join(ch.name for ch in channels) or "(none)"
            self.stdout.write(
                self.style.SUCCESS(f"\n  {ws.name}")
                + f"  — {ws.description or '(no description)'}"
            )
            self.stdout.write(f"    Channels: {ch_names}")
            self.stdout.write(f"    Tokens: {tokens}  Members: {members}")
