"""Top-level daemon glue for worker-progress (todo#272).

Wires the ``_client.HubWSClient`` loop into the ``_digest.DigestCoalescer``
and the ``_digest.MentionPolicy`` bypass path. Owns signal handling
and the ~1 s tick that drains the coalescer.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Optional

from . import AGENT_NAME, DIGEST_CHANNEL, SUBSCRIBE_CHANNELS
from ._client import HubWSClient
from ._config import build_ws_uri, resolve_token, resolve_ws_url
from ._digest import DigestCoalescer, InboundEvent, MentionPolicy

log = logging.getLogger("worker-progress.daemon")

# How often the tick loop wakes up to maybe flush a digest. Small
# relative to the 60 s window so we emit close to the boundary.
TICK_INTERVAL_S = 1.0


def _as_inbound(frame: dict) -> Optional[InboundEvent]:
    """Project a raw hub frame into an ``InboundEvent``.

    Returns ``None`` for frames that aren't user messages (acks,
    presence, info, pong, etc.).
    """
    if frame.get("type") != "message":
        return None
    channel = str(frame.get("channel") or "")
    sender = str(frame.get("sender") or "")
    text = str(frame.get("text") or "")
    # Drop our own echoed posts so we never digest ourselves.
    if sender == AGENT_NAME or sender == f"agent-{AGENT_NAME}":
        return None
    is_dm = channel.startswith("dm:")
    ev = InboundEvent(
        channel=channel,
        sender=sender,
        text=text,
        ts=time.time(),
        is_dm=is_dm,
    )
    ev.mentions_self = MentionPolicy.is_mention(ev)
    return ev


async def _tick_loop(
    client: HubWSClient,
    coalescer: DigestCoalescer,
    stop_event: asyncio.Event,
    once: bool = False,
) -> None:
    """Wake every ``TICK_INTERVAL_S`` and flush the coalescer.

    With ``once=True``, runs one flush (honouring the window) then
    exits — used by the ``--once`` smoke-test flag.
    """
    while not stop_event.is_set():
        try:
            line = coalescer.flush()
            if line:
                await client.send_message(DIGEST_CHANNEL, line)
                log.info("digest emitted: %s", line)
        except Exception:  # noqa: BLE001 — log + continue
            log.exception("digest flush failed")
        if once:
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_INTERVAL_S)
        except asyncio.TimeoutError:
            pass


async def _ingest_loop(
    client: HubWSClient,
    coalescer: DigestCoalescer,
    stop_event: asyncio.Event,
) -> None:
    """Consume hub frames, route mentions, push the rest into the coalescer."""
    async for frame in client.run():
        if stop_event.is_set():
            break
        ev = _as_inbound(frame)
        if ev is None:
            continue
        if ev.mentions_self:
            # Bypass the throttle — ack immediately.
            reply_channel = ev.channel or DIGEST_CHANNEL
            try:
                await client.send_message(reply_channel, MentionPolicy.ack_line(ev))
                log.info(
                    "mention ack posted to %s (from %s)", reply_channel, ev.sender
                )
            except Exception:  # noqa: BLE001
                log.exception("mention ack send failed")
            # Also record in the coalescer so the digest still counts it.
        coalescer.push(ev)


async def run(
    dry_run: bool = False,
    once: bool = False,
    url: str = "",
    token: str = "",
) -> int:
    """Start the daemon. Returns process exit code."""
    ws_base = url or resolve_ws_url()
    tok = token or resolve_token()
    if not tok and not dry_run:
        log.error(
            "no SCITEX_OROCHI_TOKEN / SCITEX_OROCHI_WORKSPACE_TOKEN in env; "
            "refusing to connect. Set the env var (see scripts/client/install/"
            "bootstrap-host.sh for the .env file shape) or pass --dry-run."
        )
        return 2
    uri = build_ws_uri(ws_base, tok, AGENT_NAME)
    log.info(
        "worker-progress starting (dry_run=%s once=%s ws=%s)",
        dry_run,
        once,
        ws_base,
    )

    client = HubWSClient(
        uri=uri,
        agent_name=AGENT_NAME,
        channels=SUBSCRIBE_CHANNELS,
        machine="",
        project="scitex-orochi",
        dry_run=dry_run,
    )
    coalescer = DigestCoalescer(now=time.monotonic)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        log.info("signal received, stopping…")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            # Windows / restricted environments — fall back to
            # default handler and rely on KeyboardInterrupt.
            pass

    tick_task = asyncio.create_task(
        _tick_loop(client, coalescer, stop_event, once=once)
    )

    if dry_run or once:
        # Dry-run / once modes skip the real WS hookup; just emit the
        # tick cycle (at most once) and exit. This is what the install
        # smoke-test flag exercises.
        try:
            await tick_task
        finally:
            await client.stop()
        return 0

    ingest_task = asyncio.create_task(_ingest_loop(client, coalescer, stop_event))

    try:
        await stop_event.wait()
    finally:
        # Flush any pending digest before we tear down.
        try:
            final = coalescer.flush()
            if final:
                await client.send_message(DIGEST_CHANNEL, final)
                log.info("final digest emitted on shutdown: %s", final)
        except Exception:  # noqa: BLE001
            log.exception("final flush failed")
        await client.stop()
        ingest_task.cancel()
        tick_task.cancel()
        for t in (ingest_task, tick_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    log.info("worker-progress exited cleanly")
    return 0
