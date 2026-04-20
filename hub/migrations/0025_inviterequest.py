# Generated for InviteRequest model (external user self-request, Option B)

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hub", "0024_channel_icon_color"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InviteRequest",
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
                ("email", models.EmailField(max_length=254)),
                ("name", models.CharField(blank=True, default="", max_length=150)),
                (
                    "affiliation",
                    models.CharField(blank=True, default="", max_length=200),
                ),
                ("message", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("denied", "Denied"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=10,
                    ),
                ),
                (
                    "requested_workspace",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invite_requests_reviewed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resulting_invite",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="from_request",
                        to="hub.workspaceinvitation",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
