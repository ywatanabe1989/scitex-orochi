"""Add sender_type field to Message model.

Stores whether a message was sent by an 'agent' or 'human' at creation time
so the dashboard does not depend on real-time WebSocket connections.
"""

from django.db import migrations, models


def backfill_sender_type(apps, schema_editor):
    """Heuristic backfill: names containing 'orochi-' or 'head-' are agents."""
    Message = apps.get_model("hub", "Message")
    Message.objects.filter(sender__contains="orochi-").update(sender_type="agent")
    Message.objects.filter(sender__contains="head-").update(sender_type="agent")


class Migration(migrations.Migration):
    dependencies = [
        ("hub", "0002_workspaceinvitation"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="sender_type",
            field=models.CharField(
                choices=[("agent", "Agent"), ("human", "Human")],
                default="human",
                max_length=10,
            ),
        ),
        migrations.RunPython(backfill_sender_type, migrations.RunPython.noop),
    ]
