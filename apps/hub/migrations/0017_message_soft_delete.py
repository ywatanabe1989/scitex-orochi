"""Add deleted_at soft-delete field to Message (todo#403)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0016_scheduled_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
