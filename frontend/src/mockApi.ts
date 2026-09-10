import analyzeExample from "./api/examples/01-analyze-case.json";
import evaluateExample from "./api/examples/02-evaluate-action.json";
import approveExample from "./api/examples/03-approve-resolution.json";
import shipmentExample from "./api/examples/04-shipment-event.json";
import type {
  AccountabilityState,
  CaseInput,
  AnalyzeCaseRequest,
  AnalyzeCaseResponse,
  ApiResult,
  ApproveResolutionRequest,
  ApproveResolutionResponse,
  DecisionResult,
  EvaluateActionRequest,
  EvaluateActionResponse,
  ExtractedJourney,
  ShipmentEventRequest,
  ShipmentEventResponse,
  ApiErrorCode,
  RuntimeMetrics,
} from "./api/contracts";

export type MockMode =
  | "normal"
  | "slow"
  | "cached"
  | "model_timeout"
  | "state_conflict";

let mockMode: MockMode = "normal";
let serviceClock = "2026-05-07T09:42:00+08:00";

export function configureMockMode(mode: MockMode) {
  mockMode = mode;
}

export function getMockMode() {
  return mockMode;
}

/** Test-only clock injection: the mock never derives service deadlines from the browser clock. */
export function configureMockClock(value = "2026-05-07T09:42:00+08:00") {
  serviceClock = value;
}

const wait = (ms = 420) =>
  new Promise((resolve) => setTimeout(resolve, mockMode === "slow" ? 1800 : ms));

function ok<T>(data: T, prefix: string): ApiResult<T> {
  return { data, error: null, request_id: `${prefix}_${Date.now()}` };
}

function fail<T>(
  code: ApiErrorCode,
  message: string,
  prefix: string,
  retryable = true,
): ApiResult<T> {
  return {
    data: null,
    error: { code, message, retryable },
    request_id: `${prefix}_${Date.now()}`,
  };
}

const heroAnalysis = analyzeExample.response.data as unknown as AnalyzeCaseResponse;
const interveneDecision = evaluateExample.response.data as unknown as DecisionResult;
const allowDecision = evaluateExample.decision_variants[0]
  .response_data as unknown as DecisionResult;
const reviewDecision = evaluateExample.decision_variants[1]
  .response_data as unknown as DecisionResult;
const approved = approveExample.response.data as unknown as ApproveResolutionResponse;
const shipmentNotPickedUp = shipmentExample.response
  .data as unknown as ShipmentEventResponse;
const shipmentPickedUp = shipmentExample.picked_up_variant
  .response_data as unknown as ShipmentEventResponse;
const sourceHeroInput = analyzeExample.case_input_fixture;
const states = new Map<string, AccountabilityState>();
const decisions = new Map<string, DecisionResult>();
const shipmentStages = new Map<string, "AWAITING_PICKUP" | "IN_TRANSIT" | "DELIVERED">();

const analysisMetrics: RuntimeMetrics = {
  input_tokens: 1184,
  output_tokens: 346,
  inference_latency_ms: 842,
  rule_substitution_count: 0,
};

const evaluationMetrics: RuntimeMetrics = {
  input_tokens: 238,
  output_tokens: 74,
  inference_latency_ms: 36,
  rule_substitution_count: 1,
};

export function resetMockState() {
  states.clear();
  decisions.clear();
  shipmentStages.clear();
  serviceClock = "2026-05-07T09:42:00+08:00";
  mockMode = "normal";
}

function analysisFor(input: AnalyzeCaseRequest): AnalyzeCaseResponse {
  const response = structuredClone(heroAnalysis);
  const caseInput = (input.case_input ?? sourceHeroInput) as CaseInput;
  response.extracted_journey.case_id = input.case_id;
  response.accountability_state.case_id = input.case_id;
  response.accountability_state.current_scope = {
    order_id: caseInput.order.order_id,
    fulfillment_item_id: caseInput.current_issue.fulfillment_item_id,
    sku_id: caseInput.current_issue.sku_id,
    issue_type: caseInput.current_issue.issue_type,
  };
  response.accountability_state.audit_trail = [{
    at: input.evaluation_time ?? caseInput.evaluation_time,
    actor: "SYSTEM",
    action: "ANALYZED",
    changed_fields: ["extracted_journey", "accountability_state"],
    request_id: `REQ_ANALYZE_${Date.now()}`,
  }];
  response.accountability_state.active_commitments = response.accountability_state.active_commitments.map(
    (commitment) => ({ ...commitment, status: "ACTIVE" }),
  );

  const firstEvidence = caseInput.evidence_images[0];
  const isGiftChallenge = input.challenge_mode === true && firstEvidence?.declared_view_type === "PACKAGE_CONTEXT";
  const isBlurredChallenge = input.challenge_mode === true && firstEvidence?.declared_view_type === "ISSUE_DETAIL";

  if (isGiftChallenge) {
    response.extracted_journey = {
      ...response.extracted_journey,
      case_id: input.case_id,
      promise_events: [],
      image_observations: [
        {
          evidence_id: firstEvidence.evidence_id,
          readability: "HIGH",
          product_identifiable: true,
          sku_match: "MISMATCH",
          product_role: "GIFT",
          issue_visible: true,
          affected_component: "OUTER_PACKAGE",
          view_type: "PACKAGE_CONTEXT",
          coverage: ["PRODUCT_IDENTITY", "PACKAGE_CONTEXT"],
          integrity_concern: false,
          hygiene_risk_signal: "LOW",
          confidence: 0.96,
        },
      ],
      journey_understanding: {
        consumer_intent: "说明赠品与正装是两个不同问题",
        experience_expression: "消费者主动指出证据范围发生变化",
        service_cause: "现有图片只覆盖赠品面膜外盒",
        latent_need: "只补充当前粉底液泵头所需的证据",
        cooperation_willingness: "STABLE",
        action_impact: "可以请求当前范围缺失的泵头近照",
        source_ids: [caseInput.conversation[0]?.message_id ?? "CHALLENGE_MESSAGE", firstEvidence.evidence_id],
      },
    } satisfies ExtractedJourney;
    response.accountability_state = {
      ...response.accountability_state,
      evidence_status: "MISMATCHED",
      consumer_input_required: true,
      accountable_side: "CONSUMER",
      case_status: "WAITING_FOR_CONSUMER",
      active_commitments: [],
      prohibited_actions: [],
      open_obligation: null,
      service_progress_receipt: null,
      experience_risk: "LOW",
    };
  }

  if (isBlurredChallenge) {
    response.extracted_journey = {
      ...response.extracted_journey,
      case_id: input.case_id,
      promise_events: [],
      image_observations: [
        {
          evidence_id: firstEvidence.evidence_id,
          readability: "LOW",
          product_identifiable: false,
          sku_match: "UNKNOWN",
          product_role: "UNKNOWN",
          issue_visible: false,
          affected_component: "UNKNOWN",
          view_type: "ISSUE_DETAIL",
          coverage: [],
          integrity_concern: false,
          hygiene_risk_signal: "UNKNOWN",
          confidence: 0.41,
        },
      ],
      journey_understanding: {
        consumer_intent: "说明粉底液泵头无法使用",
        experience_expression: "消费者已提交图片但图片未对焦",
        service_cause: "当前图片不足以支持自动判断",
        latent_need: "明确告诉消费者是否真的需要补充材料",
        cooperation_willingness: "STABLE",
        action_impact: "应先由人工复核，避免无依据地重复索证",
        source_ids: [caseInput.conversation[0]?.message_id ?? "CHALLENGE_MESSAGE", firstEvidence.evidence_id],
      },
    } satisfies ExtractedJourney;
    response.accountability_state = {
      ...response.accountability_state,
      evidence_status: "NEED_HUMAN_REVIEW",
      consumer_input_required: false,
      accountable_side: "UNKNOWN",
      case_status: "ACTION_REVIEW",
      active_commitments: [],
      prohibited_actions: [],
      open_obligation: null,
      service_progress_receipt: null,
      experience_risk: "MEDIUM",
    };
  }

  response.model_metadata = response.extracted_journey.model_metadata;
  response.runtime_metrics = structuredClone(analysisMetrics);
  states.set(input.case_id, structuredClone(response.accountability_state));
  shipmentStages.set(input.case_id, "AWAITING_PICKUP");
  return response;
}

function decisionFor(state: AccountabilityState, input: EvaluateActionRequest): DecisionResult {
  const isChallenge = input.challenge_mode === true;
  const challengedImage = isChallenge
    ? input.challenge_overrides?.image_observation_overrides?.[0]
    : undefined;
  const challengedScope = isChallenge ? input.challenge_overrides?.requested_scope : undefined;
  const evidenceStatus = challengedImage?.readability === "LOW" || challengedImage?.readability === "UNKNOWN"
    ? "NEED_HUMAN_REVIEW"
    : challengedScope && challengedScope.sku_id !== state.current_scope.sku_id
      ? "MISMATCHED"
      : state.evidence_status;
  const requestedScope = challengedScope ?? input.prepared_action.requested_scope;
  const scopeMatch = requestedScope
    ? requestedScope.order_id === state.current_scope.order_id
      && requestedScope.fulfillment_item_id === state.current_scope.fulfillment_item_id
      && requestedScope.sku_id === state.current_scope.sku_id
      && requestedScope.issue_type === state.current_scope.issue_type
    : null;
  const action = input.prepared_action.action_type;
  const base = structuredClone(interveneDecision);
  base.accountability_state = structuredClone(state);
  base.case_id = state.case_id;
  base.challenge_mode = isChallenge;
  base.fact_trace = {
    evidence_status: evidenceStatus,
    prepared_action: action,
    scope_match: scopeMatch,
    active_promise_count: state.active_commitments.length,
  };
  base.runtime_metrics = structuredClone(evaluationMetrics);

  const apply = (template: DecisionResult, ruleId: DecisionResult["rule_id"], priority: DecisionResult["rule_priority"], decision: DecisionResult["decision"], suppressed: DecisionResult["fact_trace"]["suppressed_rule_ids"] = []) => ({
    ...structuredClone(template),
    ...base,
    decision,
    rule_id: ruleId,
    rule_priority: priority,
    fact_trace: { ...base.fact_trace, suppressed_rule_ids: suppressed },
  } satisfies DecisionResult);

  const e1Matches = action === "ASK_EVIDENCE" && evidenceStatus === "VALID" && scopeMatch === true;
  const h1Matches = evidenceStatus === "NEED_HUMAN_REVIEW" || state.current_scope.issue_type === "ADVERSE_REACTION";
  const p0Matches = action === "CLOSE_CASE" && state.prohibited_actions.includes("CLOSE_BEFORE_RESOLUTION");

  if (p0Matches) return apply(interveneDecision, "P0_PROHIBITED_ACTION", 400, "INTERVENE", h1Matches ? ["H1"] : []);
  if (h1Matches) return apply(reviewDecision, "H1", 350, "HUMAN_REVIEW", e1Matches ? ["E1"] : []);
  if (e1Matches) return apply(interveneDecision, "E1", 300, "INTERVENE");
  if (action === "ASK_EVIDENCE" && evidenceStatus === "MISMATCHED") return apply(allowDecision, "E2", 100, "ALLOW");
  return apply(allowDecision, "E0_NO_RULE_MATCHED", 0, "ALLOW");
}

export const mockApi = {
  async analyzeCase(
    input: AnalyzeCaseRequest,
  ): Promise<ApiResult<AnalyzeCaseResponse>> {
    await wait(520);
    if (mockMode === "model_timeout") {
      return fail(
        "MODEL_UNAVAILABLE",
        "模型分析超时，当前没有可用结果。案例内容和客服草稿均已保留。",
        "REQ_ANALYZE",
      );
    }
    const response = analysisFor(input);
    const cached = mockMode === "cached";
    response.extracted_journey.model_metadata.cached_result = cached;
    return ok(response, "REQ_ANALYZE");
  },

  async evaluateAction(
    input: EvaluateActionRequest,
  ): Promise<ApiResult<EvaluateActionResponse>> {
    await wait();
    if (mockMode === "state_conflict") {
      return fail("INVALID_EVENT_TRANSITION", "责任状态已变化，请刷新后重试。", "REQ_EVALUATE");
    }
    const state = states.get(input.case_id) ?? structuredClone(heroAnalysis.accountability_state);
    const decision = decisionFor(state, input);
    decision.case_id = input.case_id;
    decision.accountability_state = structuredClone(state);
    decisions.set(input.case_id, structuredClone(decision));
    return ok(decision, "REQ_EVALUATE");
  },

  async approveResolution(
    input: ApproveResolutionRequest,
  ): Promise<ApiResult<ApproveResolutionResponse>> {
    await wait(560);
    if (mockMode === "state_conflict") {
      return fail("INVALID_EVENT_TRANSITION", "当前解决路径基于旧状态，请刷新后重试。", "REQ_APPROVE");
    }
    if (!input.approver_id?.trim()) {
      return fail("VALIDATION_ERROR", "请填写审批人，才可以激活服务责任。", "REQ_APPROVE", false);
    }
    const response = structuredClone(approved);
    const existingState = states.get(input.case_id);
    const deadline = existingState?.active_commitments[0]?.deadline
      ?? response.accountability_state.active_commitments[0]?.deadline
      ?? "2026-05-07T10:27:37+08:00";
    const nextCheckAt = "2026-05-07T10:30:00+08:00";
    response.accountability_state.case_id = input.case_id;
    response.accountability_state.case_status = "IN_FULFILLMENT";
    response.accountability_state.experience_risk = "MEDIUM";
    response.accountability_state.active_commitments = response.accountability_state.active_commitments.map(
      (commitment) => ({ ...commitment, status: "ACTIVE", deadline }),
    );
    if (response.accountability_state.open_obligation) {
      response.accountability_state.open_obligation.status = "ON_TRACK";
      response.accountability_state.open_obligation.deadline = deadline;
      response.accountability_state.open_obligation.next_check_at = nextCheckAt;
    }
    if (response.accountability_state.service_progress_receipt) {
      response.accountability_state.service_progress_receipt.status = "ACTIVE";
      response.accountability_state.service_progress_receipt.latest_update_at = serviceClock;
      response.accountability_state.service_progress_receipt.next_update_by = nextCheckAt;
      response.accountability_state.service_progress_receipt.brand_action =
        "正在核实换货件是否已由物流揽收。";
      response.accountability_state.service_progress_receipt.recovery_if_missed =
        "若承诺时间前仍未确认揽收，品牌将主动催办并通知新的处理时间。";
    }
    const priorDecision = decisions.get(input.case_id);
    if (priorDecision) response.approved_resolution = structuredClone(priorDecision.resolution_path);
    response.approved_resolution.executor = input.human_edits.executor ?? response.approved_resolution.executor;
    if (response.approved_resolution.compiled_service_responsibility) {
      response.approved_resolution.compiled_service_responsibility.next_check_at =
        input.human_edits.next_check_at ?? nextCheckAt;
      response.approved_resolution.compiled_service_responsibility.recovery_if_missed =
        input.human_edits.recovery_if_missed ?? response.approved_resolution.compiled_service_responsibility.recovery_if_missed;
    }
    const auditEntry = {
      at: serviceClock,
      actor: input.approver_id,
      action: "RESOLUTION_APPROVED" as const,
      changed_fields: Object.keys(input.human_edits),
      request_id: `REQ_APPROVE_${serviceClock}`,
    };
    response.accountability_state.audit_trail = [
      ...(states.get(input.case_id)?.audit_trail ?? []),
      auditEntry,
    ];
    response.audit_trail = response.accountability_state.audit_trail;
    states.set(input.case_id, structuredClone(response.accountability_state));
    return ok(response, "REQ_APPROVE");
  },

  async pushShipmentEvent(
    input: ShipmentEventRequest,
  ): Promise<ApiResult<ShipmentEventResponse>> {
    await wait(560);
    if (mockMode === "state_conflict") {
      return fail("INVALID_EVENT_TRANSITION", "物流状态已经变化，请刷新后重新选择事件。", "REQ_SHIPMENT");
    }
    const stage = shipmentStages.get(input.case_id) ?? "AWAITING_PICKUP";
    if (input.event_type === "SHIPMENT_DELIVERED" && stage !== "IN_TRANSIT") {
      return fail("INVALID_EVENT_TRANSITION", "未揽收的换货件不能直接标记为已送达。", "REQ_SHIPMENT");
    }
    const source =
      input.event_type === "SHIPMENT_PICKED_UP" || input.event_type === "SHIPMENT_DELIVERED"
        ? shipmentPickedUp
        : shipmentNotPickedUp;
    const response = structuredClone(source);
    const eventAt = input.event_time;
    response.accountability_state.case_id = input.case_id;
    if (input.event_type === "SHIPMENT_DELIVERED") {
      response.accountability_state.case_status = "RESOLVED";
      response.accountability_state.experience_risk = "LOW";
      response.accountability_state.active_commitments = [];
      if (response.accountability_state.open_obligation) {
        response.accountability_state.open_obligation.status = "COMPLETED";
        response.accountability_state.open_obligation.milestone = "DELIVERED";
      }
      if (response.accountability_state.service_progress_receipt) {
        response.accountability_state.service_progress_receipt.status = "COMPLETED";
        response.accountability_state.service_progress_receipt.brand_action = "换货件已送达，本次服务责任已完成。";
      }
      response.follow_up_candidate = null;
      response.supervisor_escalation_candidate = null;
      shipmentStages.set(input.case_id, "DELIVERED");
    } else if (input.event_type === "SHIPMENT_PICKED_UP") {
      const nextUpdate = "2026-05-08T10:10:00+08:00";
      if (response.accountability_state.open_obligation) {
        response.accountability_state.open_obligation.next_check_at = nextUpdate;
        response.accountability_state.open_obligation.status = "ON_TRACK";
        response.accountability_state.open_obligation.milestone = "IN_TRANSIT";
      }
      response.accountability_state.active_commitments = response.accountability_state.active_commitments.map(
        (commitment) => ({ ...commitment, status: "COMPLETED" }),
      );
      shipmentStages.set(input.case_id, "IN_TRANSIT");
      if (response.accountability_state.service_progress_receipt) {
        response.accountability_state.service_progress_receipt.latest_update_at = eventAt;
        response.accountability_state.service_progress_receipt.next_update_by = nextUpdate;
      }
    } else {
      const overdueDeadline = states.get(input.case_id)?.active_commitments[0]?.deadline
        ?? "2026-05-07T10:27:37+08:00";
      const nextUpdate = "2026-05-07T12:00:00+08:00";
      response.accountability_state.active_commitments = response.accountability_state.active_commitments.map(
        (commitment) => ({ ...commitment, status: "AT_RISK", deadline: overdueDeadline }),
      );
      if (response.accountability_state.open_obligation) {
        response.accountability_state.open_obligation.deadline = overdueDeadline;
        response.accountability_state.open_obligation.next_check_at = nextUpdate;
      }
      if (response.accountability_state.service_progress_receipt) {
        response.accountability_state.service_progress_receipt.latest_update_at = eventAt;
        response.accountability_state.service_progress_receipt.next_update_by = nextUpdate;
      }
    }
    const nextUpdateAt = response.accountability_state.service_progress_receipt?.next_update_by ?? eventAt;
    const notificationText = typeof response.proactive_notification_draft === "string"
      ? response.proactive_notification_draft
      : response.proactive_notification_draft?.text ?? response.accountability_state.service_progress_receipt?.brand_action ?? "服务状态已更新。";
    response.proactive_notification_draft = {
      text: notificationText,
      commits_next_update_at: nextUpdateAt,
      requires_human_approval: true,
      channel: "ORIGINAL_CHAT",
    };
    response.accountability_state.audit_trail = [
      ...(states.get(input.case_id)?.audit_trail ?? []),
      {
        at: input.event_time,
        actor: "SIMULATOR",
        action: input.event_type,
        changed_fields: ["case_status", "open_obligation", "service_progress_receipt"],
        request_id: `REQ_SHIPMENT_${input.event_id}`,
      },
    ];
    states.set(input.case_id, structuredClone(response.accountability_state));
    return ok(response, "REQ_SHIPMENT");
  },
};
