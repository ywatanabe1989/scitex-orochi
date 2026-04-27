"""(Available Now) help-suffix layer for scitex-orochi CLI.

Implements the "minimum-surprise" help-display policy from §9 of the CLI
refactor plan (PR #337 / msg#16514): the only visible difference in ``--help`` output
is a quiet ``(Available Now)`` suffix next to each subcommand whose backing
service is currently reachable.

Design constraints (from the plan):

* **Total probe budget ≤ 100 ms** across all probes, regardless of how many
  subcommands are annotated. Probes run in parallel threads with a tight
  per-probe timeout; results short-circuit on the deadline.
* **No false positives.** For subcommands with no service dependency
  (e.g. ``docs``, ``skills``), the suffix is omitted entirely.
* **No error text, no colour, no banner.** Suffix present iff reachable;
  absent otherwise.

The three probe categories (by ``ProbeKind``):

* ``HUB`` — hub-reachable commands hit ``/api/healthz`` on the configured
  host:port via a single HTTP GET with a tight timeout.
* ``LOCAL_DAEMON`` — daemon-reachable commands check whether the local
  ``orochi-cron`` LaunchAgent (macOS) / systemd user unit (Linux) exists
  and is loaded.
* ``PURE_LOCAL`` — pure-local commands (doc/help/skill browsing) — the
  suffix is omitted; no probe runs.

The probe assignment for each top-level subcommand lives in
:data:`DEFAULT_PROBE_MAP`. Step A wires the decorator onto the top-level
``scitex-orochi`` click group only; Step B will recurse into nested groups.
"""

from __future__ import annotations

import enum
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import click

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Maximum total wall-clock budget for probing, in seconds. Matches §9.
TOTAL_BUDGET_S: float = 0.100

#: Per-probe socket / HTTP timeout, in seconds. Strictly < TOTAL_BUDGET_S
#: so one slow probe cannot blow the shared budget on its own.
PER_PROBE_TIMEOUT_S: float = 0.080

#: Suffix appended to reachable subcommands in ``--help`` output.
AVAILABLE_SUFFIX: str = "(Available Now)"


class ProbeKind(enum.Enum):
    """What kind of reachability check to run for a subcommand."""

    HUB = "hub"
    LOCAL_DAEMON = "local_daemon"
    PURE_LOCAL = "pure_local"


# ---------------------------------------------------------------------------
# Default subcommand → probe mapping for the top-level group.
# Keyed by the *current* (pre-Step-B) command name; Step B/C will extend.
# ---------------------------------------------------------------------------

DEFAULT_PROBE_MAP: Mapping[str, ProbeKind] = {
    # ── Phase 1d Step C: canonical noun groups (plan §2 / PR #337). ──
    # The noun dispatchers are hub-dependent wherever their verbs talk
    # to the hub (agent, auth, channel, hook, invite, message, push,
    # server, system, workspace). ``config`` stays pure-local — its only
    # verb (``config init``) writes a local YAML.
    "agent": ProbeKind.HUB,
    "auth": ProbeKind.HUB,
    "channel": ProbeKind.HUB,
    "hook": ProbeKind.HUB,
    "invite": ProbeKind.HUB,
    "message": ProbeKind.HUB,
    "push": ProbeKind.HUB,
    "server": ProbeKind.HUB,
    "system": ProbeKind.HUB,
    "workspace": ProbeKind.HUB,
    "config": ProbeKind.PURE_LOCAL,
    # ── Phase 1d Step C: flat rename stubs (hard-error). ──
    # The stubs do not talk to the hub; they print-and-exit. Mark them
    # pure-local so no probe runs and no ``(Available Now)`` suffix is
    # rendered next to a command that will deterministically fail. This
    # avoids misleading operators who glance at ``--help``.
    "agent-launch": ProbeKind.PURE_LOCAL,
    "agent-restart": ProbeKind.PURE_LOCAL,
    "agent-status": ProbeKind.PURE_LOCAL,
    "agent-stop": ProbeKind.PURE_LOCAL,
    "list-agents": ProbeKind.PURE_LOCAL,
    "list-channels": ProbeKind.PURE_LOCAL,
    "list-members": ProbeKind.PURE_LOCAL,
    "list-workspaces": ProbeKind.PURE_LOCAL,
    "list-invites": ProbeKind.PURE_LOCAL,
    "show-status": ProbeKind.PURE_LOCAL,
    "show-history": ProbeKind.PURE_LOCAL,
    "send": ProbeKind.PURE_LOCAL,
    "listen": ProbeKind.PURE_LOCAL,
    "join": ProbeKind.PURE_LOCAL,
    "login": ProbeKind.PURE_LOCAL,
    "fleet": ProbeKind.PURE_LOCAL,
    "create-workspace": ProbeKind.PURE_LOCAL,
    "delete-workspace": ProbeKind.PURE_LOCAL,
    "create-invite": ProbeKind.PURE_LOCAL,
    "report": ProbeKind.PURE_LOCAL,
    "heartbeat-push": ProbeKind.PURE_LOCAL,
    "serve": ProbeKind.PURE_LOCAL,
    "setup-push": ProbeKind.PURE_LOCAL,
    "doctor": ProbeKind.PURE_LOCAL,
    "init": ProbeKind.PURE_LOCAL,
    "launch": ProbeKind.PURE_LOCAL,
    "deploy": ProbeKind.PURE_LOCAL,
    "stop": ProbeKind.PURE_LOCAL,
    # ── Other hub-dependent top-level commands (not renamed). ──
    "orochi_machine": ProbeKind.HUB,
    "host-liveness": ProbeKind.HUB,
    "hungry-signal": ProbeKind.HUB,
    "dispatch": ProbeKind.HUB,
    "todo": ProbeKind.HUB,
    "host-identity": ProbeKind.HUB,
    # ── Local daemon-dependent commands. ──
    "cron": ProbeKind.LOCAL_DAEMON,
    "chrome-watchdog": ProbeKind.LOCAL_DAEMON,
    "disk": ProbeKind.LOCAL_DAEMON,
    # ── Flat keepers (Q5): docs / skills / mcp stay flat. ──
    "docs": ProbeKind.PURE_LOCAL,
    "skills": ProbeKind.PURE_LOCAL,
    # Flat keeper `mcp start` is pure-local (stdio server startup): no
    # suffix added to keep external mcp.json contracts noise-free.
    "mcp": ProbeKind.PURE_LOCAL,
}


# ---------------------------------------------------------------------------
# Probe implementations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    name: str
    reachable: bool
    kind: ProbeKind
    elapsed_s: float


def probe_hub(host: str, port: int, timeout_s: float = PER_PROBE_TIMEOUT_S) -> bool:
    """Return True iff ``http://host:port/api/healthz`` returns HTTP < 500.

    Uses a single GET with a tight ``timeout``. Any network error / timeout
    / connection refused / DNS failure is treated as unreachable.
    """
    url = f"http://{host}:{port}/api/healthz"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status < 500
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, OSError):
        return False
    except Exception:  # pragma: no cover - belt-and-braces
        return False


def probe_local_daemon(name: str = "orochi-cron") -> bool:
    """Return True iff the local orochi daemon (LaunchAgent / systemd unit)
    exists and is loaded.

    * macOS (Darwin): ``launchctl list | grep <name>``
    * Linux: ``systemctl --user list-units --no-legend --all`` and look for
      the unit name.
    * Other: False.
    """
    platform_name = sys.platform
    if platform_name == "darwin":
        launchctl = shutil.which("launchctl")
        if launchctl is None:
            return False
        try:
            out = subprocess.run(
                [launchctl, "list"],
                capture_output=True,
                text=True,
                timeout=PER_PROBE_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        return name in (out.stdout or "")
    if platform_name.startswith("linux"):
        systemctl = shutil.which("systemctl")
        if systemctl is None:
            return False
        try:
            out = subprocess.run(
                [systemctl, "--user", "list-units", "--no-legend", "--all"],
                capture_output=True,
                text=True,
                timeout=PER_PROBE_TIMEOUT_S,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        return name in (out.stdout or "")
    return False


def probe_pure_local() -> bool:
    """Pure-local commands never annotate. Always returns False so the
    suffix is omitted."""
    return False


# ---------------------------------------------------------------------------
# Parallel probing with shared deadline
# ---------------------------------------------------------------------------


def run_probes(
    subcommands: Iterable[str],
    *,
    host: str,
    port: int,
    probe_map: Mapping[str, ProbeKind] = DEFAULT_PROBE_MAP,
    total_budget_s: float = TOTAL_BUDGET_S,
    hub_prober: Callable[[str, int, float], bool] = probe_hub,
    daemon_prober: Callable[[], bool] = probe_local_daemon,
) -> dict[str, ProbeResult]:
    """Probe the reachability of each subcommand in parallel.

    Any probe not finished before ``total_budget_s`` wall-clock seconds is
    treated as unreachable (suffix omitted). This keeps ``--help`` snappy
    even when the hub is unreachable and the TCP connect blocks for its
    full OS-level timeout.
    """
    results: dict[str, ProbeResult] = {}
    started = time.monotonic()

    # PURE_LOCAL commands: mark unreachable synchronously, no thread needed.
    # HUB + LOCAL_DAEMON run in a thread pool.
    to_probe: list[tuple[str, ProbeKind]] = []
    for name in subcommands:
        kind = probe_map.get(name)
        if kind is None or kind is ProbeKind.PURE_LOCAL:
            # Suffix omitted entirely; record an unreachable result so the
            # decorator knows to leave the help line untouched.
            results[name] = ProbeResult(
                name=name,
                reachable=False,
                kind=kind if kind is not None else ProbeKind.PURE_LOCAL,
                elapsed_s=0.0,
            )
            continue
        to_probe.append((name, kind))

    if not to_probe:
        return results

    def _one(name: str, kind: ProbeKind) -> ProbeResult:
        t0 = time.monotonic()
        try:
            if kind is ProbeKind.HUB:
                reachable = hub_prober(host, port, PER_PROBE_TIMEOUT_S)
            elif kind is ProbeKind.LOCAL_DAEMON:
                reachable = daemon_prober()
            else:
                reachable = False
        except Exception:  # pragma: no cover - defensive
            reachable = False
        return ProbeResult(
            name=name,
            reachable=reachable,
            kind=kind,
            elapsed_s=time.monotonic() - t0,
        )

    with ThreadPoolExecutor(max_workers=max(2, len(to_probe))) as pool:
        futures = {pool.submit(_one, name, kind): name for name, kind in to_probe}
        deadline = started + total_budget_s
        for fut in as_completed(futures, timeout=None):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Out of budget; mark all unfinished as unreachable and bail.
                break
            name = futures[fut]
            try:
                results[name] = fut.result(timeout=remaining)
            except Exception:
                results[name] = ProbeResult(
                    name=name,
                    reachable=False,
                    kind=probe_map.get(name, ProbeKind.HUB),
                    elapsed_s=time.monotonic() - started,
                )

        # Anything still unfinished: force-cancel, mark unreachable.
        for fut, name in futures.items():
            if name in results:
                continue
            fut.cancel()
            results[name] = ProbeResult(
                name=name,
                reachable=False,
                kind=probe_map.get(name, ProbeKind.HUB),
                elapsed_s=time.monotonic() - started,
            )

    return results


# ---------------------------------------------------------------------------
# Click integration — decorator + help-text augmentation
# ---------------------------------------------------------------------------


_PROBE_CACHE_LOCK = threading.Lock()
_PROBE_CACHE: dict[tuple[str, int], dict[str, ProbeResult]] = {}


def _get_hub_coords(ctx: click.Context) -> tuple[str, int]:
    """Resolve (host, port) from click context or env, without importing
    scitex_orochi._config at module load (keeps this module safe to import
    under any env)."""
    host = None
    port: int | None = None
    if ctx.obj:
        host = ctx.obj.get("host")
        port = ctx.obj.get("port")
    if not host or not port:
        try:
            from scitex_orochi._config import HOST, PORT

            host = host or HOST
            port = port or PORT
        except Exception:
            host = host or os.environ.get("SCITEX_OROCHI_HOST", "127.0.0.1")
            port = port or int(os.environ.get("SCITEX_OROCHI_PORT", "9559"))
    return str(host), int(port)


class AvailabilityAnnotatedGroup(click.Group):
    """Click ``Group`` subclass that attaches ``(Available Now)`` to the
    short-help of each reachable subcommand when rendering ``--help``.

    Only annotates the *direct* subcommands of this group — it does not
    recurse. Step B will wire the same logic into nested groups.
    """

    # Attribute is filled by :func:`annotate_help_with_availability` so we
    # don't force every Group subclass to pass a probe_map kwarg.
    _availability_probe_map: Mapping[str, ProbeKind] = DEFAULT_PROBE_MAP

    def format_commands(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        names = list(self.list_commands(ctx))
        host, port = _get_hub_coords(ctx)
        cache_key = (host, port)
        with _PROBE_CACHE_LOCK:
            cached = _PROBE_CACHE.get(cache_key)
        if cached is None:
            # Look up the probe implementations at call time (not via
            # default-arg capture) so ``unittest.mock.patch.object`` on
            # this module swaps them in correctly.
            import sys as _sys

            mod = _sys.modules[__name__]
            cached = run_probes(
                names,
                host=host,
                port=port,
                probe_map=self._availability_probe_map,
                hub_prober=mod.probe_hub,
                daemon_prober=mod.probe_local_daemon,
            )
            with _PROBE_CACHE_LOCK:
                _PROBE_CACHE[cache_key] = cached

        rows: list[tuple[str, str]] = []
        for name in names:
            cmd = self.get_command(ctx, name)
            if cmd is None:
                continue
            if getattr(cmd, "hidden", False):
                continue
            short = cmd.get_short_help_str(limit=formatter.width or 80)
            res = cached.get(name)
            if (
                res is not None
                and res.reachable
                and res.kind is not ProbeKind.PURE_LOCAL
            ):
                short = f"{short} {AVAILABLE_SUFFIX}".strip()
            rows.append((name, short))

        if rows:
            with formatter.section("Commands"):
                formatter.write_dl(rows)


def annotate_help_with_availability(
    group: click.Group,
    *,
    probe_map: Mapping[str, ProbeKind] | None = None,
) -> click.Group:
    """Swap the command class of ``group`` to one that annotates reachable
    subcommands with ``(Available Now)`` in ``--help``.

    Applied to the top-level ``scitex-orochi`` group only (Step A scope).
    Does not recurse into nested groups; that lands in Step B.
    """
    # Re-parent the class so the group's existing invoke callback / options
    # are preserved but format_commands uses our override.
    current_cls = type(group)
    # Build a dynamic subclass that mixes in the original behaviours plus
    # AvailabilityAnnotatedGroup.format_commands.
    if not isinstance(group, AvailabilityAnnotatedGroup):

        class _Annotated(AvailabilityAnnotatedGroup, current_cls):  # type: ignore[misc, valid-type]
            pass

        group.__class__ = _Annotated

    if probe_map is not None:
        group._availability_probe_map = probe_map  # type: ignore[attr-defined]
    return group


def reset_probe_cache() -> None:
    """Clear the module-level probe cache. Intended for tests."""
    with _PROBE_CACHE_LOCK:
        _PROBE_CACHE.clear()
