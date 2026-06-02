# Generated for channel custom icon + color support

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hub", "0023_trackedrepo_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="channel",
            name="icon_emoji",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="channel",
            name="icon_image",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="channel",
            name="icon_text",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="channel",
            name="color",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
    ]
