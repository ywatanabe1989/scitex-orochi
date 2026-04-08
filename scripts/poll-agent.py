#!/usr/bin/env python3
"""Poll-based Orochi agent -- checks for new messages and responds via Claude."""

from __future__ import annotations

import asyncio
import os
import subprocess

AGENT_NAME = os.environ.get("SCITEX_OROCHI_AGENT", "poll-agent")
HOST = os.environ.get("SCITEX_OROCHI_HOST", "127.0.0.1")
PORT = os.environ.get("SCITEX_OROCHI_PORT", "9559")
TOKEN = os.environ.get("SCITEX_OROCHI_TOKEN", "")
CHANNELS = os.environ.get("SCITEX_OROCHI_CHANNELS", "#general").split(",")
POLL_INTERVAL = int(os.environ.get("SCITEX_OROCHI_POLL_INTERVAL", "10"))
MODEL = os.environ.get("SCITEX_OROCHI_MODEL", "haiku")

last_seen_ts: dict[str, str] = {}


async def poll_messages() -> list[dict]:
    """Fetch recent messages from all channels."""
    from scitex_orochi._client import OrochiClient

    new_messages = []
    async with OrochiClient(
        AGENT_NAME, host=HOST, port=int(PORT), token=TOKEN, channels=CHANNELS
    ) as client:
        for ch in CHANNELS:
            history = await client.query_history(ch, limit=5)
            if not history:
                continue
            cutoff = last_seen_ts.get(ch, "")
            for msg in history:
                ts = msg.get("ts", "")
                if ts <= cutoff:
                    continue
                sender = msg.get("sender", "")
                if sender == AGENT_NAME:
                    continue
                content = msg.get("content", "")
                if f"@{AGENT_NAME}" in content or not cutoff:
                    new_messages.append(
                        {"channel": ch, "sender": sender, "content": content, "ts": ts}
                    )
            # Update last seen
            if history:
                latest = max(m.get("ts", "") for m in history)
                if latest > last_seen_ts.get(ch, ""):
                    last_seen_ts[ch] = latest
    return new_messages


async def respond(channel: str, sender: str, content: str) -> None:
    """Generate a response via Claude and send it back."""
    prompt = (
        f"You are {AGENT_NAME}, an AI agent on the Orochi communication hub. "
        f'{sender} sent this message on {channel}: "{content}"\n\n'
        f"Reply briefly and helpfully. If asked to introduce yourself, "
        f"explain you are an orchestrator agent running on ywata-note-win."
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", MODEL, "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        reply = result.stdout.strip()
        if not reply:
            reply = "(no response generated)"
    except Exception as exc:
        reply = f"(error: {exc})"

    # Send reply via CLI
    from scitex_orochi._client import OrochiClient

    async with OrochiClient(
        AGENT_NAME, host=HOST, port=int(PORT), token=TOKEN, channels=[channel]
    ) as client:
        await client.send(channel, reply)
    print(f"[{channel}] {AGENT_NAME}: {reply[:80]}")


async def main_loop() -> None:
    print(f"Poll agent '{AGENT_NAME}' starting")
    print(f"  Host: {HOST}:{PORT}")
    print(f"  Channels: {CHANNELS}")
    print(f"  Model: {MODEL}")
    print(f"  Poll interval: {POLL_INTERVAL}s")

    # Initial poll to set baseline (don't respond to old messages)
    try:
        await poll_messages()
        print("  Baseline set, listening for new messages...")
    except Exception as exc:
        print(f"  Warning: initial poll failed: {exc}")

    while True:
        try:
            messages = await poll_messages()
            for msg in messages:
                print(f"[{msg['channel']}] {msg['sender']}: {msg['content']}")
                await respond(msg["channel"], msg["sender"], msg["content"])
        except Exception as exc:
            print(f"Poll error: {exc}")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\nStopped.")
