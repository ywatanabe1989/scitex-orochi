"""Backfill: dedupe legacy bare-name group channels into ``#name`` canonical.

Why this exists
---------------
Prior to todo#326 the hub had no normalization on the write path, so any
client posting to ``general`` (or ``progress``, ``escalation`` …) created
a separate ``Channel`` row alongside the canonical ``#general``. The
read-side normalization (2f4e073) hid this in the sidebar but the
duplicate rows still hold messages — so clicking ``#general`` shows only
one of the two histories and the other becomes invisible.

What this migration does
------------------------
For every workspace, walk all group-kind channels whose name is neither
``#``-prefixed nor ``dm:``-prefixed. For each such legacy row:

  1. compute the canonical name (``#<name>``);
  2. find or create the canonical Channel row (using ``Channel.objects``
     so the model save() normalizer also runs);
  3. reassign every Message FK from the legacy row to the canonical row;
  4. delete the legacy row.

Idempotent: re-running is a no-op once all rows are normalized.
Reverse: not supported — there is no record of which messages came from
which legacy bucket. ``RunPython.noop`` is used so the migration is
forward-only but Django still recognises a reverse step exists.
"""
from django.db import migrations


def merge_unhashed_channels(apps, schema_editor):
    Channel = apps.get_model("hub", "Channel")
    Message = apps.get_model("hub", "Message")

    legacy_qs = Channel.objects.filter(kind="group").exclude(
        name__startswith="#"
    ).exclude(name__startswith="dm:")

    merged = 0
    deleted = 0
    for legacy in legacy_qs.iterator():
        name = legacy.name.strip()
        if not name:
            # Empty-name rows can't be merged into anything sensible;
            # delete them outright (they were never reachable from the UI).
            Message.objects.filter(channel=legacy).delete()
            legacy.delete()
            deleted += 1
            continue
        canonical_name = f"#{name}"
        canonical, _ = Channel.objects.get_or_create(
            workspace=legacy.workspace,
            name=canonical_name,
            defaults={
                "description": legacy.description,
                "kind": legacy.kind,
            },
        )
        if canonical.pk == legacy.pk:
            # get_or_create returned the same row — happens when name was
            # already canonical and the .exclude() filter was bypassed by
            # a race. Skip.
            continue
        Message.objects.filter(channel=legacy).update(channel=canonical)
        legacy.delete()
        merged += 1

    if merged or deleted:
        print(
            f"  hub.0015: merged {merged} legacy channel(s) into "
            f"# canonical, deleted {deleted} empty-name row(s)"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0014_pushsubscription"),
    ]

    operations = [
        migrations.RunPython(
            merge_unhashed_channels,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
