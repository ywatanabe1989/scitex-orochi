# Generated for #123 reactions and #114 threading

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0004_workspace_icon"),
    ]

    operations = [
        migrations.CreateModel(
            name="MessageReaction",
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
                ("emoji", models.CharField(max_length=32)),
                ("reactor", models.CharField(max_length=100)),
                ("reactor_type", models.CharField(default="human", max_length=10)),
                ("ts", models.DateTimeField(auto_now_add=True)),
                (
                    "message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reactions",
                        to="hub.message",
                    ),
                ),
            ],
            options={
                "unique_together": {("message", "emoji", "reactor")},
                "indexes": [
                    models.Index(
                        fields=["message", "emoji"],
                        name="hub_msgreac_message_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="MessageThread",
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
                ("ts", models.DateTimeField(auto_now_add=True)),
                (
                    "parent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="thread_replies",
                        to="hub.message",
                    ),
                ),
                (
                    "reply",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="thread_parent",
                        to="hub.message",
                    ),
                ),
            ],
        ),
    ]
