"""DM-dispatch helpers for ``singleton-host-check.py`` (issue #250).

Split out of the main script to keep each file under the 512-line
ceiling and to make the dispatch path independently testable. The main
script re-exports these names so the existing ``importlib`` test
loader keeps working without per-test path rewrites.

What lives here
---------------
* ``HEALER_NAME_TEMPLATE`` / ``SCRIPT_AGENT_NAME`` / ``WORKSPACE_SLUG``
  — env-driven configuration for "who is the healer on host X" and
  "what sender identity do we DM as".
* ``_resolve_healer_name(host, template)`` — strict ``{host}``
  substitution; raises rather than silently producing a malformed name.
* ``_dm_channel_name(sender, healer)`` — canonical spec v3 §2.3
  ``dm:agent:<a>|agent:<b>`` channel name (sorted principals → name
  is initiator-independent → hub's ``_ensure_dm_channel`` is
  naturally idempotent).
* ``_format_dm_for_healer(warning)`` — action-oriented per-warning
  body that points the receiving healer at
  ``sac singleton-reconcile --execute``.
* ``_post_dm_to_healer(healer, text)`` — POSTs to
  ``/api/workspace/<slug>/messages/`` with ``?token=&agent=`` query
  auth. Returns bool; logs (does not raise) on hub-unreachable.
* ``dispatch_dm_warnings(warnings)`` — orchestrator the CLI calls,
  with an injectable ``post`` callable so tests can capture the
  call shape without touching the network.

References
----------
* Issue #250 — bug(singleton-scheduler): agent host-priority not
  enforced. The "Optional" follow-up calls for DM-targeting the
  preferred-host healer instead of broadcasting to ``#heads``.
* ``apps/hub/views/api/_dms.py::_ensure_dm_channel`` — the hub-side
  endpoint that lazy-creates the DM channel on first message send.
* ``docs/architecture.md`` Snake Fleet Topology — fleet healer
  naming convention (``head-<machine>``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable

log = logging.getLogger("singleton-host-check.dm")

# ---------------------------------------------------------------------------
# Configuration (env-driven)
# ---------------------------------------------------------------------------

HUB_URL = os.environ.get("SCITEX_OROCHI_HUB_URL", "https://scitex-orochi.com")
HUB_TOKEN = os.environ.get("SCITEX_OROCHI_TOKEN", "")

# Sender identity used by the DM-healer dispatch path. The DM endpoint
# resolves ``?agent=<name>`` into ``agent-<name>`` Django user, so this
# value also becomes the visible sender in the healer's DM list. Kept
# distinct from any real agent name so the DM provenance is obvious.
SCRIPT_AGENT_NAME = os.environ.get(
    "SCITEX_OROCHI_SINGLETON_CHECK_AGENT", "singleton-host-check"
)

# Template used to resolve a preferred-host name into the healer agent
# name that owns lifecycle on that host. ``{host}`` is the only allowed
# substitution. Default mirrors the ``head-<machine>`` convention used
# by the fleet (see ``docs/architecture.md`` Snake Fleet Topology).
HEALER_NAME_TEMPLATE = os.environ.get("SCITEX_OROCHI_HEALER_TEMPLATE", "head-{host}")

# Workspace slug used when resolving the DM/messages endpoint on the
# bare domain. Defaults to ``fleet`` (the canonical workspace operators
# run agents against); operators on a different workspace set this env
# var to match. Used by the ``/api/workspace/<slug>/...`` token-auth
# routes that DM-create + DM-message both go through.
WORKSPACE_SLUG = os.environ.get("SCITEX_OROCHI_WORKSPACE", "fleet")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_healer_name(host: str, template: str = HEALER_NAME_TEMPLATE) -> str:
    """Return the healer agent name on ``host`` per ``template``.

    ``template`` must contain ``{host}``; we substitute the bare host
    (no FQDN / no ``user@`` prefix) so the resulting name lines up with
    the registered agent identity (``head-spartan`` etc.). Strict
    substitution — any other ``{...}`` placeholder raises ``KeyError``
    rather than silently producing a malformed name.
    """
    bare = host.split("@")[-1].split(".")[0]
    return template.format(host=bare)


def _dm_channel_name(sender: str, healer: str) -> str:
    """Return the canonical ``dm:<a>|<b>`` channel name for the pair.

    Spec v3 §2.3: principal keys are sorted so the channel name is
    initiator-independent, which makes ``_ensure_dm_channel`` on the
    hub side idempotent.
    """
    keys = sorted([f"agent:{sender}", f"agent:{healer}"])
    return "dm:" + "|".join(keys)


def _format_dm_for_healer(warning: dict) -> str:
    """Render the per-warning DM body sent to the preferred-host healer.

    Action-oriented and stable — the healer parses neither, but humans
    reading the DM should immediately see *what* to do (run ``sac
    singleton-reconcile --execute``) and *why* (the priority drift).
    """
    return (
        f"[#250 singleton-host-check] preferred-host yield needed\n"
        f"agent: {warning['agent']}\n"
        f"current_machine: {warning['current_machine']} "
        f"(priority #{warning['current_rank']})\n"
        f"preferred_host: {warning['preferred_host']} "
        f"(priority #{warning['preferred_rank']}) — you\n"
        f"priority_list: {' > '.join(warning['priority_list'])}\n"
        f"action: run `sac singleton-reconcile --execute` to claim "
        f"{warning['agent']} from {warning['current_machine']}"
    )


def _post_dm_to_healer(healer: str, text: str) -> bool:
    """POST a DM to ``healer`` via the workspace messages endpoint.

    Returns ``True`` on a 2xx response and ``False`` (with a warning
    logged) otherwise. The channel name is the canonical ``dm:`` form
    so the hub's ``_ensure_dm_channel`` lazy-create runs idempotently
    on first contact.

    Symmetric with the legacy ``_post_to_heads`` w.r.t. auth — passes
    the workspace token in the JSON body and ``?agent=`` on the query
    string so the eventual token-auth path (sibling work item) can be
    added to ``api_messages`` without changing this call site.
    """
    try:
        import urllib.request

        channel = _dm_channel_name(SCRIPT_AGENT_NAME, healer)
        data = json.dumps(
            {
                "token": HUB_TOKEN,
                "channel": channel,
                "text": text,
            }
        ).encode()
        url = (
            f"{HUB_URL}/api/workspace/{WORKSPACE_SLUG}/messages/"
            f"?token={HUB_TOKEN}&agent={SCRIPT_AGENT_NAME}"
        )
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except (
        Exception
    ) as exc:  # stx-allow: fallback (reason: hub may be unreachable during check)
        log.warning("Failed to DM healer %s: %s", healer, exc)
        return False


def dispatch_dm_warnings(
    warnings: list[dict],
    *,
    template: str = HEALER_NAME_TEMPLATE,
    post: Callable[[str, str], bool] = _post_dm_to_healer,
) -> list[dict]:
    """Resolve + DM the preferred-host healer for each warning.

    Returns a list of ``{agent, healer, ok}`` records — the caller
    prints these so operators can see at a glance which DMs landed.
    ``post`` is injectable so the unit tests can capture the call
    shape without touching the network.
    """
    results: list[dict] = []
    for w in warnings:
        try:
            healer = _resolve_healer_name(w["preferred_host"], template)
        except (KeyError, IndexError, ValueError) as exc:
            log.warning(
                "Could not resolve healer for host %s via template %r: %s",
                w.get("preferred_host"),
                template,
                exc,
            )
            results.append({"agent": w.get("agent"), "healer": None, "ok": False})
            continue
        ok = post(healer, _format_dm_for_healer(w))
        results.append({"agent": w["agent"], "healer": healer, "ok": ok})
    return results


__all__ = [
    "HEALER_NAME_TEMPLATE",
    "SCRIPT_AGENT_NAME",
    "WORKSPACE_SLUG",
    "_resolve_healer_name",
    "_dm_channel_name",
    "_format_dm_for_healer",
    "_post_dm_to_healer",
    "dispatch_dm_warnings",
]
