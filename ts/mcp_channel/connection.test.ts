/**
 * FR-K (lead msg#22969): MCP sidecar should auto-reconnect on hub
 * recovery with exponential backoff, capped at 5min, retried indefinitely.
 *
 * Background: 2026-04-29 mba disk-full incident took the hub down ~21h.
 * The pre-FR-K reconnect was a flat 3s setTimeout — fine for short
 * blips, but during a 21h outage it would re-attempt ~25k times and
 * gave operators no clear "we are back" signal in the agent's pane.
 *
 * These tests cover the pure backoff-scheduling helper. The full
 * reconnect loop integration is exercised by the manual acceptance
 * test (kill hub, restart, verify MCP tools recover without manual
 * /mcp reconnect) — too WS-stateful to mock cleanly.
 */

import { describe, expect, test } from "bun:test";
import { RECONNECT_BACKOFF_MS, reconnectBackoffMs } from "./connection.js";

describe("reconnectBackoffMs", () => {
  test("first attempt waits 5s", () => {
    expect(reconnectBackoffMs(1)).toBe(5_000);
  });

  test("schedule progresses 5s -> 10s -> 30s -> 60s -> 120s -> 300s", () => {
    expect(reconnectBackoffMs(1)).toBe(5_000);
    expect(reconnectBackoffMs(2)).toBe(10_000);
    expect(reconnectBackoffMs(3)).toBe(30_000);
    expect(reconnectBackoffMs(4)).toBe(60_000);
    expect(reconnectBackoffMs(5)).toBe(120_000);
    expect(reconnectBackoffMs(6)).toBe(300_000);
  });

  test("clamps at 5min for any attempt past the schedule", () => {
    expect(reconnectBackoffMs(7)).toBe(300_000);
    expect(reconnectBackoffMs(100)).toBe(300_000);
    // 21h outage at 5min cadence is the worst case after the schedule
    // is exhausted — this is the upper bound we care about.
    expect(reconnectBackoffMs(10_000)).toBe(300_000);
  });

  test("treats attempt=0 the same as attempt=1 (defensive)", () => {
    // Production code increments reconnectAttempts before calling, so 0
    // shouldn't occur, but the helper must not throw if it does.
    expect(reconnectBackoffMs(0)).toBe(5_000);
    expect(reconnectBackoffMs(-1)).toBe(5_000);
  });

  test("schedule shape is monotonic and capped at 300s", () => {
    for (let i = 1; i < RECONNECT_BACKOFF_MS.length; i++) {
      expect(RECONNECT_BACKOFF_MS[i]).toBeGreaterThanOrEqual(
        RECONNECT_BACKOFF_MS[i - 1],
      );
    }
    expect(Math.max(...RECONNECT_BACKOFF_MS)).toBe(300_000);
  });
});
