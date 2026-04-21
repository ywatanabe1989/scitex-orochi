# Generated for todo#305 Task 7 (lead msg#15548) — 2026-04-21.
#
# Adds AgentProfile.is_hidden so the 👁 eye toggle on agent cards
# (sidebar + topology) has a persistent per-agent hidden flag,
# mirroring ChannelPreference.is_hidden. Default False keeps every
# existing agent visible on rollout.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0026_workspace_icon_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentprofile",
            name="is_hidden",
            field=models.BooleanField(default=False),
        ),
    ]
