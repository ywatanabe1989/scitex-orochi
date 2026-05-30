"""Add icon (emoji) field to Workspace model."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hub", "0003_message_sender_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="icon",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
    ]
