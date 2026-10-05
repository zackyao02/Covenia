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
  CustomerState,
  PriorityState,
  DemoServiceEventRequest,
  DemoServiceEventResponse,
} from "./api/contracts";
import { demoCases } from "./demoData";

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
  measurement_status: "NOT_MEASURED",
  input_tokens: null,
  output_tokens: null,
  inference_latency_ms: null,
  rule_substitution_count: null,
};

const evaluationMetrics: RuntimeMetrics = {
  measurement_status: "NOT_MEASURED",
  input_tokens: null,
  output_tokens: null,
  inference_latency_ms: null,
  rule_substitution_count: null,
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
  response.extracted_journey.extracted_scope = {
    order_id: caseInput.order.order_id,
    fulfillment_item_id: caseInput.current_issue.fulfillment_item_id,
    sku_id: caseInput.current_issue.sku_id,
    issue_type: caseInput.current_issue.issue_type,
  };
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
  const isHumanReviewChallenge = input.challenge_mode === true && (
    firstEvidence?.declared_view_type === "ISSUE_DETAIL" || (caseInput.current_issue.issue_type === "ADVERSE_REACTION" && !firstEvidence)
  );

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
        consumer_intent: "核实精华瓶口破损，并弄清已经发过照片后还缺什么",
        experience_expression: "消费者被要求整单重传，想知道只需补哪张图片",
        service_cause: "现有图片没有覆盖精华瓶口破损处",
        latent_need: "只补充当前精华瓶口所需的证据",
        cooperation_willingness: "STABLE",
        action_impact: "可以请求当前范围缺失的精华瓶口照片",
        source_ids: [caseInput.conversation[0]?.message_id ?? "CHALLENGE_MESSAGE", caseInput.conversation[caseInput.conversation.length - 1]?.message_id ?? "CHALLENGE_MESSAGE", firstEvidence.evidence_id],
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

  if (isHumanReviewChallenge) {
    response.extracted_journey = {
      ...response.extracted_journey,
      case_id: input.case_id,
      promise_events: [],
      image_observations: firstEvidence ? [
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
      ] : [],
      journey_understanding: {
        consumer_intent: "反馈使用防晒乳后泛红、刺痛，要求无需先发面部照片即可由专人跟进",
        experience_expression: "消费者仍感不适，也不愿在聊天里上传面部照片",
        service_cause: "涉及使用不适，不能只凭当前材料自动推断原因",
        latent_need: "先由专人接手，说明后续安排，并尊重不上传面部照片的选择",
        cooperation_willingness: "STABLE",
        action_impact: "先转人工核实，不自动诊断，也不要求消费者重复描述",
        source_ids: [caseInput.conversation[0]?.message_id ?? "CHALLENGE_MESSAGE", caseInput.conversation[caseInput.conversation.length - 1]?.message_id ?? "CHALLENGE_MESSAGE", ...(firstEvidence ? [firstEvidence.evidence_id] : [])],
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
      experience_gap_diagnosis: {
        consumer_expression: "消费者反馈使用防晒乳后泛红、刺痛，要求无需上传面部照片即可由专人跟进。",
        traceable_service_facts: [{
          fact_type: "OTHER",
          statement: "当前记录是消费者的使用反馈，尚未由人工核实。",
          source_ids: [caseInput.conversation[0]?.message_id ?? "DEMO_AUG_MSG_003_1"],
        }],
        deterioration_cause: "涉及身体不适，自动判断可能造成误导。",
        latent_need: "无需先上传面部照片，也能获得谨慎回应和人工跟进。",
        responsibility_judgment: { consumer_input_complete: false, accountable_side: "UNKNOWN" },
        action_impacts: ["ROUTE_TO_HUMAN"],
        reply_strategy: "先回应消费者关切，记录反馈并转人工核实，不自动判断原因。",
      },
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
    reason: template.reason,
    rule_id: ruleId,
    rule_priority: priority,
    resolution_path: structuredClone(template.resolution_path),
    fact_trace: { ...base.fact_trace, suppressed_rule_ids: suppressed },
  } satisfies DecisionResult);

  const e1Matches = action === "ASK_EVIDENCE" && evidenceStatus === "VALID" && scopeMatch === true;
  const h1Matches = evidenceStatus === "NEED_HUMAN_REVIEW" || state.current_scope.issue_type === "ADVERSE_REACTION";
  if (h1Matches) {
    const result = apply(reviewDecision, "H1", 350, "HUMAN_REVIEW", e1Matches ? ["E1"] : []);
    if (state.current_scope.issue_type === "ADVERSE_REACTION") {
      result.reason = "涉及消费者使用不适，需人工核实相关信息；系统不自动判断原因。";
      result.resolution_path.evidence_basis = ["消费者反馈使用防晒乳后脸部泛红", "当前没有可支持自动判断的完整依据"];
      result.resolution_path.consumer_reply_draft = "已记录您使用后泛红、刺痛的反馈，不用先上传面部照片。我会交给专人核实；在核实前请先暂停使用，如不适明显或持续，请及时咨询医生。";
      result.resolution_path.task_prefill = {
        ...result.resolution_path.task_prefill,
        sku_id: state.current_scope.sku_id,
        affected_component: "UNKNOWN",
        summary: "人工核实消费者使用防晒乳后脸部泛红的反馈；不自动判断原因。",
      };
    }
    return result;
  }
  if (e1Matches) return apply(interveneDecision, "E1", 300, "INTERVENE");
  if (action === "ASK_EVIDENCE" && evidenceStatus === "MISMATCHED") return apply(allowDecision, "E2", 100, "ALLOW");
  return apply(allowDecision, "E0_NO_RULE_MATCHED", 0, "ALLOW");
}

export const mockApi = {
  async pushDemoServiceEvent(input: DemoServiceEventRequest): Promise<ApiResult<DemoServiceEventResponse>> {
    await wait();
    const state = states.get(input.case_id);
    if (!state) return fail("VALIDATION_ERROR", "请先打开当前会话。", "REQ_DEMO_SERVICE", false);
    const next = structuredClone(state);
    let summary: string;
    let nextUpdate: string;
    if (input.case_id === "DEMO_002" && input.event_type === "CURRENT_SCOPE_EVIDENCE_SUBMITTED" && !next.demo_service_event) {
      summary = "已收到当前商品的精华瓶口照片；赠品材料无需重传，品牌继续核验。";
      nextUpdate = "2026-05-07T12:00:00+08:00";
      next.evidence_status = "VALID";
      next.consumer_input_required = false;
      next.accountable_side = "BRAND";
      next.case_status = "READY_FOR_BRAND";
    } else if (input.case_id === "DEMO_003" && input.event_type === "SPECIALIST_ASSIGNED" && !next.demo_service_event) {
      summary = "售后专员已接手使用不适反馈，将在 12:00 前主动联系；当前无需上传面部照片。";
      nextUpdate = "2026-05-07T12:00:00+08:00";
      next.accountable_side = "BRAND";
      next.case_status = "IN_FULFILLMENT";
      next.demo_specialist = "售后专员";
      next.demo_specialist_status = "已接手";
    } else if (input.case_id === "DEMO_003" && input.event_type === "SPECIALIST_FOLLOWED_UP" && next.demo_service_event === "SPECIALIST_ASSIGNED") {
      summary = "售后专员已主动联系并记录反馈，后续仍由品牌跟进；不自动判断不适原因。";
      nextUpdate = "2026-05-07T14:00:00+08:00";
      next.case_status = "READY_FOR_BRAND";
      next.demo_specialist_status = "已反馈";
    } else {
      return fail("INVALID_EVENT_TRANSITION", "当前服务事件不能重复或跳步。", "REQ_DEMO_SERVICE", false);
    }
    next.demo_service_event = input.event_type;
    next.service_progress_receipt = {
      receipt_id: `DEMO_SERVICE_RECEIPT_${input.case_id}`,
      status: "ACTIVE",
      received_evidence: input.case_id === "DEMO_002" ? ["赠品面膜外盒照片", "复颜精华瓶口近照（模拟提交）"] : ["消费者的使用反馈"],
      brand_action: summary,
      latest_update_at: serviceClock,
      next_update_by: nextUpdate,
      consumer_action_required: false,
      recovery_if_missed: "如未按时更新，由品牌继续跟进并告知新的处理时间。",
    };
    next.audit_trail = [...next.audit_trail, { at: serviceClock, actor: "SIMULATOR", action: input.event_type, changed_fields: ["case_status", "accountable_side", "service_progress_receipt"], request_id: `REQ_DEMO_SERVICE_${Date.now()}` }];
    states.set(input.case_id, structuredClone(next));
    return ok({ accountability_state: next, event_summary: summary }, "REQ_DEMO_SERVICE");
  },
  async resetDemoSession(caseId: string): Promise<ApiResult<{ case_id: string; reset: true }>> {
    states.delete(caseId);
    decisions.delete(caseId);
    shipmentStages.delete(caseId);
    serviceClock = "2026-05-07T09:42:00+08:00";
    return ok({ case_id: caseId, reset: true }, "REQ_DEMO_RESET");
  },
  async getCustomerState(): Promise<ApiResult<CustomerState>> {
    return fail("MODEL_UNAVAILABLE", "当前运行模式未启用实时沟通判断，请连接服务后重试。", "REQ_CUSTOMER", false);
  },
  async refreshDemoCustomerState(): Promise<ApiResult<CustomerState>> {
    return fail("MODEL_UNAVAILABLE", "当前运行模式未启用实时沟通判断，请连接服务后重试。", "REQ_DEMO_CUSTOMER", false);
  },
  async getPriority(): Promise<ApiResult<PriorityState[]>> {
    const rows: PriorityState[] = [];
    for (const item of demoCases) {
      const state = states.get(item.id) ?? analysisFor({
        case_id: item.id,
        evaluation_time: item.input.evaluation_time,
        challenge_mode: item.id !== "DEMO_001",
        case_input: item.input,
      }).accountability_state;
      if (state.case_status === "RESOLVED") continue;
      const overdue = state.case_status === "AT_RISK" || state.active_commitments.some(
        (entry) => entry.status !== "COMPLETED" && Date.parse(entry.deadline) < Date.parse(serviceClock),
      );
      const review = state.evidence_status === "NEED_HUMAN_REVIEW" || state.current_scope.issue_type === "ADVERSE_REACTION";
      const score = overdue ? 120 : review ? 92 : state.evidence_status === "MISMATCHED" ? 40 : 64;
      rows.push({
        case_id: item.id, rank: 0, priority_score: score,
        band: score >= 120 ? "RED" : score >= 92 ? "ORANGE" : score >= 64 ? "YELLOW" : "NORMAL",
        queue_reasons: [overdue ? "承诺需要跟进" : review ? "待人工复核" : state.consumer_input_required ? "等待补充当前证据" : "品牌待处理"],
        next_best_action: review ? "人工复核" : state.consumer_input_required ? "补齐当前证据" : "跟进处理进度",
      });
    }
    rows.sort((a, b) => b.priority_score - a.priority_score);
    return ok(rows.map((row, i) => ({ ...row, rank: i + 1 })), "REQ_PRIORITY");
  },
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
    if (input.draft_reply !== undefined) {
      return fail("MODEL_UNAVAILABLE", "当前运行模式无法确认这条回复是否可发送，请连接服务后重试。", "REQ_EVALUATE", false);
    }
    if (mockMode === "state_conflict") {
      return fail("INVALID_EVENT_TRANSITION", "责任状态已变化，请刷新后重试。", "REQ_EVALUATE");
    }
    const state = states.get(input.case_id) ?? structuredClone(heroAnalysis.accountability_state);
    if (input.prepared_action.action_type === "CLOSE_CASE" && state.prohibited_actions.includes("CLOSE_BEFORE_RESOLUTION")) {
      return fail("P0_PROHIBITED_ACTION", "当前不能结案，已有未完成的服务责任。", "REQ_EVALUATE", false);
    }
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
    const nextCheckAt = input.human_edits.next_check_at ?? "2026-05-07T10:10:00+08:00";
    const latestRecordedAt = existingState?.service_progress_receipt?.latest_update_at ?? serviceClock;
    if (!Number.isFinite(Date.parse(nextCheckAt)) || Date.parse(nextCheckAt) <= Math.max(Date.parse(serviceClock), Date.parse(latestRecordedAt))) {
      return fail("VALIDATION_ERROR", "下次更新时间须晚于当前服务时间。", "REQ_APPROVE", false);
    }
    if ((!existingState?.open_obligation || existingState.open_obligation.milestone === "AWAITING_CARRIER_PICKUP") && Date.parse(serviceClock) < Date.parse(deadline) && Date.parse(nextCheckAt) >= Date.parse(deadline)) {
      return fail("VALIDATION_ERROR", "正常跟进时间必须早于原承诺截止；请改成截止前的时间。", "REQ_APPROVE", false);
    }
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
      response.accountability_state.open_obligation.executor = input.human_edits.executor ?? response.accountability_state.open_obligation.executor;
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
    if (input.human_edits.consumer_reply?.trim()) {
      response.approved_resolution.consumer_reply_draft = input.human_edits.consumer_reply.trim();
      if (response.accountability_state.service_progress_receipt) {
        response.accountability_state.service_progress_receipt.brand_action = input.human_edits.consumer_reply.trim();
      }
    }
    if (response.approved_resolution.compiled_service_responsibility) {
      response.approved_resolution.compiled_service_responsibility.next_check_at =
        input.human_edits.next_check_at ?? nextCheckAt;
      response.approved_resolution.compiled_service_responsibility.recovery_if_missed =
        input.human_edits.recovery_if_missed ?? response.approved_resolution.compiled_service_responsibility.recovery_if_missed;
    }
    if (existingState?.open_obligation) {
      if (existingState.open_obligation.status === "COMPLETED") return fail("INVALID_EVENT_TRANSITION", "履约已完成，不能重新激活换货责任。", "REQ_APPROVE", false);
      response.accountability_state = structuredClone(existingState);
      response.accountability_state.open_obligation!.next_check_at = nextCheckAt;
      if (response.accountability_state.service_progress_receipt) response.accountability_state.service_progress_receipt.next_update_by = nextCheckAt;
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
