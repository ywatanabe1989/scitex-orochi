"""ADR-0003 Phase 1 — sac inventory reconciler daemon.

Per ADR 0003 §Decision 2, sac filesystem inventory is the canonical
source of truth for which agents exist. This daemon is the single
highest-leverage change that resolves the operator's "old contributors
stay in the orochi UI for months after they're gone from sac" complaint
(operator msg #74) WITHOUT touching any model, requiring a migration,
or waiting for the (still-to-be-built) sac extension ports of
Decision 2-B.

SAC v3 dir-as-SSoT
------------------

Canonical SAC v3 inventory layout (see
``~/proj/scitex-agent-container/examples/agents/full-agent/spec.yaml``
lines 1-7 — the format docs are inline in the example):

    <agents_dir>/<name>/spec.yaml

**The directory name IS the agent name.** There is no top-level
``name:`` field in the YAML — the parent directory is the
single-source-of-truth ("dir-as-SSoT"). This daemon honours that
convention: ``_parse_spec`` derives ``name = spec_path.parent.name``
and never reads a top-level ``name`` key.

The other two top-level keys the reconciler validates are:

* ``apiVersion: scitex-agent-container/v3`` — REQUIRED. Anything else
  (v1, v2, missing) is logged with the actual value and skipped.
* ``kind: Agent | AgentProxy`` — REQUIRED. Any other value is logged
  and skipped.

This Phase-1 daemon does NOT read ``metadata.labels.*`` or any
``spec.*`` subsection. Future PRs may map ``metadata.labels.role`` /
``metadata.labels.description`` etc. into orochi-side surfaces, but
that's out of scope here — the reconciler's only job is "what agents
exist (per SAC's directory inventory)".

Behaviour
---------

1. Read ``<agents_dir>/*/spec.yaml`` (``<agents_dir>`` overridable via
   ``SCITEX_AGENT_CONTAINER_AGENTS_DIR``; default
   ``~/.scitex/agent-container/agents``).
2. Parse each ``spec.yaml`` (``yaml.safe_load``). Validate apiVersion
   and kind; derive name from the parent directory.
3. For each name in inventory:
     - upsert an ``AgentProfile`` row (create with ``is_hidden=False``,
       or — for existing rows — clear ``is_hidden`` if it was set).
     - **Never clobber operator-set icon fields** (``icon_emoji``,
       ``icon_image``, ``icon_text``, ``color``). Operators configure
       those via the dashboard; the reconciler's only mutation on an
       existing row is the ``is_hidden`` flag.
4. For each existing ``AgentProfile.name`` NOT in inventory:
     - set ``is_hidden=True``. **DO NOT delete** — message history
       must be preserved (ADR §Decision 2 step 1 is explicit).
5. Sleep ``SCITEX_OROCHI_SAC_SYNC_INTERVAL`` seconds (default 300).

Workspace selection (Phase-1 simplification)
--------------------------------------------

The live ``AgentProfile`` model is keyed on
``unique_together = ("workspace", "name")`` (see
``apps/hub/models/_identity.py:195``). SAC's filesystem inventory has
no workspace concept. Until a multi-workspace-routing ADR lands, the
reconciler operates against a single configurable workspace:

* ``SCITEX_OROCHI_SAC_SYNC_WORKSPACE`` env var picks the target name.
* Default: ``"default"``.
* The workspace is auto-created on first run via ``get_or_create``.

What this daemon DEFERS
-----------------------

* **Multi-host inventory.** Single-host first (the dispatcher host);
  ADR §Decision 2 step 1 explicitly defers fleet inventory to a
  follow-up ADR.
* **ContainerAgent migration** (ADR §Decision 2 steps 2-3). This
  daemon does NOT touch the ``ContainerAgent`` model or its REST
  surface.
* **In-memory ``hub.registry._agents`` rename to
  ``_session_cache``** (ADR §Decision 2 step 3).
* **``metadata.labels.*`` mapping** into orochi-side metadata
  (description, role, capabilities).

Wiring
------

* ``run()`` — top-level async coroutine; the daemon body.
* ``main()`` — sync wrapper, ``asyncio.run(run())``. Called by the
  Django management command at
  ``apps/hub/management/commands/sync_sac_inventory.py``
  (``python manage.py sync_sac_inventory``).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable

import yaml

# Module-level logger — matches the project pattern
# (``logging.getLogger("orochi.<scope>")``; cf. ``apps/hub/apps.py``,
# ``src/scitex_orochi/_daemons/_stale_pr/_wrapper.py:45``).
logger = logging.getLogger("orochi.daemon.sac_inventory_sync")


# ---------------------------------------------------------------------------
# Defaults / env vars
# ---------------------------------------------------------------------------

#: Hard-coded fallback when ``SCITEX_AGENT_CONTAINER_AGENTS_DIR`` is unset.
#: Matches the ADR-0003 §Decision 2 example path.
DEFAULT_AGENTS_DIR = "~/.scitex/agent-container/agents"

#: Tick interval in seconds (overridable via env).
DEFAULT_INTERVAL_S = 300

#: Workspace the reconciler upserts AgentProfile rows into. See module
#: docstring "Workspace selection".
DEFAULT_WORKSPACE_NAME = "default"

#: SAC apiVersion prefix the reconciler accepts. v1/v2 specs are
#: warned + skipped (kept readable but not synced).
_REQUIRED_API_VERSION_PREFIX = "scitex-agent-container/v3"

#: SAC kinds the reconciler accepts. Other kinds are warned + skipped.
_ACCEPTED_KINDS = frozenset({"Agent", "AgentProxy"})

_ENV_AGENTS_DIR = "SCITEX_AGENT_CONTAINER_AGENTS_DIR"
_ENV_INTERVAL = "SCITEX_OROCHI_SAC_SYNC_INTERVAL"
_ENV_WORKSPACE = "SCITEX_OROCHI_SAC_SYNC_WORKSPACE"


# ---------------------------------------------------------------------------
# Inventory parsing
# ---------------------------------------------------------------------------


def _resolve_agents_dir() -> Path:
    """Return the sac agents inventory directory.

    Reads ``SCITEX_AGENT_CONTAINER_AGENTS_DIR`` first; falls back to
    ``~/.scitex/agent-container/agents``. ``~`` is expanded.
    """
    raw = os.environ.get(_ENV_AGENTS_DIR, DEFAULT_AGENTS_DIR)
    return Path(raw).expanduser()


def _iter_spec_files(agents_dir: Path) -> Iterable[Path]:
    """Yield each ``<agents_dir>/<name>/spec.yaml`` that exists.

    Per SAC v3 dir-as-SSoT, the canonical layout is one directory per
    agent with a ``spec.yaml`` inside. The directory name is the agent
    name (see module docstring).
    """
    if not agents_dir.exists() or not agents_dir.is_dir():
        logger.warning(
            "sac agents dir does not exist: %s (env=%s)",
            agents_dir,
            _ENV_AGENTS_DIR,
        )
        return
    for child in sorted(agents_dir.iterdir()):
        if not child.is_dir():
            continue
        spec = child / "spec.yaml"
        if spec.is_file():
            yield spec


def _parse_spec(spec_path: Path) -> dict | None:
    """Parse a single ``spec.yaml`` and return ``{"name": <dir_name>}``,
    or ``None`` if the file is malformed or fails apiVersion/kind
    validation.

    Per SAC v3 dir-as-SSoT, the agent name is derived from
    ``spec_path.parent.name`` — there is NO top-level ``name:`` field
    in the canonical v3 YAML.

    Validation rules (warn+skip on mismatch):
        * ``apiVersion`` must start with ``"scitex-agent-container/v3"``.
        * ``kind`` must be ``"Agent"`` or ``"AgentProxy"``.
    """
    try:
        with spec_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (yaml.YAMLError, OSError) as exc:
        # Per the test contract: bad yaml does not crash the pass; it
        # is logged and skipped.
        logger.warning("skipping malformed spec %s: %s", spec_path, exc)
        return None

    if not isinstance(raw, dict):
        logger.warning(
            "skipping spec %s: top-level is not a mapping (got %s)",
            spec_path,
            type(raw).__name__,
        )
        return None

    api_version = raw.get("apiVersion")
    if not isinstance(api_version, str) or not api_version.startswith(
        _REQUIRED_API_VERSION_PREFIX
    ):
        logger.warning(
            "skipping spec %s: unsupported apiVersion=%r (require prefix %r)",
            spec_path,
            api_version,
            _REQUIRED_API_VERSION_PREFIX,
        )
        return None

    kind = raw.get("kind")
    if kind not in _ACCEPTED_KINDS:
        logger.warning(
            "skipping spec %s: unsupported kind=%r (accept %s)",
            spec_path,
            kind,
            sorted(_ACCEPTED_KINDS),
        )
        return None

    name = spec_path.parent.name
    if not name or not name.strip():
        # Defensive: shouldn't happen given _iter_spec_files only yields
        # children of agents_dir, but guard anyway.
        logger.warning("skipping spec %s: empty directory name", spec_path)
        return None

    return {"name": name.strip()}


def _read_inventory(agents_dir: Path) -> dict[str, dict]:
    """Read the full inventory keyed by agent name.

    Malformed individual files are logged + skipped; the rest of the
    pass proceeds.
    """
    inventory: dict[str, dict] = {}
    for spec_path in _iter_spec_files(agents_dir):
        parsed = _parse_spec(spec_path)
        if parsed is None:
            continue
        inventory[parsed["name"]] = parsed
    return inventory


# ---------------------------------------------------------------------------
# DB reconciliation
# ---------------------------------------------------------------------------


def _resolve_workspace():
    """Return the Workspace the reconciler should write into.

    Lazy import of Django models so this module can be imported (e.g.
    for unit-testing the yaml-parse helpers) without Django being
    set up. See module docstring "Workspace selection" for the
    Phase-1 simplification rationale.
    """
    from apps.hub.models import Workspace

    name = os.environ.get(_ENV_WORKSPACE, DEFAULT_WORKSPACE_NAME)
    workspace, _ = Workspace.objects.get_or_create(
        name=name,
        defaults={"description": f"Auto-created by sac inventory reconciler ({name})"},
    )
    return workspace


def reconcile_once(agents_dir: Path | None = None) -> dict[str, int]:
    """Run a single reconcile pass synchronously.

    Returns a small dict of counters (useful for tests + tick logs):
        {"present": N, "created": M, "hidden": H, "unhidden": U}

    Synchronous because Django ORM is sync; the async ``run()`` loop
    drives this in a thread (asyncio.to_thread) so the event loop
    doesn't block on DB I/O.

    NOTE: on existing rows, the ONLY field this function mutates is
    ``is_hidden``. Operator-set icon fields (``icon_emoji``,
    ``icon_image``, ``icon_text``, ``color``) are never touched.
    """
    agents_dir = agents_dir or _resolve_agents_dir()
    inventory = _read_inventory(agents_dir)

    # Lazy import — see _resolve_workspace.
    from apps.hub.models import AgentProfile

    workspace = _resolve_workspace()

    counters = {"present": 0, "created": 0, "hidden": 0, "unhidden": 0}

    # ----- upsert each name that IS in inventory -----------------------
    for name in inventory:
        counters["present"] += 1
        # On create, set ONLY workspace + name + is_hidden. Icons are
        # operator-managed via the dashboard; the reconciler must not
        # supply defaults (it would lock in empty values on the first
        # pass and then the no-clobber rule below would prevent the
        # operator's later edits from taking effect — wait, that's not
        # true because save-from-dashboard is a direct field write. But
        # symmetrically: the reconciler has no opinion on icons. Don't
        # set them.).
        profile, created = AgentProfile.objects.get_or_create(
            workspace=workspace,
            name=name,
            defaults={"is_hidden": False},
        )
        if created:
            counters["created"] += 1
            continue

        # Existing row: the ONLY mutation is unhiding if it was hidden.
        # Icons / health fields are deliberately untouched.
        if profile.is_hidden:
            profile.is_hidden = False
            profile.save(update_fields=["is_hidden", "updated_at"])
            counters["unhidden"] += 1

    # ----- hide each existing row whose name is NOT in inventory -------
    # Note: scoped to the configured workspace. DO NOT delete.
    stale_qs = AgentProfile.objects.filter(workspace=workspace).exclude(
        name__in=list(inventory.keys())
    )
    for profile in stale_qs:
        if not profile.is_hidden:
            profile.is_hidden = True
            profile.save(update_fields=["is_hidden", "updated_at"])
            counters["hidden"] += 1

    logger.info(
        "sac inventory reconcile pass: %s",
        " ".join(f"{k}={v}" for k, v in counters.items()),
    )
    return counters


# ---------------------------------------------------------------------------
# Async daemon loop
# ---------------------------------------------------------------------------


def _resolve_interval_s() -> int:
    raw = os.environ.get(_ENV_INTERVAL)
    if not raw:
        return DEFAULT_INTERVAL_S
    try:
        v = int(raw)
        return v if v > 0 else DEFAULT_INTERVAL_S
    except ValueError:
        logger.warning(
            "ignoring non-integer %s=%r; falling back to %ds",
            _ENV_INTERVAL,
            raw,
            DEFAULT_INTERVAL_S,
        )
        return DEFAULT_INTERVAL_S


async def run(max_ticks: int | None = None) -> None:
    """Run the reconciler loop forever (or for ``max_ticks`` iterations).

    The ``max_ticks`` knob exists for ``--once`` smoke tests and for
    future integration tests that want to drive the loop deterministically.
    Production use is ``max_ticks=None``.
    """
    interval_s = _resolve_interval_s()
    agents_dir = _resolve_agents_dir()
    logger.info(
        "sac inventory reconciler starting: agents_dir=%s interval=%ss",
        agents_dir,
        interval_s,
    )

    tick = 0
    while True:
        tick += 1
        try:
            # ORM is sync; offload so the event loop stays responsive
            # when the daemon eventually lands alongside other async
            # daemons in the same process.
            await asyncio.to_thread(reconcile_once, agents_dir)
        except Exception:  # pragma: no cover — last-ditch crash guard
            # NEVER let a single bad pass kill the daemon. Log and
            # keep ticking; the operator's worst-case is "stale UI",
            # not "no reconciler at all".
            logger.exception("sac inventory reconcile pass failed (tick=%d)", tick)

        if max_ticks is not None and tick >= max_ticks:
            return

        await asyncio.sleep(interval_s)


def main() -> int:
    """Sync entry point. Wired by the Django management command at
    ``apps/hub/management/commands/sync_sac_inventory.py``.
    """
    # Basic logging config in case nothing else has set it up (e.g.
    # when launched bare via ``python -m`` rather than through
    # ``manage.py``). Mirrors the pattern in
    # ``src/scitex_orochi/_daemons/_stale_pr/__main__.py``.
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("sac inventory reconciler interrupted; exiting")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
