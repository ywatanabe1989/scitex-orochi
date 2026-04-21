/**
 * Tests for the ``cron_status`` MCP tool (lead msg#16684 follow-up to
 * PR #346). The tool is a thin pass-through to the hub's
 * ``GET /api/cron/`` endpoint; what matters here is the URL/query
 * shape and error-envelope handling — the hub behaviour itself is
 * covered by ``hub/tests/views/api/test_cron.py``.
 *
 * Run with ``bun test ts/src/tools/cron_status.test.ts``.
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";

import { handleCronStatus } from "./sidecar";

type FetchCall = { url: string; init?: RequestInit };

function installFetchStub(
  respond: (call: FetchCall) => {
    status?: number;
    body?: unknown;
    bodyText?: string;
  },
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
    const r = respond(call);
    const status = r.status ?? 200;
    const text =
      r.bodyText !== undefined
        ? r.bodyText
        : JSON.stringify(r.body ?? { hosts: {} });
    return new Response(text, {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return {
    calls,
    restore() {
      globalThis.fetch = original;
    },
  };
}

describe("handleCronStatus", () => {
  let savedToken: string | undefined;
  let savedAgent: string | undefined;
  let savedUrl: string | undefined;

  beforeEach(() => {
    savedToken = process.env.SCITEX_OROCHI_TOKEN;
    savedAgent = process.env.SCITEX_OROCHI_AGENT;
    savedUrl = process.env.SCITEX_OROCHI_URL;
  });

  afterEach(() => {
    if (savedToken === undefined) delete process.env.SCITEX_OROCHI_TOKEN;
    else process.env.SCITEX_OROCHI_TOKEN = savedToken;
    if (savedAgent === undefined) delete process.env.SCITEX_OROCHI_AGENT;
    else process.env.SCITEX_OROCHI_AGENT = savedAgent;
    if (savedUrl === undefined) delete process.env.SCITEX_OROCHI_URL;
    else process.env.SCITEX_OROCHI_URL = savedUrl;
  });

  test("hits /api/cron/ with token + agent query params and parses response", async () => {
    const stub = installFetchStub(() => ({
      body: { hosts: { mba: { agent: "head-mba", jobs: [] } } },
    }));
    try {
      const result = await handleCronStatus({});
      expect(stub.calls.length).toBe(1);
      const url = new URL(stub.calls[0].url);
      expect(url.pathname).toBe("/api/cron/");
      // Token + agent always appended when the env provides them.
      // (Captured at module load — values seeded by config.ts.)
      expect(url.searchParams.has("token")).toBe(true);
      expect(url.searchParams.has("agent")).toBe(true);
      // No host filter when the arg is omitted.
      expect(url.searchParams.has("host")).toBe(false);
      const payload = JSON.parse(result.content[0].text);
      expect(payload.hosts.mba.agent).toBe("head-mba");
    } finally {
      stub.restore();
    }
  });

  test("propagates host arg as ?host= query param", async () => {
    const stub = installFetchStub(() => ({
      body: { hosts: { nas: { agent: "head-nas", jobs: [] } } },
    }));
    try {
      await handleCronStatus({ host: "nas" });
      const url = new URL(stub.calls[0].url);
      expect(url.searchParams.get("host")).toBe("nas");
    } finally {
      stub.restore();
    }
  });

  test("trims whitespace from host arg and drops empty host", async () => {
    const stub = installFetchStub(() => ({ body: { hosts: {} } }));
    try {
      await handleCronStatus({ host: "   " });
      const url = new URL(stub.calls[0].url);
      expect(url.searchParams.has("host")).toBe(false);
    } finally {
      stub.restore();
    }
  });

  test("HTTP 401 maps to permission_denied error envelope", async () => {
    const stub = installFetchStub(() => ({
      status: 401,
      bodyText: "invalid token",
    }));
    try {
      const result = await handleCronStatus({});
      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.error.code).toBe("permission_denied");
      expect(parsed.error.reason).toContain("HTTP 401");
    } finally {
      stub.restore();
    }
  });

  test("HTTP 500 maps to internal_error envelope", async () => {
    const stub = installFetchStub(() => ({
      status: 500,
      bodyText: "boom",
    }));
    try {
      const result = await handleCronStatus({});
      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.error.code).toBe("internal_error");
    } finally {
      stub.restore();
    }
  });

  test("network failure surfaces internal_error with hint", async () => {
    const original = globalThis.fetch;
    (globalThis as any).fetch = async () => {
      throw new Error("ECONNREFUSED");
    };
    try {
      const result = await handleCronStatus({});
      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.error.code).toBe("internal_error");
      expect(parsed.error.reason).toContain("ECONNREFUSED");
      expect(parsed.error.hint).toMatch(/reachability|OROCHI_URL/);
    } finally {
      globalThis.fetch = original;
    }
  });
});
