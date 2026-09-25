import test from "node:test";
import assert from "node:assert/strict";
import { CoveniaService, ServiceError } from "../server/service.js";

test("analyze builds Customer State with emotion, effort and explainable risk", () => {
  const service = new CoveniaService();
  const result = service.analyze({ case_id: "DEMO_001" });
  assert.equal(result.customer_state.evidence.status, "VALID");
  assert.equal(result.customer_state.emotion.trend, "ESCALATING");
  assert.equal(result.customer_state.effort.contact_count, 2);
  assert.ok(result.customer_state.risk.score >= 61);
  assert.ok(result.customer_state.risk.factors.some((factor) => factor.code === "REPEATED_EVIDENCE"));
  assert.ok(result.customer_state.emotion.events.every((event) => event.source_id && event.quote && event.inference.is_inference));
  assert.equal(result.customer_state.emotion.governance.included_in_risk_score, false);
  assert.equal(result.customer_state.emotion.governance.overrides_existing_rules, false);
  assert.equal(result.customer_state.risk.prediction, false);
  assert.ok(!result.customer_state.risk.factors.some((factor) => factor.code.includes("EMOTION")));
  assert.ok(result.consumer_story.do_not_ask_again.some((item) => item.code === "ASK_SAME_EVIDENCE"));
});

test("emotion inference changes do not change operational risk score", () => {
  const service = new CoveniaService();
  const baseline = service.analyze({ case_id: "DEMO_001" });
  const variant = service.getFixture("DEMO_001").case_input;
  variant.conversation.at(-1).text = "我现在真的气死了，请给我明确答复。";
  const result = service.analyze({ case_id: "DEMO_001", challenge_mode: true, case_input: variant });
  assert.equal(result.customer_state.emotion.current, "ANGRY");
  assert.equal(result.customer_state.risk.score, baseline.customer_state.risk.score);
  assert.equal(result.customer_state.risk.context_signals[0].used_for_score, false);
});

test("firewall blocks repeated evidence request from server-derived state", () => {
  const service = new CoveniaService();
  const fixture = service.getFixture("DEMO_001");
  const result = service.evaluate({ case_id: "DEMO_001", prepared_action: fixture.prepared_action });
  assert.equal(result.decision, "INTERVENE");
  assert.equal(result.rule_id, "P0_PROHIBITED_ACTION");
  assert.equal(result.rule_priority, 400);
});

test("scope mismatch allows only the missing evidence request", () => {
  const service = new CoveniaService();
  const fixture = service.getFixture("DEMO_002");
  const result = service.evaluate({ case_id: "DEMO_002", prepared_action: fixture.prepared_action });
  assert.equal(result.accountability_state.evidence_status, "MISMATCHED");
  assert.equal(result.rule_id, "E2");
  assert.equal(result.decision, "ALLOW");
});

test("uncertain evidence routes to human review", () => {
  const service = new CoveniaService();
  const fixture = service.getFixture("DEMO_003");
  const result = service.evaluate({ case_id: "DEMO_003", prepared_action: fixture.prepared_action });
  assert.equal(result.accountability_state.evidence_status, "NEED_HUMAN_REVIEW");
  assert.equal(result.rule_id, "H1");
  assert.equal(result.decision, "HUMAN_REVIEW");
});

test("approval requires an approver", () => {
  const service = new CoveniaService();
  assert.throws(() => service.approve({ case_id: "DEMO_001" }), (error) => error instanceof ServiceError && error.code === "VALIDATION_ERROR");
});

test("approval is idempotent and creates a tracked obligation", () => {
  const service = new CoveniaService();
  const body = { case_id: "DEMO_001", candidate_type: "CHECK_REPLACEMENT_FULFILLMENT", approver_id: "tester", idempotency_key: "approve-test-001", human_edits: { executor: "WAREHOUSE" } };
  const first = service.approve(body);
  const replay = service.approve(body);
  assert.deepEqual(replay, first);
  assert.equal(first.accountability_state.open_obligation.milestone, "AWAITING_CARRIER_PICKUP");
  assert.equal(first.accountability_state.audit_trail.length, 1);
});

test("shipment state machine rejects delivery before pickup and resolves after delivery", () => {
  const service = new CoveniaService();
  service.approve({ case_id: "DEMO_001", candidate_type: "CHECK_REPLACEMENT_FULFILLMENT", approver_id: "tester", idempotency_key: "approve-test-002", human_edits: { executor: "WAREHOUSE" } });
  assert.throws(() => service.shipment({ case_id: "DEMO_001", event_id: "e0", event_type: "SHIPMENT_DELIVERED", event_time: "2026-05-07T12:00:00+08:00", idempotency_key: "ship-test-000" }), (error) => error.code === "INVALID_EVENT_TRANSITION");
  const picked = service.shipment({ case_id: "DEMO_001", event_id: "e1", event_type: "SHIPMENT_PICKED_UP", event_time: "2026-05-07T12:00:00+08:00", idempotency_key: "ship-test-001" });
  assert.equal(picked.accountability_state.open_obligation.milestone, "IN_TRANSIT");
  const delivered = service.shipment({ case_id: "DEMO_001", event_id: "e2", event_type: "SHIPMENT_DELIVERED", event_time: "2026-05-08T12:00:00+08:00", idempotency_key: "ship-test-002" });
  assert.equal(delivered.customer_state.resolution.status, "RESOLVED");
  assert.equal(delivered.accountability_state.open_obligation.status, "COMPLETED");
  assert.equal(delivered.customer_state.risk.score, 0);
});

test("risk radar returns cases sorted by score", () => {
  const service = new CoveniaService();
  const cases = service.riskCases();
  assert.equal(cases.length, 3);
  assert.ok(cases.every((item, index) => index === 0 || cases[index - 1].risk.score >= item.risk.score));
});
