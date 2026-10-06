import { afterEach, describe, expect, it, vi } from "vitest";
import { httpApi } from "./client";

describe("HTTP API failure handling", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("never exposes a failed HTTP response as successful data", async () => {
    vi.stubGlobal("window", { setTimeout: vi.fn(() => 1), clearTimeout: vi.fn() });
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "request-1") });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      data: { reset: true }, error: null, request_id: "server-request",
    }), { status: 503, headers: { "Content-Type": "application/json" } })));

    const result = await httpApi.resetDemoSession("DEMO_001");
    expect(result.data).toBeNull();
    expect(result.error?.retryable).toBe(true);
  });

  it("reports network rejection with null data and a retryable error", async () => {
    vi.stubGlobal("window", { setTimeout: vi.fn(() => 1), clearTimeout: vi.fn() });
    vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "request-2") });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    const result = await httpApi.resetDemoSession("DEMO_001");
    expect(result.data).toBeNull();
    expect(result.error?.retryable).toBe(true);
  });
});
