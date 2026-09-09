/**
 * Covenia Competition MVP v0.8 — C 端接口契约
 *
 * 依据：docs/01-core-contracts.md、03-firewall-rules.md、
 * 04-responsibility-loop.md、05-api-and-ui.md 及仓库 JSON Schema。
 *
 * 约定：
 * 1. 后端仍只提供四个业务接口；服务进度回执是 AccountabilityState 的派生视图。
 * 2. CaseInput、ExtractedJourney、AccountabilityState、PreparedAction、
 *    DecisionResult 与仓库 Schema 对齐。
 * 3. 所有响应使用 {data, error, request_id}；approve 与 shipment
 *    在请求体携带幂等键，服务端是责任状态的唯一真相。
 * 4. 所有 ID 均按 string 传输，避免订单号、工单号和物流单号丢失精度。
 */

export type ISODateTime = string;

export type Speaker = "CONSUMER" | "AGENT" | "SYSTEM";
export type ConversationSourceKind =
  | "COMPETITION_MOCK"
  | "DEMO_AUGMENTATION";
export type EvidenceSourceKind =
  | "TEAM_SYNTHETIC_RECREATION"
  | "TEAM_SYNTHETIC_AUGMENTATION";
export type ViewType =
  | "PRODUCT_OVERVIEW"
  | "ISSUE_DETAIL"
  | "PACKAGE_CONTEXT"
  | "OTHER";
export type ItemRole = "PRIMARY" | "GIFT" | "BUNDLE_COMPONENT";
export type TicketType =
  | "REPLACEMENT"
  | "OFFLINE_PAYMENT"
  | "LOGISTICS"
  | "ADVERSE_REACTION"
  | "RETURN";
export type IssueType =
  | "PACKAGE_DAMAGE"
  | "LOGISTICS_STALLED"
  | "ADVERSE_REACTION";
export type AffectedComponent =
  | "BOTTLE"
  | "PUMP"
  | "CAP"
  | "SEAL"
  | "OUTER_PACKAGE"
  | "UNKNOWN";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN";

export interface DataProvenance {
  source_dataset: "TIANCHI_LOREAL_TRACK1_MOCK";
  source_session_id: string;
  augmentation_notes: string[];
}

export interface ConversationMessage {
  message_id: string;
  timestamp: ISODateTime;
  speaker: Speaker;
  text: string;
  source_kind: ConversationSourceKind;
}

export interface OrderItem {
  fulfillment_item_id: string;
  sku_id: string;
  product_name: string;
  batch_code?: string | null;
  item_role: ItemRole;
}

export interface CaseOrder {
  order_id: string;
  channel: "TIANCHI_MOCK_QIANNIU";
  items: OrderItem[];
  original_logistics_number: string;
}

export interface ServiceTicket {
  ticket_id: string;
  ticket_type: TicketType;
  status: string;
  assignee_id: string;
  executor_name?: string | null;
  replacement_logistics_number?: string | null;
  created_at: ISODateTime;
  completed_at?: ISODateTime | null;
  source_sheet: string;
}

export interface EvidenceImage {
  evidence_id: string;
  file_name: string;
  submitted_at: ISODateTime;
  declared_view_type: ViewType;
  source_kind: EvidenceSourceKind;
  source_message_id: string;
  competition_reference_path?: string | null;
}

export interface IssueScope {
  order_id: string;
  fulfillment_item_id: string;
  sku_id: string;
  issue_type: IssueType;
}

export interface CurrentIssue {
  fulfillment_item_id: string;
  sku_id: string;
  issue_type: IssueType;
  affected_component?: AffectedComponent;
  integrity_concern?: boolean;
  hygiene_risk?: RiskLevel;
}

export interface CaseInput {
  case_id: string;
  data_provenance: DataProvenance;
  evaluation_time: ISODateTime;
  conversation: ConversationMessage[];
  order: CaseOrder;
  service_tickets: ServiceTicket[];
  evidence_images: EvidenceImage[];
  current_issue: CurrentIssue;
  policy_requirement_id: "DEMO_POLICY_PACKAGE_DAMAGE_V1";
}

export type CommitmentClass =
  | "STANDARD_APPROVED"
  | "APPROVAL_REQUIRED"
  | "CONDITIONAL"
  | "ERRONEOUS_OR_UNAUTHORIZED"
  | "AMBIGUOUS";
export type ActivationStatus =
  | "ACTIVE"
  | "PENDING_APPROVAL"
  | "BLOCKED"
  | "IGNORED";

export interface PromiseEvent {
  raw_text: string;
  promise_type: string;
  commitment_class: CommitmentClass;
  activation_recommendation: ActivationStatus;
  conditions: string[];
  committed_at: ISODateTime;
  deadline: ISODateTime | null;
  confidence: number;
  source_ids: string[];
}

export type EvidenceCoverage =
  | "PRODUCT_IDENTITY"
  | "AFFECTED_COMPONENT"
  | "DAMAGE_DETAIL"
  | "PACKAGE_CONTEXT"
  | "BATCH_LABEL";

export interface ImageObservation {
  evidence_id: string;
  readability: "HIGH" | "LOW" | "UNKNOWN";
  product_identifiable: boolean;
  sku_match: "MATCH" | "MISMATCH" | "UNKNOWN";
  product_role: ItemRole | "UNKNOWN";
  issue_visible: boolean;
  affected_component: AffectedComponent;
  view_type: ViewType;
  coverage: EvidenceCoverage[];
  integrity_concern: boolean;
  hygiene_risk: RiskLevel;
  confidence: number;
}

export interface JourneyUnderstanding {
  consumer_intent: string;
  experience_expression: string;
  service_cause: string;
  latent_need: string;
  cooperation_willingness: "STABLE" | "DECLINING" | "LOW" | "UNKNOWN";
  action_impact: string;
  source_ids: string[];
}

export interface SourceTrace {
  field: string;
  source_type: "CHAT" | "IMAGE" | "ORDER" | "TICKET";
  source_id: string;
}

export interface ExtractedJourney {
  case_id: string;
  completed_actions: {
    issue_explained: boolean;
    order_verified: boolean;
    evidence_submitted: boolean;
  };
  promise_events: PromiseEvent[];
  image_observations: ImageObservation[];
  extracted_scope: IssueScope;
  journey_understanding: JourneyUnderstanding;
  source_trace: SourceTrace[];
  model_metadata: {
    model_id: "Qwen/Qwen2-VL-2B-Instruct";
    model_revision?: string;
    prompt_version: string;
    run_id: string;
    cached_result?: boolean;
  };
}

export type CaseStatus =
  | "WAITING_FOR_CONSUMER"
  | "READY_FOR_BRAND"
  | "ACTION_REVIEW"
  | "IN_FULFILLMENT"
  | "AT_RISK"
  | "RESOLVED";
export type AccountableSide = "CONSUMER" | "BRAND" | "UNKNOWN";
export type EvidenceStatus = "VALID" | "MISMATCHED" | "NEED_HUMAN_REVIEW";
export type ProhibitedAction =
  | "ASK_SAME_EVIDENCE"
  | "ASK_REPEAT_EXPLANATION"
  | "SHIFT_FOLLOW_UP_TO_CONSUMER"
  | "MAKE_UNTRACKABLE_PROMISE"
  | "CLOSE_BEFORE_RESOLUTION";

export interface ActiveCommitment {
  promise_type: string;
  raw_text: string;
  status: "ACTIVE" | "AT_RISK" | "COMPLETED";
  deadline: ISODateTime;
  source_ids: string[];
}

export type TraceableFactType =
  | "ISSUE_EXPLAINED"
  | "EVIDENCE_SUBMITTED"
  | "TICKET_CREATED"
  | "PROMISE_ACTIVE"
  | "PROMISE_OVERDUE"
  | "REPEAT_CONTACT"
  | "OTHER";

export interface ExperienceGapDiagnosis {
  consumer_expression: string;
  traceable_service_facts: Array<{
    fact_type: TraceableFactType;
    statement: string;
    source_ids: string[];
  }>;
  deterioration_cause: string;
  latent_need: string;
  responsibility_judgment: {
    consumer_input_complete: boolean;
    accountable_side: AccountableSide;
  };
  action_impacts: Array<
    | "BLOCK_REPEAT_EVIDENCE"
    | "RAISE_PRIORITY"
    | "ROUTE_TO_HUMAN"
    | "CHECK_EXISTING_FULFILLMENT"
    | "REQUEST_MISSING_INPUT"
    | "START_PROACTIVE_UPDATE"
  >;
  reply_strategy: string;
}

export type ObligationExecutor = "BRAND" | "WAREHOUSE" | "LOGISTICS_PROVIDER";
export type ObligationMilestone =
  | "AWAITING_CARRIER_PICKUP"
  | "IN_TRANSIT"
  | "DELIVERED";

export interface OpenObligation {
  obligation_type: "REPLACEMENT_FULFILLMENT";
  status: "ON_TRACK" | "AT_RISK" | "COMPLETED";
  accountable_side: "BRAND";
  executor: ObligationExecutor;
  deadline: ISODateTime;
  next_check_at: ISODateTime;
  milestone: ObligationMilestone;
  resolution_condition: "REPLACEMENT_DELIVERED";
}

export interface ServiceProgressReceipt {
  receipt_id: string;
  status: "ACTIVE" | "AT_RISK" | "COMPLETED";
  received_evidence: string[];
  brand_action: string;
  latest_update_at: ISODateTime;
  next_update_by: ISODateTime;
  consumer_action_required: boolean;
  recovery_if_missed: string;
}

export interface AccountabilityState {
  case_id: string;
  case_status: CaseStatus;
  consumer_input_required: boolean;
  accountable_side: AccountableSide;
  evidence_status: EvidenceStatus;
  current_scope: IssueScope;
  active_commitments: ActiveCommitment[];
  prohibited_actions: ProhibitedAction[];
  experience_gap_diagnosis: ExperienceGapDiagnosis;
  open_obligation: OpenObligation | null;
  service_progress_receipt: ServiceProgressReceipt | null;
  experience_risk: Exclude<RiskLevel, "UNKNOWN">;
  audit_trail: AuditTrailEntry[];
}

export interface AuditTrailEntry {
  at: ISODateTime;
  actor: string;
  action:
    | "ANALYZED"
    | "RESOLUTION_APPROVED"
    | "SHIPMENT_PICKED_UP"
    | "SHIPMENT_NOT_PICKED_UP"
    | "SHIPMENT_DELIVERED";
  changed_fields: string[];
  request_id: string;
}

export type PreparedActionType =
  | "ASK_EVIDENCE"
  | "CHECK_REPLACEMENT_PROGRESS"
  | "CREATE_FOLLOW_UP_TASK"
  | "CLOSE_CASE";

export interface PreparedAction {
  action_id: string;
  action_type: PreparedActionType;
  requested_scope?: IssueScope | null;
  requires_human_approval: boolean;
}

export type Decision = "INTERVENE" | "ALLOW" | "HUMAN_REVIEW";
export type RuleId = "P0_PROHIBITED_ACTION" | "E1" | "E2" | "H1" | "E0_NO_RULE_MATCHED";
export type RulePriority = 400 | 300 | 200 | 100 | 0;
export type ResolutionCandidateType =
  | "CHECK_REPLACEMENT_FULFILLMENT"
  | "ASK_CURRENT_SCOPE_EVIDENCE"
  | "HUMAN_EVIDENCE_REVIEW";
export type TaskType =
  | "CHECK_REPLACEMENT_STATUS"
  | "WAREHOUSE_FOLLOW_UP"
  | "REQUEST_EVIDENCE"
  | "HUMAN_EVIDENCE_REVIEW";
export type ResolutionExecutor =
  | "CONSUMER"
  | "BRAND"
  | "WAREHOUSE"
  | "LOGISTICS_PROVIDER"
  | "HUMAN_REVIEW_QUEUE";

export interface TaskPrefill {
  task_type: TaskType;
  existing_ticket_id: string | null;
  sku_id?: string;
  affected_component?: AffectedComponent;
  summary: string;
}

export interface CompiledServiceResponsibility {
  source_promise_text: string;
  commitment_class: CommitmentClass;
  activation_status: ActivationStatus;
  deadline: ISODateTime | null;
  next_check_at: ISODateTime | null;
  recovery_if_missed: string;
}

export interface ResolutionPath {
  candidate_type: ResolutionCandidateType;
  evidence_basis: string[];
  policy_basis: string;
  consumer_reply_draft: string;
  task_prefill: TaskPrefill;
  accountable_side: AccountableSide;
  executor: ResolutionExecutor;
  requires_human_approval: boolean;
  creates_obligation: boolean;
  compiled_service_responsibility: CompiledServiceResponsibility | null;
}

export interface DecisionResult {
  case_id: string;
  decision: Decision;
  rule_id: RuleId;
  rule_priority: RulePriority;
  accountability_state: AccountabilityState;
  challenge_mode: boolean;
  fact_trace: {
    evidence_status: EvidenceStatus;
    prepared_action: string;
    scope_match?: boolean | null;
    active_promise_count?: number;
    suppressed_rule_ids?: Array<Exclude<RuleId, "E0_NO_RULE_MATCHED">>;
  };
  reason: string;
  resolution_path: ResolutionPath;
}

// POST /api/cases/analyze — case_input 仅允许在 challenge_mode 中使用
export interface AnalyzeCaseRequest {
  case_id: string;
  evaluation_time?: ISODateTime;
  challenge_mode?: boolean;
  case_input?: CaseInput;
}
export interface AnalyzeCaseResponse {
  extracted_journey: ExtractedJourney;
  accountability_state: AccountabilityState;
  model_metadata: ExtractedJourney["model_metadata"];
}

// POST /api/actions/evaluate
export interface EvaluateActionRequest {
  case_id: string;
  prepared_action: PreparedAction;
  evaluation_time?: ISODateTime;
  challenge_mode?: boolean;
  challenge_overrides?: {
    requested_scope?: IssueScope;
    image_observation_overrides?: Array<{
      evidence_id: string;
      readability: "HIGH" | "LOW" | "UNKNOWN";
      sku_match?: "MATCH" | "MISMATCH" | "UNKNOWN";
      issue_visible?: boolean;
    }>;
  };
}
export type EvaluateActionResponse = DecisionResult;

/** C 端提案：原规范只描述了语义，尚无正式 JSON Schema。 */
export interface HumanResolutionEdits {
  executor?: ObligationExecutor;
  next_check_at?: ISODateTime;
  recovery_if_missed?: string;
}

// POST /api/resolutions/approve
export interface ApproveResolutionRequest {
  case_id: string;
  candidate_type: ResolutionCandidateType;
  approver_id: string;
  idempotency_key: string;
  human_edits: HumanResolutionEdits;
}
export interface ApproveResolutionResponse {
  accountability_state: AccountabilityState;
  approved_resolution: ResolutionPath;
  audit_trail: AuditTrailEntry[];
}

export type ShipmentEventType =
  | "SHIPMENT_PICKED_UP"
  | "SHIPMENT_NOT_PICKED_UP"
  | "SHIPMENT_DELIVERED";

// POST /api/events/shipment
export interface ShipmentEventRequest {
  case_id: string;
  event_id: string;
  event_type: ShipmentEventType;
  event_time: ISODateTime;
  idempotency_key: string;
}

export interface FollowUpCandidate {
  task_type: "WAREHOUSE_FOLLOW_UP";
  existing_ticket_id: string | null;
  priority: "NORMAL" | "HIGH";
  summary: string;
}

export interface SupervisorEscalationCandidate {
  escalation_type: "PROMISE_OVERDUE";
  priority: "HIGH";
  summary: string;
}

export interface ShipmentEventResponse {
  accountability_state: AccountabilityState;
  follow_up_candidate: FollowUpCandidate | null;
  supervisor_escalation_candidate: SupervisorEscalationCandidate | null;
  proactive_notification_draft: {
    text: string;
    commits_next_update_at: ISODateTime;
    requires_human_approval: true;
    channel: "ORIGINAL_CHAT";
  } | null;
}

export type ApiErrorCode =
  | "SCHEMA_INVALID"
  | "VALIDATION_ERROR"
  | "P0_PROHIBITED_ACTION"
  | "IDEMPOTENCY_CONFLICT"
  | "MODEL_UNAVAILABLE"
  | "MODEL_OUTPUT_INVALID"
  | "INVALID_EVENT_TRANSITION"
  | "INTERNAL_ERROR";

export type ApiResult<T> =
  | { data: T; error: null; request_id: string }
  | {
      data: null;
      error: {
        code: ApiErrorCode;
        message: string;
        retryable: boolean;
      };
      request_id: string;
    };

export interface CoveniaApi {
  analyzeCase(input: AnalyzeCaseRequest): Promise<ApiResult<AnalyzeCaseResponse>>;
  evaluateAction(
    input: EvaluateActionRequest,
  ): Promise<ApiResult<EvaluateActionResponse>>;
  approveResolution(
    input: ApproveResolutionRequest,
  ): Promise<ApiResult<ApproveResolutionResponse>>;
  pushShipmentEvent(
    input: ShipmentEventRequest,
  ): Promise<ApiResult<ShipmentEventResponse>>;
}

/**
 * C 端联调传输约定提案：
 * - Content-Type 固定为 application/json; charset=utf-8。
 * - X-Request-Id 用于把 UI 报错与后端日志串联。
 * - approve、shipment 会改变责任状态，必须在请求体携带 idempotency_key。
 * - 比赛本地环境暂不定义鉴权；接入真实千牛时另行增加，不塞入业务对象。
 */
export interface ApiRequestHeaders {
  "Content-Type": "application/json; charset=utf-8";
  "X-Request-Id": string;
}

export const API_HTTP_STATUS = {
  success: 200,
  validationError: 400,
  prohibitedAction: 400,
  stateConflict: 409,
  modelOutputInvalid: 502,
  internalError: 500,
  modelUnavailable: 503,
} as const;

export const API_ENDPOINTS = {
  analyzeCase: {
    method: "POST",
    path: "/api/cases/analyze",
    request: "AnalyzeCaseRequest",
    response: "ApiResult<AnalyzeCaseResponse>",
    uiTrigger: "加载或重置案例",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 20000,
  },
  evaluateAction: {
    method: "POST",
    path: "/api/actions/evaluate",
    request: "EvaluateActionRequest",
    response: "ApiResult<DecisionResult>",
    uiTrigger: "客服发送消息或执行关键动作之前",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 10000,
  },
  approveResolution: {
    method: "POST",
    path: "/api/resolutions/approve",
    request: "ApproveResolutionRequest",
    response: "ApiResult<ApproveResolutionResponse>",
    uiTrigger: "客服确认解决路径",
    changesResponsibilityState: true,
    requiresIdempotencyKey: true,
    suggestedTimeoutMs: 10000,
  },
  pushShipmentEvent: {
    method: "POST",
    path: "/api/events/shipment",
    request: "ShipmentEventRequest",
    response: "ApiResult<ShipmentEventResponse>",
    uiTrigger: "演示物流已揽收或未揽收",
    changesResponsibilityState: true,
    requiresIdempotencyKey: true,
    suggestedTimeoutMs: 10000,
  },
} as const;

/**
 * 插件按钮与四接口的唯一映射。
 * “生成解决回复”直接读取 DecisionResult.resolution_path.consumer_reply_draft，
 * “展示服务回执”直接读取 AccountabilityState.service_progress_receipt，
 * 两者都不增加接口。
 *
 * “查询补发进度”在 P0 中提交 CHECK_REPLACEMENT_PROGRESS 给 evaluateAction；
 * B 端需在该次处理时读取既有工单事实并返回解决路径，不另设第五个查询接口。
 */
export const UI_API_FLOW = {
  loadCase: "analyzeCase",
  attemptSendOrCriticalAction: "evaluateAction",
  checkReplacementProgress: "evaluateAction",
  generateReplyDraft: "read:DecisionResult.resolution_path.consumer_reply_draft",
  approveResolution: "approveResolution",
  showProgressReceipt:
    "read:AccountabilityState.service_progress_receipt",
  simulateShipmentPickedUp: "pushShipmentEvent",
  simulateShipmentNotPickedUp: "pushShipmentEvent",
} as const;
