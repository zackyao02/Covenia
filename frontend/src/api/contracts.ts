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

export interface DemoCustomerStateRefreshRequest {
  case_id: string;
  challenge_mode: true;
  messages: ConversationMessage[];
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
  hygiene_risk_signal: RiskLevel;
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
    model_id: string;
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
  demo_service_event?: DemoServiceEventType;
  demo_specialist?: string;
  demo_specialist_status?: "已接手" | "已反馈";
}

export interface AuditTrailEntry {
  at: ISODateTime;
  actor: string;
  action:
    | "ANALYZED"
    | "RESOLUTION_APPROVED"
    | "SHIPMENT_PICKED_UP"
    | "SHIPMENT_NOT_PICKED_UP"
    | "SHIPMENT_DELIVERED"
    | DemoServiceEventType;
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
export type RulePriority = 400 | 350 | 300 | 100 | 0;

export interface RuntimeMetrics {
  measurement_status: "MEASURED" | "NOT_MEASURED";
  input_tokens: number | null;
  output_tokens: number | null;
  inference_latency_ms: number | null;
  rule_substitution_count: number | null;
}

export interface SourceEvidence {
  source_id: string;
  source_type: "CHAT" | "IMAGE" | "ORDER" | "TICKET" | "LOGISTICS" | "SYSTEM_EVENT" | "HUMAN_EDIT";
  source_label: string;
  observed_at: ISODateTime | null;
  claim: string;
  field_path?: string;
  confidence: number;
  derived_time?: boolean;
}

export interface EmotionState {
  current_label: "CALM" | "ANXIOUS" | "FRUSTRATED" | "CONFUSED" | "URGENT" | "UNKNOWN";
  trend: "STABLE" | "IMPROVING" | "WORSENING" | "UNKNOWN";
  cause: string;
  communication_guidance: string;
  source_evidence_ids: string[];
  confidence: number;
  probability?: number | null;
  risk_scoring_allowed: false;
}

export interface RiskState {
  case_id: string;
  score: number;
  level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  factors: Array<{
    factor_type: "PROMISE_OVERDUE" | "REPEAT_CONTACT" | "EVIDENCE_CONFLICT" | "HUMAN_REVIEW_REQUIRED" | "FULFILLMENT_STALLED" | "EFFORT_HIGH";
    weight: number;
    reason: string;
    source_evidence_ids: string[];
  }>;
  prediction: false;
  source_evidence_ids: string[];
}

export interface PriorityState {
  case_id: string;
  rank: number;
  band: "RED" | "ORANGE" | "YELLOW" | "NORMAL";
  priority_score: number;
  queue_reasons: string[];
  next_best_action: string;
}

export interface EmergingIssue {
  issue_id: string;
  fingerprint: {
    sku_id: string;
    affected_component: AffectedComponent;
    issue_type: IssueType;
  };
  window: {
    started_at: ISODateTime;
    ended_at: ISODateTime;
  };
  independent_consumer_count: number;
  status: "WATCHING" | "EMERGING_CANDIDATE" | "CONFIRMED" | "DISMISSED";
  requires_human_confirmation: boolean;
  prediction: false;
  source_evidence_ids: string[];
}

export interface DeadlineState {
  case_id: string;
  promise_id: string;
  status: "SCHEDULED" | "NEAR_DUE" | "OVERDUE" | "ESCALATED" | "CLOSED";
  deadline: ISODateTime;
  next_check_at: ISODateTime;
  monitor_status: "WAITING" | "RUNNING" | "FAILED" | "CLOSED";
  escalated_once: boolean;
  risk_state_id: string | null;
  priority_state_id: string | null;
  audit_event_id: string | null;
}

export interface JEVDecisionAdvisory {
  assessment_id: string;
  customer_state_version: string;
  source: "JEV" | "RULE_FALLBACK";
  status: "READY" | "FALLBACK";
  configured: boolean;
  jev_call: {
    configured: boolean;
    attempted: boolean;
    succeeded: boolean;
    fallback_used: boolean;
    error_code?: string | null;
  };
  emotion: {
    trend: EmotionState["trend"];
    probability: number | null;
    threshold: number;
    source: "JEV" | "RULE_FALLBACK";
  };
  human_escalation: {
    required: boolean;
    probability: number | null;
    threshold: number;
    source: "JEV" | "RULE_FALLBACK" | "RULE";
  };
  next_best_action: {
    recommended:
      | "CHECK_REPLACEMENT"
      | "HUMAN_ESCALATION"
      | "CONTINUE_TROUBLESHOOTING"
      | "REQUEST_EVIDENCE";
    probability: number | null;
    threshold: number;
    source: "JEV" | "RULE_FALLBACK";
  };
  deterministic_signals: {
    promise_overdue: boolean;
    repeated_contact: boolean;
    conversation_count: number;
    evidence_status: EvidenceStatus | "UNKNOWN";
    has_open_obligation: boolean;
    needs_human_by_rule: boolean;
  };
  audit: {
    assessment_id: string;
    case_id: string;
    customer_state_version: string;
    source: "JEV" | "RULE_FALLBACK";
    jev_call: {
      configured: boolean;
      attempted: boolean;
      succeeded: boolean;
      fallback_used: boolean;
      error_code?: string | null;
    };
    model_version?: string | null;
    questions: string[];
    thresholds: Record<string, number>;
    final_decision: Record<string, string | boolean>;
    provider_error?: { code: string; message: string } | null;
    latency_ms: number;
    created_at: ISODateTime;
    pii_masked_count?: number;
    thresholds_validated?: boolean;
  };
}

export interface CustomerDecision {
  case_id: string;
  decision: Decision;
  reason: string;
  rule_id?: RuleId;
  jev_assessment_id?: string | null;
  decision_advisory?: JEVDecisionAdvisory;
  source_evidence_ids: string[];
  next_action: string;
  human_review_required: boolean;
}

export interface CustomerState {
  case_id: string;
  service_clock?: ISODateTime;
  facts: Array<{
    fact_id: string;
    statement: string;
    source_evidence_ids: string[];
  }>;
  evidence: {
    status: EvidenceStatus;
    known: string[];
    missing: string[];
    do_not_ask_again: string[];
  };
  intent: {
    current_goal: string;
    constraints: string[];
    accepted_solutions: string[];
    rejected_solutions: string[];
    source_evidence_ids: string[];
  };
  emotion: EmotionState;
  effort: {
    score: number;
    level: "LOW" | "MEDIUM" | "HIGH";
    signals: string[];
  };
  actions: {
    next_best_action: string;
    blocked_actions: string[];
    allowed_actions: string[];
    human_review_actions: string[];
  };
  promises: {
    active: string[];
    deadline_state: DeadlineState;
  };
  risk: RiskState;
  decision: CustomerDecision;
  decision_advisory?: JEVDecisionAdvisory;
  resolution: {
    status: "NOT_STARTED" | "DRAFTED" | "APPROVED" | "IN_PROGRESS" | "AT_RISK" | "RESOLVED";
    current_path: string;
    consumer_reply_draft: string;
    service_progress_receipt_id: string | null;
  };
  source_evidence: SourceEvidence[];
}

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
  runtime_metrics: RuntimeMetrics;
  draft_assessment?: DraftAssessment;
}

export interface DraftAssessment {
  kind: "EVIDENCE_REQUEST" | "PROGRESS_UPDATE" | "NEW_COMMITMENT" | "CLOSE_CASE" | "UNCLASSIFIED";
  requires_confirmation: boolean;
  explanation: string;
  evaluated_text: string;
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
  customer_state?: CustomerState;
  risk_state?: RiskState;
  deadline_state?: DeadlineState;
  model_metadata: ExtractedJourney["model_metadata"];
  runtime_metrics: RuntimeMetrics;
}

// POST /api/actions/evaluate
export interface EvaluateActionRequest {
  case_id: string;
  prepared_action: PreparedAction;
  draft_reply?: string;
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
  /** 兼容字段：服务端一律忽略，保留以验证 A21。 */
  evidence_status?: unknown;
  active_commitments?: unknown;
  prohibited_actions?: unknown;
  current_scope?: unknown;
  accountability_state?: unknown;
}
export type EvaluateActionResponse = DecisionResult;

/** C 端提案：原规范只描述了语义，尚无正式 JSON Schema。 */
export interface HumanResolutionEdits {
  executor?: ObligationExecutor;
  next_check_at?: ISODateTime;
  recovery_if_missed?: string;
  consumer_reply?: string;
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

export type DemoServiceEventType = "CURRENT_SCOPE_EVIDENCE_SUBMITTED" | "SPECIALIST_ASSIGNED" | "SPECIALIST_FOLLOWED_UP";

export interface DemoServiceEventRequest {
  case_id: "DEMO_002" | "DEMO_003";
  event_type: DemoServiceEventType;
  idempotency_key: string;
}

export interface DemoServiceEventResponse {
  accountability_state: AccountabilityState;
  event_summary: string;
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
  resetDemoSession(caseId: string): Promise<ApiResult<{ case_id: string; reset: true }>>;
  getCustomerState(caseId: string): Promise<ApiResult<CustomerState>>;
  refreshDemoCustomerState(input: DemoCustomerStateRefreshRequest): Promise<ApiResult<CustomerState>>;
  getPriority(): Promise<ApiResult<PriorityState[]>>;
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
  pushDemoServiceEvent(input: DemoServiceEventRequest): Promise<ApiResult<DemoServiceEventResponse>>;
  getRiskStates?(): Promise<ApiResult<RiskState[]>>;
  getPriorityStates?(): Promise<ApiResult<PriorityState[]>>;
  getEmergingIssues?(): Promise<ApiResult<EmergingIssue[]>>;
  createDecision?(input: EvaluateActionRequest): Promise<ApiResult<CustomerDecision | DecisionResult>>;
  getDeadlineStates?(): Promise<ApiResult<DeadlineState[]>>;
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
  getCustomerState: {
    method: "GET",
    path: "/api/customer-state/:case_id",
    request: "case_id",
    response: "ApiResult<CustomerState>",
    uiTrigger: "打开新版 Customer Workspace",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 5000,
  },
  refreshDemoCustomerState: {
    method: "POST",
    path: "/api/demo/customer-state/refresh",
    request: "DemoCustomerStateRefreshRequest",
    response: "ApiResult<CustomerState>",
    uiTrigger: "本地模拟顾客产生新回复",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 20000,
  },
  getRiskStates: {
    method: "GET",
    path: "/api/risk",
    request: "none",
    response: "ApiResult<RiskState[]>",
    uiTrigger: "Risk Radar 刷新",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 5000,
  },
  getPriorityStates: {
    method: "GET",
    path: "/api/priority",
    request: "none",
    response: "ApiResult<PriorityState[]>",
    uiTrigger: "Priority Queue 刷新",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 5000,
  },
  getEmergingIssues: {
    method: "GET",
    path: "/api/emerging-issues",
    request: "none",
    response: "ApiResult<EmergingIssue[]>",
    uiTrigger: "流程风险候选刷新",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 5000,
  },
  createDecision: {
    method: "POST",
    path: "/api/decisions",
    request: "EvaluateActionRequest",
    response: "ApiResult<CustomerDecision | DecisionResult>",
    uiTrigger: "新版工作区生成轻量决策",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 10000,
  },
  getDeadlines: {
    method: "GET",
    path: "/api/deadlines",
    request: "none",
    response: "ApiResult<DeadlineState[]>",
    uiTrigger: "Deadline Monitor 展示",
    changesResponsibilityState: false,
    requiresIdempotencyKey: false,
    suggestedTimeoutMs: 5000,
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
