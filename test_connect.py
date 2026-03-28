#!/usr/bin/env python3
"""Quick test: connect an agent to Orochi and send a message."""

import asyncio
import json
import platform

import websockets


async def main():
    uri = "ws://orochi.scitex.ai:9559"
    # Try direct NAS connection if external fails
    fallback_uri = "ws://192.168.0.102:9559"

    for target in [uri, fallback_uri]:
        try:
            print(f"Connecting to {target}...")
            ws = await asyncio.wait_for(websockets.connect(target), timeout=5)
            break
        except Exception as e:
            print(f"  Failed: {e}")
            ws = None

    if not ws:
        print("Could not connect to any Orochi server")
        return

    # Register
    reg = {
        "type": "register",
        "sender": "master-agent",
        "id": "test-001",
        "ts": "",
        "payload": {
            "channels": ["#general"],
            "machine": platform.node(),
            "role": "orchestrator",
            "agent_id": f"master-agent@{platform.node()}",
            "project": "master-agent",
        },
    }
    await ws.send(json.dumps(reg))
    ack = await ws.recv()
    print(f"Register ack: {ack[:100]}")

    # Send a message
    msg = {
        "type": "message",
        "sender": "master-agent",
        "id": "msg-001",
        "ts": "",
        "payload": {
            "channel": "#general",
            "content": "Hello from master-agent! Orochi is alive.",
            "metadata": {},
        },
    }
    await ws.send(json.dumps(msg))
    ack2 = await ws.recv()
    print(f"Message ack: {ack2[:100]}")

    # Status update
    status = {
        "type": "status_update",
        "sender": "master-agent",
        "id": "status-001",
        "ts": "",
        "payload": {
            "status": "online",
            "current_task": "Orochi deployment verification",
            "project": "master-agent",
        },
    }
    await ws.send(json.dumps(status))
    ack3 = await ws.recv()
    print(f"Status ack: {ack3[:100]}")

    print("\nAgent connected! Check orochi.scitex.ai dashboard.")
    print("Press Ctrl+C to disconnect.")

    try:
        async for raw in ws:
            data = json.loads(raw)
            if data.get("type") not in ("ack",):
                print(f"  Received: {json.dumps(data)[:120]}")
    except (KeyboardInterrupt, websockets.ConnectionClosed):
        pass
    finally:
        await ws.close()


if __name__ == "__main__":
    asyncio.run(main())
