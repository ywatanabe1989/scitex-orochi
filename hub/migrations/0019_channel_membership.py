"""Add ChannelMembership model for per-member read-only/read-write permissions (todo#407)."""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0018_channel_preference"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelMembership",
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
                (
                    "permission",
                    models.CharField(
                        choices=[
                            ("read-write", "Read & Write"),
                            ("read-only", "Read Only"),
                        ],
                        default="read-write",
                        max_length=12,
                    ),
                ),
                (
                    "joined_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="hub.channel",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="channel_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("user", "channel")},
            },
        ),
    ]
