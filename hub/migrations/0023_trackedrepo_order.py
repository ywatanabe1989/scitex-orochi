# Generated for todo#91 — drag-and-drop reorder for Releases tab.

from django.db import migrations, models


def seed_order(apps, schema_editor):
    """Assign a deterministic initial order for existing rows so the
    Releases sub-tab bar preserves the current visible order after the
    migration (previously ``ordering = ["created_at", "id"]``)."""
    TrackedRepo = apps.get_model("hub", "TrackedRepo")
    # Group by workspace so order restarts at 0 per workspace.
    workspace_ids = (
        TrackedRepo.objects.values_list("workspace_id", flat=True)
        .distinct()
        .order_by("workspace_id")
    )
    for ws_id in workspace_ids:
        rows = TrackedRepo.objects.filter(workspace_id=ws_id).order_by(
            "created_at", "id"
        )
        for idx, row in enumerate(rows):
            row.order = idx
            row.save(update_fields=["order"])


def unseed_order(apps, schema_editor):
    # No-op: the column is dropped by the reverse of AddField.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("hub", "0022_trackedrepo"),
    ]

    operations = [
        migrations.AddField(
            model_name="trackedrepo",
            name="order",
            field=models.IntegerField(default=0, db_index=True),
        ),
        migrations.AlterModelOptions(
            name="trackedrepo",
            options={"ordering": ["order", "id"]},
        ),
        migrations.RunPython(seed_order, reverse_code=unseed_order),
    ]
