import test from "node:test";
import assert from "node:assert/strict";
import { JevClient, buildJevState } from "../server/jev.js";
import { CoveniaService } from "../server/service.js";

test("JEV state projection minimizes identifiers and preserves journey signals", () => {
  const service = new CoveniaService();
  const snapshot = service.buildSnapshot("DEMO_001");
  const projection = buildJevState(snapshot);
  const serialized = JSON.stringify(projection.state);
  assert.equal(projection.state.contact_history.length, snapshot.caseInput.conversation.length);
  assert.equal(projection.state.deterministic_signals.repeated_contact, snapshot.customerState.effort.repeated_contact);
  assert.ok(!serialized.includes(snapshot.caseInput.order.order_id));
  assert.ok(!serialized.includes(snapshot.caseInput.evidence_images[0].file_name));
});

test("JEV contract mock returns typed advisory signals without changing operational risk", async () => {
  const client = new JevClient({ mode: "mock", model: "jev-latest" });
  const service = new CoveniaService(undefined, undefined, client);
  const before = service.analyze({ case_id: "DEMO_001" }).customer_state.risk;
  const result = await service.analyzeWithJev({ case_id: "DEMO_001" });
  assert.equal(result.jev.status, "READY");
  assert.equal(result.jev.signals.emotion_change.primitive, "choice");
  assert.equal(result.jev.signals.needs_human_review.primitive, "noul");
  assert.equal(result.jev.signals.service_urgency.primitive, "score");
  assert.equal(result.jev.governance.simulated_probabilities, true);
  assert.equal(result.jev.governance.changes_operational_risk_score, false);
  assert.deepEqual(result.operational_risk, before);
});

test("live JEV adapter sends official state, model and typed questions contract", async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url, options, body: JSON.parse(options.body) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        model: "jev-1.13.0",
        answers: {
          emotion_change: { type: "choice", choice: "worsening", confidence: 0.84, probabilities: { improving: 0.03, stable: 0.13, worsening: 0.84 } },
          needs_human_review: { type: "noul", noul: 0.76 },
          service_urgency: { type: "score", score: 2.1, confidence: 0.79, legend: { 0: "normal", 1: "today", 2: "priority", 3: "immediate" }, probabilities: { 0: 0.04, 1: 0.18, 2: 0.57, 3: 0.21 } },
        },
        usage: { input_tokens: 321, output_tokens: 12 }
      })
    };
  };
  const client = new JevClient({ mode: "live", apiKey: "test-secret", model: "jev-latest", fetchImpl });
  const service = new CoveniaService(undefined, undefined, client);
  const result = await service.analyzeWithJev({ case_id: "DEMO_001" });
  assert.equal(request.url, "https://api.typesafe.ai/v1/systemone");
  assert.equal(request.options.headers.authorization, "Bearer test-secret");
  assert.equal(request.body.model, "jev-latest");
  assert.deepEqual(Object.keys(request.body.questions), ["emotion_change", "needs_human_review", "service_urgency"]);
  assert.equal(result.jev.provider, "TYPESAFE_JEV");
  assert.equal(result.jev.signals.emotion_change.probabilities.worsening, 0.84);
  assert.equal(result.jev.decision_support.experimental_formula_preview.used_for_operational_risk, false);
});

test("JEV provider failure fails open to existing Covenia rules", async () => {
  const client = new JevClient({ mode: "live", apiKey: "test-secret", fetchImpl: async () => { throw new Error("network down"); } });
  const service = new CoveniaService(undefined, undefined, client);
  const result = await service.analyzeWithJev({ case_id: "DEMO_001" });
  assert.equal(result.jev.status, "ERROR");
  assert.equal(result.integration_policy, "FAIL_OPEN_TO_EXISTING_RULES");
  assert.ok(result.operational_risk.score > 0);
});
