"""Split ``ChannelMembership.permission`` into ``can_read`` + ``can_write``.

Lead directive msg#16884. Replaces the single-choice CharField with two
independent booleans so the four combinations (read-write, read-only,
write-only, admin lockout) are representable without juggling an enum.

Forward:
  1. ``AddField`` ``can_read`` / ``can_write`` with default ``True``.
  2. ``RunPython`` populate the bits from the existing ``permission`` column:
       - ``read-write`` → ``(True, True)``
       - ``read-only``  → ``(True, False)``
       - ``write-only`` → ``(False, True)`` (interim choice from PR #353)
       - anything else  → ``(True, True)`` (historical permissive default)

Reverse:
  - ``RunPython`` rebuilds ``permission`` from the bits (uses
    ``ChannelMembership.bits_to_perm`` semantics inline so the reverse
    works without importing the model file).
  - ``RemoveField`` drops the two booleans.

``permission`` stays on the table for one release cycle (lead
msg#16884). A follow-up migration will drop it once every deploy has
rolled past 0029.
"""

from __future__ import annotations

from django.db import migrations, models


def _backfill_bits(apps, schema_editor):
    ChannelMembership = apps.get_model("hub", "ChannelMembership")
    # Read-only rows lose the read bit only when the row says so; the
    # default on the new columns is (True, True) which already matches
    # the "read-write" case, so we only need to overwrite deviating rows.
    # Use ``update()`` so the bridge in ``ChannelMembership.save()``
    # (which lives on the app-level model, not this migration-level one)
    # doesn't fight us.
    ChannelMembership.objects.filter(permission="read-only").update(
        can_read=True, can_write=False
    )
    ChannelMembership.objects.filter(permission="write-only").update(
        can_read=False, can_write=True
    )
    # "read-write" rows already match the default; no-op update skipped.


def _backfill_permission(apps, schema_editor):
    ChannelMembership = apps.get_model("hub", "ChannelMembership")
    # Symmetric reverse: derive the string from the bits so a rollback
    # leaves the legacy column populated correctly.
    for row in ChannelMembership.objects.all().only(
        "id", "can_read", "can_write"
    ):
        cr = bool(row.can_read)
        cw = bool(row.can_write)
        if cr and cw:
            perm = "read-write"
        elif cr and not cw:
            perm = "read-only"
        elif (not cr) and cw:
            perm = "write-only"
        else:
            # (False, False) — no legacy enum; choose read-only as the
            # most-restrictive label.
            perm = "read-only"
        if row.permission != perm:
            ChannelMembership.objects.filter(pk=row.pk).update(permission=perm)


class Migration(migrations.Migration):

    dependencies = [
        ("hub", "0028_alter_channelmembership_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelmembership",
            name="can_read",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Whether the member receives chat/reaction/edit/delete "
                    "fan-out for this channel. False = write-only (no read)."
                ),
            ),
        ),
        migrations.AddField(
            model_name="channelmembership",
            name="can_write",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Whether the member is allowed to post to this channel. "
                    "False = read-only."
                ),
            ),
        ),
        migrations.RunPython(_backfill_bits, _backfill_permission),
    ]
