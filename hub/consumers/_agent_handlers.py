"""Per-frame handler functions for :class:`hub.consumers.AgentConsumer`.

Pulled out of ``_agent.py`` so the consumer class itself stays under the
512-line cap. Each handler is a free async function that takes the
consumer instance as its first argument; the consumer's ``receive_json``
just dispatches to them.
"""

from __future__ import annotations

import time

from hub.models import normalize_channel_name

from ._groups import _sanitize_group, log
from ._helpers import _load_agent_channel_subs, _persist_agent_subscription

# WebSocket close code reserved for "this WS got evicted because another
# process holds the same agent identity". Custom 4xxx range is allowed
# by RFC 6455; 4409 mirrors HTTP 409 Conflict for readability.
DUPLICATE_IDENTITY_CLOSE_CODE = 4409
DUPLICATE_IDENTITY_REASON = "duplicate_identity"


async def handle_register(consumer, content):
    """Hydrate channel subscriptions + agent metadata, then announce.

    Subscription state is sourced **only** from the persisted
    ``ChannelMembership`` rows. Client-supplied ``channels`` arrays in the
    register frame (``content["channels"]`` / ``payload["channels"]``) are
    **ignored** — accepting them would let any agent opt itself into any
    channel by self-declaration, bypassing the ACL gate on subscribe.
    Fix for scitex-orochi#251 (private-channel delivery leak).

    scitex-orochi#255 — singleton cardinality enforcement runs FIRST. If
    a sibling channel already holds this ``agent_name`` and reports a
    different ``instance_id``, we run the decision rule and either:

      - close THIS connection (incumbent wins) with code 4409 and reason
        ``"duplicate_identity"``; OR
      - close the OTHER connection (challenger wins) via the channel
        layer and proceed with the normal register flow.

    Legacy clients that don't report ``instance_id``/``start_ts_unix`` in
    the register frame fall through to the pre-#255 permissive
    multi-connection behavior with a logged WARNING (no regression for
    older agent_meta.py installs).
    """
    payload = content.get("payload", {})

    # ── #255 singleton enforcement ───────────────────────────────────
    challenger_instance_id = (payload.get("instance_id") or "").strip()
    raw_challenger_ts = payload.get("start_ts_unix")
    try:
        challenger_start_ts_unix = (
            float(raw_challenger_ts) if raw_challenger_ts is not None else None
        )
    except (TypeError, ValueError):
        challenger_start_ts_unix = None

    closed_self = await _enforce_singleton(
        consumer,
        challenger_instance_id=challenger_instance_id,
        challenger_start_ts_unix=challenger_start_ts_unix,
    )
    if closed_self:
        # We sent the close — abort the register flow so we don't write
        # a half-registered identity into the registry.
        return
    # ── /#255 ────────────────────────────────────────────────────────

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
        # #257 canonical heartbeat metadata — pass through so the
        # registry's prev-preserve logic can store the per-process
        # identity. Without these, singleton enforcement on a future
        # second register frame can't find an incumbent identity.
        "instance_id": challenger_instance_id,
        "start_ts_unix": challenger_start_ts_unix,
    }

    from hub.registry import register_agent, set_connection_identity

    register_agent(consumer.agent_name, consumer.workspace_id, consumer.agent_meta)
    # Track per-channel identity so a future challenger can be compared
    # against this connection (#255). Safe no-op when instance_id is
    # empty — list_sibling_channels still emits the entry but
    # decide_singleton_winner falls through to legacy permissive mode.
    set_connection_identity(
        channel_name=consumer.channel_name,
        agent_name=consumer.agent_name,
        instance_id=challenger_instance_id,
        start_ts_unix=challenger_start_ts_unix,
    )

    await consumer.channel_layer.group_send(
        consumer.workspace_group,
        {
            "type": "agent.info",
            "agent": consumer.agent_name,
            "info": consumer.agent_meta,
        },
    )

    await consumer.send_json({"type": "registered", "channels": channels})


async def _enforce_singleton(
    consumer,
    challenger_instance_id: str,
    challenger_start_ts_unix: float | None,
) -> bool:
    """Apply the #255 singleton decision rule for ``consumer``'s register frame.

    Returns ``True`` when this connection (the challenger) was closed
    and the caller should abort the register flow. Returns ``False``
    when either no conflict was detected or the incumbent was evicted
    (this consumer keeps the claim and registration should proceed).
    """
    from hub.registry import (
        decide_singleton_winner,
        list_sibling_channels,
        record_singleton_conflict,
    )

    siblings = list_sibling_channels(
        consumer.agent_name, exclude=consumer.channel_name
    )
    if not siblings:
        return False

    # Compare against EACH sibling so a third-comer doesn't accidentally
    # admit itself by colluding with a stale half-disconnected sibling.
    for sib in siblings:
        outcome = decide_singleton_winner(
            incumbent_instance_id=sib.get("instance_id") or "",
            incumbent_start_ts_unix=sib.get("start_ts_unix"),
            challenger_instance_id=challenger_instance_id,
            challenger_start_ts_unix=challenger_start_ts_unix,
        )
        if outcome == "incumbent" and (
            not sib.get("instance_id") or not challenger_instance_id
        ):
            # Legacy permissive mode — at least one side can't enforce.
            # Log for visibility but admit both connections.
            log.warning(
                "Singleton check skipped for agent %s — legacy client "
                "(missing instance_id). Allowing concurrent connections; "
                "upgrade agent_meta.py to enable enforcement.",
                consumer.agent_name,
            )
            continue
        if outcome == "incumbent" and sib.get(
            "instance_id"
        ) == challenger_instance_id:
            # Same process re-registering (transient WS reconnect).
            # Not a conflict — let the new connection register and
            # naturally supersede the stale sibling.
            continue
        if outcome == "incumbent":
            # Strict-mode incumbent wins → close THIS connection.
            record_singleton_conflict(
                name=consumer.agent_name,
                winner_instance_id=sib.get("instance_id") or "",
                loser_instance_id=challenger_instance_id,
                winner_start_ts_unix=sib.get("start_ts_unix"),
                loser_start_ts_unix=challenger_start_ts_unix,
                outcome="incumbent",
            )
            try:
                await consumer.send_json(
                    {
                        "type": "error",
                        "code": DUPLICATE_IDENTITY_REASON,
                        "message": (
                            "another process already holds this agent "
                            "identity (older start_ts_unix wins)"
                        ),
                        "winner_instance_id": sib.get("instance_id") or "",
                    }
                )
            except Exception:
                pass
            await consumer.close(code=DUPLICATE_IDENTITY_CLOSE_CODE)
            return True
        # outcome == "challenger" → evict the sibling.
        record_singleton_conflict(
            name=consumer.agent_name,
            winner_instance_id=challenger_instance_id,
            loser_instance_id=sib.get("instance_id") or "",
            winner_start_ts_unix=challenger_start_ts_unix,
            loser_start_ts_unix=sib.get("start_ts_unix"),
            outcome="challenger",
        )
        await _evict_sibling(consumer, sib.get("channel_name", ""))
    return False


async def _evict_sibling(consumer, sibling_channel_name: str) -> None:
    """Send a force-close hint to a sibling consumer over the channel layer.

    Django Channels lets us address a single consumer by its
    ``channel_name``. We deliver a custom event whose ``type`` maps to
    the consumer's ``singleton_evict`` handler (defined on
    ``AgentConsumer``); that handler then performs the WebSocket close.
    Best-effort — if the sibling is already gone the channel layer just
    drops the message and the next heartbeat-stale sweep finishes the
    cleanup.
    """
    if not sibling_channel_name:
        return
    try:
        await consumer.channel_layer.send(
            sibling_channel_name,
            {
                "type": "singleton.evict",
                "reason": DUPLICATE_IDENTITY_REASON,
                "code": DUPLICATE_IDENTITY_CLOSE_CODE,
            },
        )
    except Exception as e:
        log.warning(
            "Failed to evict sibling %s for agent %s: %s",
            sibling_channel_name,
            consumer.agent_name,
            e,
        )


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
        "load_avg_1m": payload.get("load_avg_1m"),
        "mem_used_percent": payload.get("mem_used_percent"),
        "mem_total_mb": payload.get("mem_total_mb"),
        "disk_used_percent": payload.get("disk_used_percent"),
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
