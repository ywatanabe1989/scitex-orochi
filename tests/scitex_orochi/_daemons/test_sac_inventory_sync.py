"""Tests for the sac inventory reconciler daemon (ADR-0003 Phase 1).

Six contract assertions:

1. A reconcile pass with 3 SAC-v3 spec yamls creates 3 AgentProfile rows.
2. A subsequent pass with one yaml removed sets that row's
   ``is_hidden=True`` (does NOT delete).
3. A subsequent pass with the previously-removed yaml restored sets
   ``is_hidden=False`` again.
4. Malformed yaml in one file does not crash the reconcile pass —
   other files still processed; the bad one is logged + skipped.
5. A spec with an unsupported ``apiVersion`` is logged + skipped (no
   AgentProfile row created).
6. The reconciler does NOT clobber operator-set icon fields when
   upserting an existing row.

Pattern note: Django needs configuring BEFORE any ``apps.hub.*`` import.
Set ``DJANGO_SETTINGS_MODULE=config.settings`` (per ADR 0002 layout —
see ``/work/manage.py``), call ``django.setup()``, and degrade to a
``pytest.skip`` when Django isn't installed.

We do NOT depend on ``pytest-django``. Instead each test runs inside a
Django transaction that is rolled back at teardown — the same isolation
``TestCase`` gives you, but composable with pytest fixtures (``tmp_path``,
``monkeypatch``, ``caplog``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

# --- Django bootstrap ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Force a tmp SQLite DB so the test never touches the live db.sqlite3
# (which may carry stale schema from older branches). The fixture below
# runs ``migrate`` on this fresh DB on first use.
import tempfile as _tempfile

os.environ.setdefault(
    "SCITEX_OROCHI_DB_PATH",
    str(Path(_tempfile.gettempdir()) / "scitex_orochi_sac_inventory_test.sqlite3"),
)
# Wipe any leftover from a previous run so each session starts clean.
_test_db = Path(os.environ["SCITEX_OROCHI_DB_PATH"])
if _test_db.exists():
    _test_db.unlink()

try:
    import django as _django

    _django.setup()
    _DJANGO_OK = True
except Exception:  # pragma: no cover — Django missing or misconfigured
    _DJANGO_OK = False

pytestmark = pytest.mark.skipif(
    not _DJANGO_OK, reason="Django not configured — skipping apps.hub.* tests"
)


# ---------------------------------------------------------------------------
# Filesystem helpers — no business-logic mocking, only tmp_path writes.
# ---------------------------------------------------------------------------


def _write_spec(
    agents_dir: Path,
    name: str,
    *,
    api_version: str = "scitex-agent-container/v3",
    kind: str = "Agent",
) -> Path:
    """Materialise a SAC-v3-shaped ``<agents_dir>/<name>/spec.yaml`` on disk.

    Mirrors the per-agent-directory layout used by SAC v3
    (see ``examples/agents/full-agent/spec.yaml`` in the SAC repo):
    one directory per agent, the directory name IS the agent name
    (dir-as-SSoT — NO top-level ``name:`` key in the YAML).

    Minimal valid payload: apiVersion + kind + a tiny ``spec`` block
    that satisfies SAC's own validator (runtime + apptainer.image).
    """
    import yaml

    agent_dir = agents_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "apiVersion": api_version,
        "kind": kind,
        "spec": {
            "runtime": "apptainer",
            "apptainer": {
                "image": "~/.scitex/agent-container/containers/sac-base.sif",
            },
        },
    }
    spec_path = agent_dir / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return spec_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_transaction():
    """Wrap each test in a Django transaction that is rolled back at
    teardown. Equivalent to what ``django.test.TestCase`` does, but
    composable with pytest fixtures.

    Also ensures the schema exists (``call_command("migrate", ...)``)
    on first use — this matters when the test is invoked from a bare
    ``pytest tests/`` and not via ``manage.py test``.
    """
    from django.core.management import call_command
    from django.db import connection, transaction

    # Cheap idempotent migrate — Django no-ops if all migrations are
    # already applied on the current connection.
    if not connection.introspection.table_names():
        call_command("migrate", "--run-syncdb", verbosity=0, interactive=False)

    atomic = transaction.atomic()
    atomic.__enter__()
    sid = transaction.savepoint()
    try:
        yield
    finally:
        transaction.savepoint_rollback(sid)
        atomic.__exit__(Exception, None, None)


@pytest.fixture
def agents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_transaction) -> Path:
    """Fresh empty sac agents inventory rooted in tmp_path, exposed
    to the daemon via the documented env var. Each test gets its own
    isolated workspace so name-collision can't leak across runs.
    """
    d = tmp_path / "sac-agents"
    d.mkdir()
    monkeypatch.setenv("SCITEX_AGENT_CONTAINER_AGENTS_DIR", str(d))
    monkeypatch.setenv(
        "SCITEX_OROCHI_SAC_SYNC_WORKSPACE", f"reconciler-test-{tmp_path.name}"
    )
    return d


def _ws():
    from apps.hub.models import Workspace

    return Workspace.objects.get(name=os.environ["SCITEX_OROCHI_SAC_SYNC_WORKSPACE"])


def _profile_names() -> set[str]:
    from apps.hub.models import AgentProfile

    return set(
        AgentProfile.objects.filter(workspace=_ws()).values_list("name", flat=True)
    )


def _hidden_names() -> set[str]:
    from apps.hub.models import AgentProfile

    return set(
        AgentProfile.objects.filter(workspace=_ws(), is_hidden=True).values_list(
            "name", flat=True
        )
    )


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_first_pass_creates_one_row_per_spec(agents_dir):
    """Contract 1 — three yamls → three AgentProfile rows, all visible."""
    from scitex_orochi._daemons._sac_inventory_sync import reconcile_once

    for n in ("alpha", "bravo", "charlie"):
        _write_spec(agents_dir, n)

    counters = reconcile_once(agents_dir)

    assert counters["present"] == 3
    assert counters["created"] == 3
    assert counters["hidden"] == 0
    assert _profile_names() == {"alpha", "bravo", "charlie"}
    assert _hidden_names() == set()


def test_removed_yaml_hides_but_does_not_delete(agents_dir):
    """Contract 2 — removing a yaml flips is_hidden, preserves the row."""
    from scitex_orochi._daemons._sac_inventory_sync import reconcile_once

    for n in ("alpha", "bravo", "charlie"):
        _write_spec(agents_dir, n)
    reconcile_once(agents_dir)  # baseline

    shutil.rmtree(agents_dir / "bravo")

    counters = reconcile_once(agents_dir)

    assert counters["present"] == 2
    assert counters["hidden"] == 1
    # Row still exists — message history preserved (ADR §Decision 2
    # step 1 explicit requirement).
    assert _profile_names() == {"alpha", "bravo", "charlie"}
    assert _hidden_names() == {"bravo"}


def test_restored_yaml_unhides(agents_dir):
    """Contract 3 — re-appearing yaml clears is_hidden."""
    from scitex_orochi._daemons._sac_inventory_sync import reconcile_once

    for n in ("alpha", "bravo", "charlie"):
        _write_spec(agents_dir, n)
    reconcile_once(agents_dir)
    shutil.rmtree(agents_dir / "bravo")
    reconcile_once(agents_dir)
    assert _hidden_names() == {"bravo"}

    # Operator re-registers bravo with sac → spec.yaml back
    _write_spec(agents_dir, "bravo")
    counters = reconcile_once(agents_dir)

    assert counters["unhidden"] == 1
    assert _hidden_names() == set()
    assert _profile_names() == {"alpha", "bravo", "charlie"}


def test_malformed_yaml_does_not_crash_pass(agents_dir, caplog):
    """Contract 4 — bad yaml is logged + skipped; rest of the pass still runs."""
    import logging

    from scitex_orochi._daemons._sac_inventory_sync import reconcile_once

    _write_spec(agents_dir, "alpha")
    _write_spec(agents_dir, "charlie")

    # Hand-write a broken spec.yaml for "bravo" (unclosed bracket).
    (agents_dir / "bravo").mkdir()
    (agents_dir / "bravo" / "spec.yaml").write_text(
        "apiVersion: scitex-agent-container/v3\nkind: Agent\nspec: {runtime: [unterminated",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="orochi.daemon.sac_inventory_sync"):
        counters = reconcile_once(agents_dir)

    # The two well-formed specs still got processed.
    assert counters["present"] == 2
    assert _profile_names() == {"alpha", "charlie"}
    # The bad file was logged with the path so an operator can find it.
    assert any(
        "bravo" in rec.message and "spec.yaml" in rec.message for rec in caplog.records
    ), (
        f"expected a warning naming bravo/spec.yaml, got: {[r.message for r in caplog.records]}"
    )


def test_unknown_apiversion_skipped(agents_dir, caplog):
    """Contract 5 — non-v3 apiVersion is logged + skipped, no row created."""
    import logging

    from scitex_orochi._daemons._sac_inventory_sync import reconcile_once

    _write_spec(agents_dir, "alpha")
    # bravo declares the older v2 schema — must NOT be upserted.
    _write_spec(agents_dir, "bravo", api_version="scitex-agent-container/v2")
    _write_spec(agents_dir, "charlie")

    with caplog.at_level(logging.WARNING, logger="orochi.daemon.sac_inventory_sync"):
        counters = reconcile_once(agents_dir)

    assert counters["present"] == 2
    assert counters["created"] == 2
    # bravo not in the DB — the v2 spec was rejected.
    assert _profile_names() == {"alpha", "charlie"}
    # And the operator gets a warning naming the file + the bad version.
    assert any(
        "bravo" in rec.message and "apiVersion" in rec.message for rec in caplog.records
    ), (
        f"expected an apiVersion warning naming bravo, got: {[r.message for r in caplog.records]}"
    )


def test_icons_are_not_clobbered(agents_dir):
    """Contract 6 — operator-set icon fields survive a reconcile pass.

    Operators set icons via the dashboard (msg#17078 / AgentProfile
    has icon_emoji / icon_image / icon_text / color columns). The
    reconciler must never touch those fields on existing rows — the
    only mutation it makes on an existing row is the ``is_hidden`` flag.
    """
    from apps.hub.models import AgentProfile, Workspace
    from scitex_orochi._daemons._sac_inventory_sync import reconcile_once

    # Pre-create the workspace + a row with operator-set icons.
    ws_name = os.environ["SCITEX_OROCHI_SAC_SYNC_WORKSPACE"]
    ws, _ = Workspace.objects.get_or_create(
        name=ws_name, defaults={"description": "test"}
    )
    AgentProfile.objects.create(
        workspace=ws,
        name="alpha",
        icon_emoji="🦊",
        icon_text="AL",
        color="#ff8800",
        is_hidden=False,
    )

    # SAC inventory has alpha present.
    _write_spec(agents_dir, "alpha")

    reconcile_once(agents_dir)

    profile = AgentProfile.objects.get(workspace=ws, name="alpha")
    # Icons SURVIVE — the reconciler never overwrites them.
    assert profile.icon_emoji == "🦊"
    assert profile.icon_text == "AL"
    assert profile.color == "#ff8800"
    assert profile.is_hidden is False
