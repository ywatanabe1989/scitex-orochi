"""AgentCard projection for orochi-served A2A agents.

Mirrors the dict-shaped projection from
``scitex_agent_container.a2a._card`` (sac side, canonical for v3 YAML →
dict) but builds the **protobuf** :class:`a2a.types.AgentCard` that
the SDK requires. The SDK ships ``agent_card_to_dict()`` to flatten
the protobuf back to a JSON-friendly shape served at
``.well-known/agent-card.json``.

The orochi registry doesn't carry the full v3 YAML — it carries the
metadata the WS bridge ships in heartbeats: ``role``, ``host``,
``a2a_url``, etc. So we project from the in-memory registry entry
when present, and fall back to a minimal card naming the agent so
``.well-known`` always returns something useful.
"""

from __future__ import annotations

from typing import Any

from a2a.types import AgentCard


def _registry_entry(name: str) -> dict[str, Any] | None:
    """Look up an agent in the orochi in-memory registry.

    Returns ``None`` if the agent is not connected — callers may
    still want to project a minimal card so external tooling can
    discover the URL exists.
    """
    from hub.registry import _agents

    entry = _agents.get(name)
    if entry is None:
        return None
    # Snapshot — registry values are mutated under a lock elsewhere.
    return dict(entry)


def project_card(name: str, base_url: str = "") -> AgentCard:
    """Project the registry entry for ``name`` into an A2A AgentCard.

    Parameters
    ----------
    name:
        Agent name (matches the URL segment ``/v1/agents/<name>/``).
    base_url:
        Optional base URL for the served interface — when present
        the supported-interface URL becomes
        ``{base_url}/v1/agents/{name}/``. Empty string omits it
        (useful for in-process tests where the public URL is unknown).
    """
    entry = _registry_entry(name) or {}
    role = entry.get("role") or "agent"
    host = entry.get("host") or ""
    description = entry.get("description") or (
        f"orochi-served A2A agent: {name}"
        + (f" (role={role}" + (f", host={host})" if host else ")") if role else "")
    )

    card = AgentCard()
    card.name = name
    card.description = description
    card.version = "scitex-orochi/1"
    card.capabilities.streaming = True
    card.capabilities.push_notifications = False
    card.default_input_modes.extend(["text/plain", "application/json"])
    card.default_output_modes.extend(["text/plain", "application/json"])

    if base_url:
        iface = card.supported_interfaces.add()
        iface.url = f"{base_url.rstrip('/')}/v1/agents/{name}/"
        iface.protocol_binding = "jsonrpc"

    skill = card.skills.add()
    skill.id = f"{name}.{role}"
    skill.name = role
    skill.description = (
        entry.get("function") or f"{role} agent served via orochi A2A bridge"
    )
    tags: list[str] = ["orochi"]
    if role:
        tags.append(role)
    if host:
        tags.append(f"host:{host}")
    skill.tags.extend(sorted(set(tags)))

    return card


__all__ = ["project_card"]
