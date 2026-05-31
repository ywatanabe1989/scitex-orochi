"""Drift guard for the heartbeat field registry.

The registry at ``src/scitex_orochi/_models/heartbeat.py`` is the
canonical list of every field that flows on the heartbeat wire. Six
files currently duplicate this set (see the registry's docstring).
Until they all migrate, this test ensures:

* The registry is a SUPERSET of what ``heartbeat_cmd.py`` actually
  forwards. A new field added to the cmd without registering is a CI
  failure.
* No accidental duplicate field names in the registry.
* Every field has a non-empty ``notes`` string (forces operator-facing
  documentation at write time, the cheapest moment).

When migrating consumers to read from the registry, add this same
shape of test for each one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scitex_orochi._models import HEARTBEAT_FIELD_NAMES, HEARTBEAT_FIELDS

_HEARTBEAT_CMD_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "scitex_orochi"
    / "_cli"
    / "commands"
    / "heartbeat_cmd.py"
)


def _fields_used_in_heartbeat_cmd() -> set[str]:
    """Parse the field names appearing as dict keys in ``heartbeat_cmd.py``.

    The cmd has one big ``info={...}`` dict that lists every field
    name as a literal string key. Naïve regex is enough — the file
    has no other source of ``"field_name":`` patterns.
    """
    src = _HEARTBEAT_CMD_PATH.read_text()
    # Match `"<lowercase_field>":` at any indentation.
    pattern = re.compile(r'^\s*"([a-z_][a-z0-9_]*)"\s*:', re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(src)}


def test_no_duplicate_field_names_in_registry() -> None:
    names = [f.name for f in HEARTBEAT_FIELDS]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"duplicate field names in registry: {duplicates}"


def test_every_field_has_notes() -> None:
    """Forcing operator-facing notes at write time is the cheapest
    moment to capture the field's intent. Empty notes silently rot
    over time."""
    missing = [f.name for f in HEARTBEAT_FIELDS if not f.notes.strip()]
    assert not missing, f"fields without notes (add a one-line description): {missing}"


def test_registry_covers_heartbeat_cmd_fields() -> None:
    """Drift guard: every field literal in heartbeat_cmd.py must be in
    the registry. Adding a new field to the cmd without registering
    fails this test.

    The reverse direction (registry has fields the cmd doesn't) is
    EXPECTED during migration — the cmd will catch up incrementally.
    """
    cmd_fields = _fields_used_in_heartbeat_cmd()
    # Filter out non-heartbeat keys that happen to appear (e.g. the
    # request body's ``token``, response shape's ``status`` / ``error``).
    HARNESS_KEYS = {
        "token",
        "status",
        "error",
        # "name" is the only identity field the registry must cover —
        # all real heartbeat content keys go through.
    }
    missing_from_registry = (cmd_fields - HEARTBEAT_FIELD_NAMES) - HARNESS_KEYS
    assert not missing_from_registry, (
        "heartbeat_cmd.py forwards fields not in the registry "
        f"(src/scitex_orochi/_models/heartbeat.py): "
        f"{sorted(missing_from_registry)}\n"
        "Either add the field to HEARTBEAT_FIELDS or to HARNESS_KEYS "
        "in this test if it is intentionally not part of the "
        "wire-format payload."
    )


@pytest.mark.parametrize("f", HEARTBEAT_FIELDS, ids=lambda f: f.name)
def test_field_default_type_is_serializable(f) -> None:
    """Every default must be JSON-roundtrippable so the producer can
    emit it without bespoke serialization. None / str / int / list /
    dict / bool only."""
    import json

    try:
        json.dumps(f.default)
    except TypeError as e:
        pytest.fail(f"field {f.name!r} default {f.default!r} not JSON-able: {e}")
