# Generated for todo#90 — CRUD tracked GitHub repos in Releases tab.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def seed_default_repos(apps, schema_editor):
    """Seed each existing workspace with the legacy hard-coded repo list so
    the Releases tab is non-empty immediately after migration."""
    Workspace = apps.get_model("hub", "Workspace")
    TrackedRepo = apps.get_model("hub", "TrackedRepo")
    defaults = [
        ("ywatanabe1989", "scitex-orochi"),
        ("ywatanabe1989", "scitex-cloud"),
        ("ywatanabe1989", "scitex-python"),
        ("ywatanabe1989", "scitex"),
        ("ywatanabe1989", "scitex-agent-container"),
    ]
    for ws in Workspace.objects.all():
        for owner, repo in defaults:
            TrackedRepo.objects.get_or_create(
                workspace=ws, owner=owner, repo=repo, defaults={"label": repo}
            )


def unseed(apps, schema_editor):
    # No-op: removing rows here would also drop any user-added repos.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("hub", "0021_userprofile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TrackedRepo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("owner", models.CharField(max_length=100)),
                ("repo", models.CharField(max_length=100)),
                ("label", models.CharField(blank=True, default="", max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "added_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tracked_repos",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracked_repos",
                        to="hub.workspace",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "unique_together": {("workspace", "owner", "repo")},
            },
        ),
        migrations.RunPython(seed_default_repos, reverse_code=unseed),
    ]
