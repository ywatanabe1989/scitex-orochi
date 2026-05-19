from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0031_channel_is_archived"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacetoken",
            name="agent_name",
            field=models.CharField(
                blank=True,
                default="",
                max_length=150,
                help_text=(
                    "scitex-orochi#182 — when non-empty, the hub uses this name "
                    "as the agent identity at WS connect instead of the URL "
                    "?agent= query param. Prevents cross-agent attribution drift "
                    "when co-resident agents share a wrong env var after a reboot."
                ),
            ),
        ),
    ]
