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


def discover_server(
    token: str,
    known_hosts: list[str],
    port: int = 8559,
) -> dict[str, str] | None:
    """Try each known host's /api/discover/ endpoint to resolve server URLs.

    Returns a dict with keys ``ws_url``, ``http_url``, ``workspace`` on
    success, or ``None`` if all hosts fail.  This is backward-compatible:
    callers fall back to the existing host list when discovery fails.
    """
    import json as _json
    import ssl
    import urllib.error
    import urllib.request

    # Accept self-signed certs for local dev
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for host in known_hosts:
        for scheme in ("https", "http"):
            url = f"{scheme}://{host}:{port}/api/discover/?token={token}"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                    if resp.status == 200:
                        data = _json.loads(resp.read().decode())
                        log.info(
                            "Server discovery via %s:%d -> workspace=%s",
                            host,
                            port,
                            data.get("workspace", "?"),
                        )
                        return data
            except Exception as exc:
                log.debug("Discovery %s:%d (%s) failed: %s", host, port, scheme, exc)
    log.warning("Server discovery failed on all hosts, falling back to host list")
    return None


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
    orochi_machine: str,
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
            orochi_machine=orochi_machine,
            role=role,
            agent_id=f"{agent_name}@{orochi_machine}",
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

    orochi_machine = agent_labels.get("orochi_machine", platform.node())
    role = agent_labels.get("role", "")
    channels = orochi.channels or ["#general"]
    attempt = 0

    # Try token-based server discovery (runs once, result cached for loop)
    discovered = discover_server(token, orochi.hosts, orochi.port)
    if discovered:
        # Extract host from the discovered http_url for use in _try_host
        from urllib.parse import urlparse

        parsed = urlparse(discovered["http_url"])
        discovered_host = parsed.hostname or ""
        if discovered_host:
            # Prepend discovered host so it's tried first, keep originals as fallback
            hosts = [discovered_host] + [
                h for h in orochi.hosts if h != discovered_host
            ]
            log.info(
                "Discovery resolved workspace=%s, using hosts=%s",
                discovered.get("workspace"),
                hosts,
            )
        else:
            hosts = list(orochi.hosts)
    else:
        hosts = list(orochi.hosts)

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
        for host in hosts:
            client = await _try_host(
                OrochiClient,
                host,
                agent_name,
                orochi,
                token,
                orochi_machine,
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
                orochi_machine,
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
                    await client.update_status(status="online", orochi_current_task="ready")
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
