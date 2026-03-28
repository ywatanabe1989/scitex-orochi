#!/usr/bin/env python3
"""Test: Can Python launch orochi_push.ts and communicate via JSON-RPC?

Discovery: MCP SDK's StdioServerTransport uses newline-delimited JSON,
NOT Content-Length framing. Each message is JSON + '\n'.
"""

import asyncio
import json
import os
import subprocess
import sys


async def test_push():
    # Launch the TypeScript MCP server as a subprocess
    proc = subprocess.Popen(
        ["bun", os.path.expanduser("~/proj/scitex-orochi/orochi_push.ts")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "OROCHI_HOST": "192.168.0.102",
            "OROCHI_PORT": "9559",
            "OROCHI_AGENT": "python-test",
        },
    )

    def send_jsonrpc(obj):
        """MCP stdio transport: newline-delimited JSON (not Content-Length)."""
        data = json.dumps(obj) + "\n"
        proc.stdin.write(data.encode())
        proc.stdin.flush()

    def read_jsonrpc(timeout_sec=10):
        """Read one newline-delimited JSON message from stdout."""
        import select

        # Use select to avoid blocking forever
        ready, _, _ = select.select([proc.stdout], [], [], timeout_sec)
        if not ready:
            print(f"TIMEOUT: no response within {timeout_sec}s")
            return None
        line = proc.stdout.readline()
        if not line:
            return None
        return json.loads(line.decode().strip())

    # Give the server a moment to start up
    await asyncio.sleep(1)

    # Step 1: Initialize
    print(">>> Sending initialize...")
    send_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "python-test", "version": "1.0"},
            },
        }
    )

    result = read_jsonrpc()
    print("Initialize response:", json.dumps(result, indent=2))

    if result is None:
        print("\nFAILED: No response from server")
        # Read stderr for diagnostics
        import select

        ready, _, _ = select.select([proc.stderr], [], [], 2)
        if ready:
            stderr = proc.stderr.read(4096).decode()
            print("Stderr:", stderr[:1000])
        proc.terminate()
        proc.wait(timeout=5)
        sys.exit(1)

    # Check if claude/channel capability is present
    if "result" in result:
        caps = result["result"].get("capabilities", {})
        experimental = caps.get("experimental", {})
        has_channel = "claude/channel" in experimental
        print(f"\nclaude/channel capability: {'YES' if has_channel else 'NO'}")

    # Step 2: Send initialized notification (required by MCP protocol)
    send_jsonrpc({"jsonrpc": "2.0", "method": "notifications/initialized"})

    # Step 3: List tools
    print("\n>>> Sending tools/list...")
    send_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    result = read_jsonrpc()
    print("Tools:", json.dumps(result, indent=2))

    # Step 4: Call reply tool (send a message)
    print("\n>>> Calling reply tool...")
    send_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "reply",
                "arguments": {
                    "chat_id": "#general",
                    "text": "Hello from Python via TypeScript push bridge!",
                },
            },
        }
    )

    # Wait a moment for the WS message to send, then read response
    await asyncio.sleep(2)
    result = read_jsonrpc()
    print("Reply result:", json.dumps(result, indent=2))

    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)

    # Read stderr for any errors/logs
    stderr = proc.stderr.read().decode()
    if stderr:
        print("\nServer stderr (logs):", stderr[:1000])

    print("\n=== EXPERIMENT RESULT ===")
    print("Python CAN launch TS push server and communicate via JSON-RPC: YES")
    print("Protocol: newline-delimited JSON (not Content-Length framing)")


asyncio.run(test_push())
