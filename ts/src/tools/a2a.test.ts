/**
 * Tests for the A2A SDK 1.x MCP tool surface (Phase 5).
 *
 * Mocks ``globalThis.fetch`` so the suite is hermetic — no real
 * network calls. Verifies the wire-shape that sac SDK 1.x expects:
 *
 *   * URL: ``POST /v1/agents/<agent>``
 *   * Header: ``A2A-Version: 1.0``
 *   * SendMessage params: ``{message: {message_id, role: "ROLE_USER",
 *     parts: [{text}]}}``
 *   * GetTask / CancelTask params: ``{id: <task_id>}``
 *
 * Run with ``bun test ts/src/tools/a2a.test.ts``.
 */
import {
  describe,
  test,
  expect,
  beforeEach,
  afterEach,
} from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { handleA2aCall } from "./a2a";
import { handleA2aGetTask } from "./a2a_get_task";
import { handleA2aCancelTask } from "./a2a_cancel_task";
import { handleA2aSendStreaming } from "./a2a_streaming";

type FetchCall = { url: string; init?: RequestInit };

function installFetchStub(
  respond: (call: FetchCall) => Response | Promise<Response>,
) {
  const calls: FetchCall[] = [];
  const original = globalThis.fetch;
  (globalThis as any).fetch = async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    const url = typeof input === "string" ? input : (input as URL).toString();
    const call: FetchCall = { url, init };
    calls.push(call);
    return respond(call);
  };
  return {
    calls,
    restore: () => {
      (globalThis as any).fetch = original;
    },
  };
}

let tmpDir: string;
let tokenPath: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "a2a-test-"));
  tokenPath = join(tmpDir, ".a2a-token");
  writeFileSync(tokenPath, "test-bearer-xyz\n");
  process.env.SCITEX_OROCHI_A2A_TOKEN_PATH = tokenPath;
  process.env.SCITEX_OROCHI_A2A_BASE_URL = "https://a2a.test";
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  delete process.env.SCITEX_OROCHI_A2A_TOKEN_PATH;
  delete process.env.SCITEX_OROCHI_A2A_BASE_URL;
});

describe("handleA2aCall (SDK 1.x defaults)", () => {
  test("default method is SendMessage with proto snake_case + A2A-Version header", async () => {
    const stub = installFetchStub(
      () =>
        new Response(
          JSON.stringify({ jsonrpc: "2.0", id: "x", result: { ok: true } }),
          { status: 200 },
        ),
    );
    try {
      await handleA2aCall({ agent: "lead", text: "hi" });
      expect(stub.calls).toHaveLength(1);
      const call = stub.calls[0]!;
      expect(call.url).toBe("https://a2a.test/v1/agents/lead");
      const headers = call.init!.headers as Record<string, string>;
      expect(headers["Authorization"]).toBe("Bearer test-bearer-xyz");
      expect(headers["A2A-Version"]).toBe("1.0");
      const body = JSON.parse(call.init!.body as string);
      expect(body.method).toBe("SendMessage");
      expect(body.params.message.role).toBe("ROLE_USER");
      expect(body.params.message.parts[0].text).toBe("hi");
      expect(typeof body.params.message.message_id).toBe("string");
    } finally {
      stub.restore();
    }
  });

  test("explicit GetTask method maps task_id → params.id", async () => {
    const stub = installFetchStub(
      () =>
        new Response(JSON.stringify({ jsonrpc: "2.0", id: "x", result: {} }), {
          status: 200,
        }),
    );
    try {
      await handleA2aCall({
        agent: "lead",
        method: "GetTask",
        task_id: "task-42",
      });
      const body = JSON.parse(stub.calls[0]!.init!.body as string);
      expect(body.method).toBe("GetTask");
      expect(body.params).toEqual({ id: "task-42" });
    } finally {
      stub.restore();
    }
  });

  test("non-2xx surface as throw", async () => {
    const stub = installFetchStub(
      () => new Response("nope", { status: 503 }),
    );
    try {
      await expect(handleA2aCall({ agent: "lead", text: "x" })).rejects.toThrow(
        /A2A 503/,
      );
    } finally {
      stub.restore();
    }
  });
});

describe("handleA2aGetTask / handleA2aCancelTask", () => {
  test("GetTask sends method=GetTask + params.id", async () => {
    const stub = installFetchStub(
      () => new Response(JSON.stringify({ result: { task: {} } }), { status: 200 }),
    );
    try {
      await handleA2aGetTask({ agent: "lead", task_id: "abc" });
      const body = JSON.parse(stub.calls[0]!.init!.body as string);
      expect(body.method).toBe("GetTask");
      expect(body.params).toEqual({ id: "abc" });
      const headers = stub.calls[0]!.init!.headers as Record<string, string>;
      expect(headers["A2A-Version"]).toBe("1.0");
    } finally {
      stub.restore();
    }
  });

  test("CancelTask sends method=CancelTask + params.id", async () => {
    const stub = installFetchStub(
      () => new Response(JSON.stringify({ result: {} }), { status: 200 }),
    );
    try {
      await handleA2aCancelTask({ agent: "lead", task_id: "abc" });
      const body = JSON.parse(stub.calls[0]!.init!.body as string);
      expect(body.method).toBe("CancelTask");
      expect(body.params).toEqual({ id: "abc" });
    } finally {
      stub.restore();
    }
  });
});

describe("handleA2aSendStreaming", () => {
  test("collects SSE events into MCP tool result", async () => {
    const sse =
      "data: {\"event\":\"start\"}\n\n" +
      "data: {\"event\":\"progress\",\"pct\":50}\n\n" +
      "data: {\"event\":\"completed\",\"state\":\"COMPLETED\"}\n\n";
    const stub = installFetchStub(
      () =>
        new Response(sse, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
    );
    try {
      const out = await handleA2aSendStreaming({
        agent: "lead",
        text: "stream",
      });
      const body = JSON.parse(stub.calls[0]!.init!.body as string);
      expect(body.method).toBe("SendStreamingMessage");
      expect(body.params.message.role).toBe("ROLE_USER");
      const parsed = JSON.parse(out.content[0]!.text);
      expect(parsed.count).toBe(3);
      expect(parsed.events[2].event).toBe("completed");
    } finally {
      stub.restore();
    }
  });
});
