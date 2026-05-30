"""Add sort_order to ChannelPreference for drag-and-drop reordering."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0019_channel_membership"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelpreference",
            name="sort_order",
            field=models.IntegerField(
                default=0,
                db_index=True,
                help_text="Manual sort order within sidebar section (drag-and-drop)",
            ),
        ),
    ]
