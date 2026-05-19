from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0030_agentprofile_last_auto_dispatch_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="is_archived",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
