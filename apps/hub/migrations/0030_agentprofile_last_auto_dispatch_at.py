# Generated for msg#17078 lane A — 2026-04-22.
#
# Adds AgentProfile.last_auto_dispatch_at so the auto-dispatch cooldown
# survives hub restarts. Before this migration the cooldown lived only
# in the in-memory ``hub.registry._agents[<name>]`` dict and was lost
# every time the hub process restarted — letting the streak + fire
# state machine re-fire a DM within ~1-5min of the previous one even
# though the DM text advertised a 15min cooldown.
#
# Default ``null`` keeps every existing agent eligible to fire on
# rollout (no retro-active cooldown).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0029_channelmembership_can_read_can_write"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentprofile",
            name="last_auto_dispatch_at",
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
