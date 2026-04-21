"""Per-frame handler functions for :class:`hub.consumers.AgentConsumer`.

Pulled out of ``_agent.py`` so the consumer class itself stays under the
512-line cap. Each handler is a free async function that takes the
consumer instance as its first argument; the consumer's ``receive_json``
just dispatches to them.
"""

from __future__ import annotations

import time

from hub.models import normalize_channel_name

from ._groups import _sanitize_group
from ._helpers import _load_agent_channel_subs, _persist_agent_subscription


async def handle_register(consumer, content):
    """Hydrate channel subscriptions + agent metadata, then announce.

    Subscription state is sourced **only** from the persisted
    ``ChannelMembership`` rows. Client-supplied ``channels`` arrays in the
    register frame (``content["channels"]`` / ``payload["channels"]``) are
    **ignored** — accepting them would let any agent opt itself into any
    channel by self-declaration, bypassing the ACL gate on subscribe.
    Fix for scitex-orochi#251 (private-channel delivery leak).
    """
    payload = content.get("payload", {})
    persisted = await _load_agent_channel_subs(
        consumer.workspace_id, consumer.agent_name
    )
    channels = list(persisted)
    # Spec v3 §3.1 — DM channels auto-subscribed at connect must also
    # appear in agent_meta["channels"] so the chat_message filter
    # forwards DM events.
    for dm_name in getattr(consumer, "_dm_channel_names", []) or []:
        if dm_name not in channels:
            channels.insert(0, dm_name)
    for ch_name in channels:
        group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
        await consumer.channel_layer.group_add(group, consumer.channel_name)

    consumer.agent_meta = {
        "agent_id": payload.get("agent_id", consumer.agent_name),
        "project": payload.get("project", ""),
        "machine": payload.get("machine", ""),
        # #257 / lead msg#15578 — live hostname(1) reported by the
        # client. Never derived from auth / source IP on the hub side;
        # always what the agent process's own ``socket.gethostname()``
        # / ``os.hostname()`` returned. Surfaced in the dashboard
        # payload as the authoritative "where is this agent running"
        # field (distinct from the YAML ``machine`` config label).
        "hostname": payload.get("hostname", ""),
        # todo#55: canonical FQDN from the heartbeat (display-only).
        "hostname_canonical": payload.get("hostname_canonical", ""),
        "role": payload.get("role", ""),
        "model": payload.get("model", ""),
        "workdir": payload.get("workdir", ""),
        "icon": payload.get("icon", ""),
        "icon_emoji": payload.get("icon_emoji", ""),
        "icon_text": payload.get("icon_text", ""),
        "color": payload.get("color", ""),
        "multiplexer": payload.get("multiplexer", ""),
        "channels": channels,
        "claude_md": payload.get("claude_md", ""),
    }

    from hub.registry import register_agent

    register_agent(consumer.agent_name, consumer.workspace_id, consumer.agent_meta)

    # scitex-orochi#451 — mark the consumer as registered. The
    # ``receive_json`` dispatch uses this flag to deny ``message`` frames
    # from un-registered connections so orphan-on-reconnect failures
    # surface as a loud error instead of a silent deafness. The flag
    # flips True only AFTER agent_meta + group_adds are in place, so a
    # concurrent message frame either arrives before register completes
    # (rejected) or after (accepted + delivered).
    consumer._registered = True

    await consumer.channel_layer.group_send(
        consumer.workspace_group,
        {
            "type": "agent.info",
            "agent": consumer.agent_name,
            "info": consumer.agent_meta,
        },
    )

    await consumer.send_json({"type": "registered", "channels": channels})


async def handle_subscription(consumer, content, subscribe: bool):
    """Add or remove a persistent channel subscription for the agent."""
    payload = content.get("payload", {})
    raw_name = payload.get("channel") or content.get("channel") or ""
    if not raw_name:
        await consumer.send_json(
            {
                "type": "error",
                "code": "channel_required",
                "message": "subscribe/unsubscribe requires a channel name",
            }
        )
        return
    ch_name = normalize_channel_name(raw_name)
    ok = await _persist_agent_subscription(
        consumer.workspace_id, consumer.agent_name, ch_name, subscribe
    )
    if not ok:
        await consumer.send_json(
            {
                "type": "error",
                "code": "subscription_failed",
                "message": f"could not update subscription for {ch_name}",
            }
        )
        return
    group = _sanitize_group(f"channel_{consumer.workspace_id}_{ch_name}")
    if subscribe:
        await consumer.channel_layer.group_add(group, consumer.channel_name)
    else:
        await consumer.channel_layer.group_discard(group, consumer.channel_name)
    subs = list(getattr(consumer, "agent_meta", {}).get("channels", []) or [])
    if subscribe and ch_name not in subs:
        subs.append(ch_name)
    if not subscribe and ch_name in subs:
        subs.remove(ch_name)
    if hasattr(consumer, "agent_meta"):
        consumer.agent_meta["channels"] = subs
    from hub.registry import register_agent

    register_agent(
        consumer.agent_name,
        consumer.workspace_id,
        getattr(consumer, "agent_meta", {"channels": subs}),
    )
    await consumer.channel_layer.group_send(
        consumer.workspace_group,
        {
            "type": "agent.info",
            "agent": consumer.agent_name,
            "info": getattr(consumer, "agent_meta", {}),
        },
    )
    await consumer.send_json(
        {
            "type": "subscribed" if subscribe else "unsubscribed",
            "channel": ch_name,
            "channels": subs,
        }
    )


async def handle_pong(consumer, content):
    """Compute RTT for hub→agent ping echo and broadcast to dashboards."""
    payload = content.get("payload") or {}
    sent_ts = payload.get("ts") or content.get("ts")
    if isinstance(sent_ts, (int, float)):
        rtt_ms = max(0.0, (time.time() - float(sent_ts)) * 1000.0)
        from hub.registry import update_pong

        update_pong(consumer.agent_name, rtt_ms)
        await consumer.channel_layer.group_send(
            consumer.workspace_group,
            {
                "type": "agent.pong",
                "agent": consumer.agent_name,
                "rtt_ms": rtt_ms,
                "ts": time.time(),
            },
        )


async def handle_echo_pong(consumer, content):
    """Lookup the nonce, compute RTT, update echo registry fields (#259).

    The hub publisher (in ``_echo._hub_echo_loop``) keeps a per-consumer
    ``_echo_inflight`` dict mapping nonce -> sent_at. A matching
    ``echo_pong`` frame yields the round-trip time and triggers
    ``update_echo_pong``, which is what flips the 4th LED green.

    Unknown nonces are dropped silently — they happen naturally on
    reconnects (publisher state is per-consumer, lost on disconnect)
    and shouldn't disturb the dashboard or log noise.
    """
    nonce = content.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return
    inflight = getattr(consumer, "_echo_inflight", None)
    if not inflight:
        return
    sent_at = inflight.pop(nonce, None)
    if sent_at is None:
        return
    rtt_ms = max(0.0, (time.time() - float(sent_at)) * 1000.0)
    from hub.registry import update_echo_pong

    update_echo_pong(consumer.agent_name, rtt_ms)


async def handle_heartbeat(consumer, content):
    """Persist resource metrics + optional narrative fields, then broadcast."""
    payload = content.get("payload", {})
    consumer.agent_metrics = {
        "cpu_count": payload.get("cpu_count"),
        "cpu_model": payload.get("cpu_model"),
        "load_avg_1m": payload.get("load_avg_1m"),
        "load_avg_5m": payload.get("load_avg_5m"),
        "load_avg_15m": payload.get("load_avg_15m"),
        "mem_used_percent": payload.get("mem_used_percent"),
        "mem_total_mb": payload.get("mem_total_mb"),
        "mem_free_mb": payload.get("mem_free_mb"),
        # ywatanabe msg#16215 — absolute MB + per-GPU list so the
        # hub can render ``N/M GB``, ``N/M TB``, ``N/M`` GPU.
        "mem_used_mb": payload.get("mem_used_mb"),
        "disk_used_percent": payload.get("disk_used_percent"),
        "disk_total_mb": payload.get("disk_total_mb"),
        "disk_used_mb": payload.get("disk_used_mb"),
        "gpus": payload.get("gpus") or [],
        # Slurm cluster aggregates (todo#87). None on non-slurm hosts.
        "resource_source": payload.get("resource_source"),
        "cluster_nodes": payload.get("cluster_nodes"),
        "cluster_cpus_allocated": payload.get("cluster_cpus_allocated"),
        "cluster_cpus_total": payload.get("cluster_cpus_total"),
        "cluster_mem_free_mb": payload.get("cluster_mem_free_mb"),
        "cluster_mem_total_mb": payload.get("cluster_mem_total_mb"),
        "cluster_gpus_total": payload.get("cluster_gpus_total"),
        "cluster_gpus_allocated": payload.get("cluster_gpus_allocated"),
        "slurm_total_jobs": payload.get("slurm_total_jobs"),
        "slurm_running": payload.get("slurm_running"),
        "slurm_pending": payload.get("slurm_pending"),
    }

    from hub.registry import (
        set_current_task,
        set_sac_status,
        set_subagent_count,
        update_heartbeat,
    )

    update_heartbeat(consumer.agent_name, consumer.agent_metrics)

    # Allow lightweight clients to piggyback narrative fields on
    # the heartbeat rather than sending separate task_update /
    # subagents_update frames.
    if "current_task" in payload:
        set_current_task(consumer.agent_name, str(payload.get("current_task") or ""))
    if "subagent_count" in payload:
        try:
            set_subagent_count(
                consumer.agent_name, int(payload.get("subagent_count") or 0)
            )
        except (TypeError, ValueError):
            pass
    # lead msg#16005: forward the whole ``sac status --terse --json``
    # dict on every WS heartbeat too (not just the REST register path).
    # Silently drop non-dict payloads.
    sac = payload.get("sac_status")
    if isinstance(sac, dict) and sac:
        set_sac_status(consumer.agent_name, sac)

    await consumer.channel_layer.group_send(
        consumer.workspace_group,
        {
            "type": "agent.info",
            "agent": consumer.agent_name,
            "info": getattr(consumer, "agent_meta", {}),
            "metrics": consumer.agent_metrics,
        },
    )


async def handle_task_update(consumer, content):
    """Agent reports its current task — visible in the Activity tab."""
    payload = content.get("payload", {})
    task = payload.get("task", "")
    from hub.registry import mark_activity, set_current_task

    set_current_task(consumer.agent_name, task)
    mark_activity(consumer.agent_name, action=task)
    await consumer.channel_layer.group_send(
        consumer.workspace_group,
        {
            "type": "agent.info",
            "agent": consumer.agent_name,
            "info": getattr(consumer, "agent_meta", {}),
            "metrics": getattr(consumer, "agent_metrics", {}),
        },
    )


async def handle_subagents_update(consumer, content):
    """Agent reports its current subagent tree."""
    # payload = { "subagents": [ {name, task, status}, ... ] }
    payload = content.get("payload", {})
    from hub.registry import mark_activity, set_subagents

    set_subagents(consumer.agent_name, payload.get("subagents") or [])
    mark_activity(consumer.agent_name)
    await consumer.channel_layer.group_send(
        consumer.workspace_group,
        {
            "type": "agent.info",
            "agent": consumer.agent_name,
            "info": getattr(consumer, "agent_meta", {}),
            "metrics": getattr(consumer, "agent_metrics", {}),
        },
    )
