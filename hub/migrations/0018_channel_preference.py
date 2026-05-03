"""Add ChannelPreference model for per-user starred/muted/hidden/notification prefs (todo#391)."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0017_message_soft_delete"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChannelPreference",
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
                ("is_starred", models.BooleanField(default=False)),
                ("is_muted", models.BooleanField(default=False)),
                ("is_hidden", models.BooleanField(default=False)),
                (
                    "notification_level",
                    models.CharField(
                        choices=[
                            ("all", "All messages"),
                            ("mentions", "Mentions only"),
                            ("nothing", "Nothing"),
                        ],
                        default="all",
                        max_length=10,
                    ),
                ),
                (
                    "channel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_preferences",
                        to="hub.channel",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="channel_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("user", "channel")},
            },
        ),
    ]
