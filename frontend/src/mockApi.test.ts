import { beforeEach, describe, expect, it } from "vitest";
import { demoCases } from "./demoData";
import type { EvaluateActionRequest } from "./api/contracts";
import { configureMockMode, mockApi } from "./mockApi";

function evaluateRequest(caseId: string): EvaluateActionRequest {
  const demoCase = demoCases.find((item) => item.id === caseId)!;
  const base: EvaluateActionRequest = {
    case_id: caseId,
    prepared_action: demoCase.preparedAction,
  };
  if (caseId === "DEMO_002") {
    return {
      ...base,
      challenge_mode: true,
      challenge_overrides: {
        requested_scope: {
          ...demoCase.preparedAction.requested_scope!,
          fulfillment_item_id: "6920185815517983396-GIFT-B5-MASK-2",
          sku_id: "GIFT-B5-MASK-2",
        },
      },
    };
  }
  if (caseId === "DEMO_003") {
    return {
      ...base,
      challenge_mode: true,
      challenge_overrides: {
        image_observation_overrides: [{
          evidence_id: "S00001_BLURRED_IMG",
          readability: "LOW",
          sku_match: "UNKNOWN",
          issue_visible: false,
        }],
      },
    };
  }
  return base;
}

async function analyze(caseId: string) {
  const demoCase = demoCases.find((item) => item.id === caseId)!;
  return mockApi.analyzeCase({
    case_id: caseId,
    evaluation_time: demoCase.input.evaluation_time,
    ...(caseId === "DEMO_001" ? {} : { challenge_mode: true, case_input: demoCase.input }),
  });
}

describe("Covenia v0.8 frontend API contract", () => {
  beforeEach(() => configureMockMode("normal"));

  it.each([
    ["DEMO_001", "INTERVENE", "E1", false],
    ["DEMO_002", "ALLOW", "E2", true],
    ["DEMO_003", "HUMAN_REVIEW", "H1", true],
  ] as const)("returns the expected decision for %s", async (caseId, decision, ruleId, challengeMode) => {
    const analyzed = await analyze(caseId);
    expect(analyzed.error).toBeNull();
    const evaluated = await mockApi.evaluateAction(evaluateRequest(caseId));
    expect(evaluated.error).toBeNull();
    if (evaluated.error) return;
    expect(evaluated.data.decision).toBe(decision);
    expect(evaluated.data.rule_id).toBe(ruleId);
    expect(evaluated.data.challenge_mode).toBe(challengeMode);
  });

  it("creates a running obligation only after human approval", async () => {
    await analyze("DEMO_001");
    const evaluated = await mockApi.evaluateAction(evaluateRequest("DEMO_001"));
    if (evaluated.error) throw new Error("evaluation failed");

    const approved = await mockApi.approveResolution({
      case_id: "DEMO_001",
      candidate_type: evaluated.data.resolution_path.candidate_type,
      approver_id: "AGENT_ZHOU",
      idempotency_key: "approve-demo-001",
      human_edits: { executor: "WAREHOUSE" },
    });
    expect(approved.error).toBeNull();
    if (approved.error) return;
    expect(approved.data.accountability_state.case_status).toBe("IN_FULFILLMENT");
    expect(approved.data.accountability_state.open_obligation?.status).toBe("ON_TRACK");
    expect(approved.data.audit_trail[approved.data.audit_trail.length - 1]?.actor).toBe("AGENT_ZHOU");
  });

  it("keeps pickup open, rejects direct delivery, then closes after delivery", async () => {
    await analyze("DEMO_001");
    const directDelivery = await mockApi.pushShipmentEvent({
      case_id: "DEMO_001",
      event_id: "EVT_DIRECT",
      event_type: "SHIPMENT_DELIVERED",
      event_time: "2026-05-08T15:20:00+08:00",
      idempotency_key: "shipment-direct-delivery",
    });
    expect(directDelivery.error?.code).toBe("INVALID_EVENT_TRANSITION");

    const pickedUp = await mockApi.pushShipmentEvent({
      case_id: "DEMO_001",
      event_id: "EVT_PICKUP",
      event_type: "SHIPMENT_PICKED_UP",
      event_time: "2026-05-07T10:10:00+08:00",
      idempotency_key: "shipment-picked-up",
    });
    expect(pickedUp.error).toBeNull();
    if (pickedUp.error) return;
    expect(pickedUp.data.accountability_state.case_status).toBe("IN_FULFILLMENT");

    const delivered = await mockApi.pushShipmentEvent({
      case_id: "DEMO_001",
      event_id: "EVT_DELIVERED",
      event_type: "SHIPMENT_DELIVERED",
      event_time: "2026-05-08T15:20:00+08:00",
      idempotency_key: "shipment-delivered",
    });
    expect(delivered.error).toBeNull();
    if (delivered.error) return;
    expect(delivered.data.accountability_state.case_status).toBe("RESOLVED");
    expect(delivered.data.accountability_state.active_commitments).toHaveLength(0);
  });

  it("marks cached analysis and exposes a retryable model error", async () => {
    configureMockMode("cached");
    const cached = await analyze("DEMO_001");
    expect(cached.error).toBeNull();
    if (!cached.error) expect(cached.data.model_metadata.cached_result).toBe(true);

    configureMockMode("model_timeout");
    const timedOut = await analyze("DEMO_001");
    expect(timedOut.data).toBeNull();
    expect(timedOut.error?.code).toBe("MODEL_UNAVAILABLE");
    expect(timedOut.error?.retryable).toBe(true);
  });
});
