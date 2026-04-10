"""Orochi auto-connect sidecar (moved from scitex_agent_container.orochi_connector).

Registers an agent with the Orochi hub on startup in a background daemon
thread. Runs entirely in scitex-orochi now — scitex-agent-container has no
knowledge of Orochi and never spawns this sidecar itself.

The sidecar is expected to be started by scitex-orochi's launch dispatcher
AFTER ``scitex_agent_container.lifecycle.agent_start()`` returns successfully,
so that the underlying screen session is up and running before the hub
registration happens.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
import threading

from .spec import OrochiSpec

log = logging.getLogger("scitex-orochi.bridge.connector")


def resolve_orochi_token(orochi: OrochiSpec, agent_env: dict[str, str]) -> str:
    """Resolve the Orochi workspace token (env → agent yaml → login shell).

    Mirrors the logic in :mod:`mcp` (the two call sites used to live in
    different packages; now they share this helper).
    """
    token = agent_env.get(orochi.token_env, "")
    if token:
        return token

    token = os.environ.get(orochi.token_env, "")
    if token:
        return token

    try:
        result = subprocess.run(
            ["bash", "-l", "-c", f"echo ${orochi.token_env}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        token = result.stdout.strip()
        if token:
            log.info("Resolved %s via bash login shell fallback", orochi.token_env)
            return token
    except Exception as exc:
        log.debug("bash -l token lookup failed: %s", exc)

    return ""


def start_orochi_sidecar(
    *,
    agent_name: str,
    orochi: OrochiSpec,
    agent_env: dict[str, str],
    agent_labels: dict[str, str],
) -> threading.Thread | None:
    """Start the Orochi connection in a background daemon thread.

    Returns the thread (useful for testing), or None if Orochi is not
    enabled or the token cannot be resolved.
    """
    if not orochi.is_enabled:
        return None

    token = resolve_orochi_token(orochi, agent_env)
    if not token:
        log.warning(
            "Orochi token env var '%s' not set -- skipping auto-connect. "
            "Fix: export %s=<your-token>",
            orochi.token_env,
            orochi.token_env,
        )
        return None

    thread = threading.Thread(
        target=_run_connector,
        args=(agent_name, orochi, token, agent_labels),
        name=f"orochi-{agent_name}",
        daemon=True,
    )
    thread.start()
    log.info(
        "Orochi sidecar started for '%s' -> hosts=%s port=%d",
        agent_name,
        orochi.hosts,
        orochi.port,
    )
    return thread


def _run_connector(
    agent_name: str,
    orochi: OrochiSpec,
    token: str,
    agent_labels: dict[str, str],
) -> None:
    """Run the async Orochi connection loop in a new event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_connect_loop(agent_name, orochi, token, agent_labels))
    except Exception:
        log.error("Orochi connector crashed", exc_info=True)
    finally:
        loop.close()


async def _try_host(
    OrochiClient: type,
    host: str,
    agent_name: str,
    orochi: OrochiSpec,
    token: str,
    machine: str,
    role: str,
    channels: list[str],
) -> object | None:
    """Try connecting to a single host. Returns the client on success."""
    try:
        client = OrochiClient(
            name=agent_name,
            host=host,
            port=orochi.port,
            channels=channels,
            token=token,
            machine=machine,
            role=role,
            agent_id=f"{agent_name}@{machine}",
            ws_path=orochi.ws_path,
        )
        await asyncio.wait_for(client.connect(), timeout=10)
        return client
    except Exception as exc:
        log.warning("Orochi host %s:%d FAILED: %s", host, orochi.port, exc)
        return None


async def _connect_loop(
    agent_name: str,
    orochi: OrochiSpec,
    token: str,
    agent_labels: dict[str, str],
) -> None:
    """Connect to Orochi with multi-host fallback and retry logic."""
    try:
        from scitex_orochi._client import OrochiClient
    except ImportError:
        log.error(
            "scitex-orochi not installed -- cannot auto-connect. "
            "Fix: pip install scitex-orochi"
        )
        return

    machine = agent_labels.get("machine", platform.node())
    role = agent_labels.get("role", "")
    channels = orochi.channels or ["#general"]
    attempt = 0

    while True:
        attempt += 1
        max_retries = orochi.reconnect_max_retries
        if max_retries > 0 and attempt > max_retries:
            log.error(
                "Orochi connection failed after %d attempts -- giving up",
                max_retries,
            )
            return

        client = None
        results: list[str] = []
        connected_host = None
        for host in orochi.hosts:
            client = await _try_host(
                OrochiClient,
                host,
                agent_name,
                orochi,
                token,
                machine,
                role,
                channels,
            )
            if client is not None:
                results.append(f"{host}:OK")
                connected_host = host
                break
            results.append(f"{host}:FAIL")

        status_line = " | ".join(results)
        if connected_host:
            log.info(
                "Orochi connection report: [%s] -- connected via %s "
                "(%s@%s channels=%s)",
                status_line,
                connected_host,
                agent_name,
                machine,
                channels,
            )
        else:
            log.error(
                "Orochi connection report: [%s] -- ALL HOSTS FAILED (attempt %d)",
                status_line,
                attempt,
            )

        if client is not None:
            try:
                try:
                    await client.start_heartbeat(interval=orochi.heartbeat_interval)
                except Exception:
                    log.debug("Heartbeat not supported by server, skipping")

                try:
                    await client.update_status(status="online", current_task="ready")
                except Exception:
                    log.debug("Status update not supported by server, skipping")

                async for msg in client.listen():
                    log.debug(
                        "Orochi msg [%s] %s: %s",
                        msg.payload.get("channel", "?"),
                        msg.sender,
                        msg.payload.get("content", "")[:80],
                    )
            except Exception:
                log.warning(
                    "Orochi connection lost (attempt %d)", attempt, exc_info=True
                )

        log.info("Reconnecting to Orochi in %ds...", orochi.reconnect_interval)
        await asyncio.sleep(orochi.reconnect_interval)
