import { describe, expect, it, vi } from "vitest";
import { RetryIdentityStore } from "./retryIdentity";

describe("RetryIdentityStore", () => {
  it("reuses the same key and event id for an identical retry", () => {
    vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValueOnce("key-1").mockReturnValueOnce("event-1") });
    const store = new RetryIdentityStore();
    const first = store.get("shipment-DEMO_001", { event_type: "SHIPMENT_PICKED_UP" }, true);
    const retry = store.get("shipment-DEMO_001", { event_type: "SHIPMENT_PICKED_UP" }, true);
    expect(retry).toEqual(first);
    expect(first.idempotencyKey).toBe("shipment-DEMO_001-key-1");
    expect(first.eventId).toBe("EVT_event-1");
    vi.unstubAllGlobals();
  });

  it("uses a fresh identity when payload changes or a prior request succeeds", () => {
    vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValueOnce("one").mockReturnValueOnce("two").mockReturnValueOnce("three") });
    const store = new RetryIdentityStore();
    const first = store.get("approve-DEMO_001", { reply: "A" });
    expect(store.get("approve-DEMO_001", { reply: "B" }).idempotencyKey).not.toBe(first.idempotencyKey);
    store.clear("approve-DEMO_001");
    expect(store.get("approve-DEMO_001", { reply: "B" }).idempotencyKey).toBe("approve-DEMO_001-three");
    vi.unstubAllGlobals();
  });
});
