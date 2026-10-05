"""Strict, schema-backed public types and internal-only domain DTOs.

The public models mirror the BATCH-03 locked JSON Schema files.  The internal
DTOs deliberately separate model candidates from server-owned evidence,
commitments, and ledger state so a candidate can never be mistaken for a final
fact merely by its type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Generic, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

from covenia_b.domain.time import Rfc3339Timestamp
from covenia_b.domain.validation import validate_contract_payload

type StrictText = StrictStr
type NonEmptyText = Annotated[StrictStr, Field(min_length=1)]
type NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
type Confidence = Annotated[StrictInt | float, Field(ge=0, le=1)]

type IssueType = Literal["PACKAGE_DAMAGE", "LOGISTICS_STALLED", "ADVERSE_REACTION"]
type AffectedComponent = Literal[
    "BOTTLE", "PUMP", "CAP", "SEAL", "OUTER_PACKAGE", "UNKNOWN"
]
type AccountableSide = Literal["CONSUMER", "BRAND", "UNKNOWN"]
type EvidenceStatus = Literal["VALID", "MISMATCHED", "NEED_HUMAN_REVIEW"]


class DomainModel(BaseModel):
    """Immutable strict base class for public fields and nested DTO shapes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SchemaBackedModel(DomainModel):
    """A model with a stable entry point to its locked JSON Schema contract."""

    SCHEMA_NAME: ClassVar[str]

    @classmethod
    def from_contract(cls: type[Self], payload: Any) -> Self:
        """Validate incoming JSON Schema first, then parse and revalidate output."""

        validate_contract_payload(cls.SCHEMA_NAME, payload)
        parsed = cls.model_validate(payload)
        parsed.to_contract()
        return parsed

    def to_contract(self) -> dict[str, Any]:
        """Serialize the model and prove that serialization still matches its schema."""

        payload = self.model_dump(mode="json", exclude_unset=True)
        validate_contract_payload(self.SCHEMA_NAME, payload)
        return payload


class ErrorPayload(DomainModel):
    """The transport-neutral error shape embedded in an API envelope."""

    code: Literal[
        "SCHEMA_INVALID",
        "VALIDATION_ERROR",
        "P0_PROHIBITED_ACTION",
        "INVALID_EVENT_TRANSITION",
        "IDEMPOTENCY_CONFLICT",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
        "INTERNAL_ERROR",
    ]
    message: NonEmptyText
    retryable: StrictBool


PayloadT = TypeVar("PayloadT")


class ApiEnvelope(SchemaBackedModel, Generic[PayloadT]):
    """Schema-backed success-or-error transport envelope without FastAPI coupling."""

    SCHEMA_NAME: ClassVar[str] = "api-envelope.schema.json"

    data: PayloadT | None
    error: ErrorPayload | None
    request_id: NonEmptyText

    @model_validator(mode="after")
    def require_exactly_one_result(self) -> Self:
        """Match the envelope schema's exclusive success/error alternatives."""

        if (self.data is None) == (self.error is None):
            raise ValueError("exactly one of data and error must be non-null")
        return self


class RuntimeMetrics(SchemaBackedModel):
    """Observed counters; no inferred or fabricated model usage fields exist here."""

    SCHEMA_NAME: ClassVar[str] = "runtime-metrics.schema.json"

    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    inference_latency_ms: NonNegativeInt
    rule_substitution_count: NonNegativeInt


class DataProvenance(DomainModel):
    source_dataset: Literal["TIANCHI_LOREAL_TRACK1_MOCK"]
    source_session_id: NonEmptyText
    augmentation_notes: list[StrictText]


class ConversationMessage(DomainModel):
    message_id: StrictText
    timestamp: Rfc3339Timestamp
    speaker: Literal["CONSUMER", "AGENT", "SYSTEM"]
    text: NonEmptyText
    source_kind: Literal["COMPETITION_MOCK", "DEMO_AUGMENTATION"]


class OrderItem(DomainModel):
    fulfillment_item_id: StrictText
    sku_id: StrictText
    product_name: StrictText
    batch_code: StrictText | None = None
    item_role: Literal["PRIMARY", "GIFT", "BUNDLE_COMPONENT"]


class Order(DomainModel):
    order_id: StrictText
    channel: Literal["TIANCHI_MOCK_QIANNIU"]
    items: Annotated[list[OrderItem], Field(min_length=1)]
    original_logistics_number: StrictText


class ServiceTicket(DomainModel):
    ticket_id: StrictText
    ticket_type: Literal[
        "REPLACEMENT", "OFFLINE_PAYMENT", "LOGISTICS", "ADVERSE_REACTION", "RETURN"
    ]
    status: StrictText
    assignee_id: StrictText
    executor_name: StrictText | None = None
    replacement_logistics_number: StrictText | None = None
    created_at: Rfc3339Timestamp
    completed_at: Rfc3339Timestamp | None = None
    source_sheet: StrictText


class EvidenceImage(DomainModel):
    evidence_id: StrictText
    file_name: StrictText
    submitted_at: Rfc3339Timestamp
    declared_view_type: Literal["PRODUCT_OVERVIEW", "ISSUE_DETAIL", "PACKAGE_CONTEXT", "OTHER"]
    source_kind: Literal["TEAM_SYNTHETIC_RECREATION", "TEAM_SYNTHETIC_AUGMENTATION"]
    source_message_id: StrictText
    competition_reference_path: StrictText | None = None


class CurrentIssue(DomainModel):
    fulfillment_item_id: StrictText
    sku_id: StrictText
    issue_type: IssueType
    affected_component: AffectedComponent | None = None


class Scope(DomainModel):
    """A schema-preserving scope whose identifiers are always strings."""

    order_id: StrictText
    fulfillment_item_id: StrictText
    sku_id: StrictText
    issue_type: IssueType


class CaseInput(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "case-input.schema.json"

    case_id: NonEmptyText
    data_provenance: DataProvenance
    evaluation_time: Rfc3339Timestamp
    conversation: Annotated[list[ConversationMessage], Field(min_length=1)]
    order: Order
    service_tickets: list[ServiceTicket]
    evidence_images: Annotated[list[EvidenceImage], Field(min_length=1)]
    current_issue: CurrentIssue
    policy_requirement_id: Literal["DEMO_POLICY_PACKAGE_DAMAGE_V1"]


class CompletedActions(DomainModel):
    issue_explained: StrictBool
    order_verified: StrictBool
    evidence_submitted: StrictBool


class PromiseEvent(DomainModel):
    raw_text: NonEmptyText
    promise_type: NonEmptyText
    commitment_class: Literal[
        "STANDARD_APPROVED",
        "APPROVAL_REQUIRED",
        "CONDITIONAL",
        "ERRONEOUS_OR_UNAUTHORIZED",
        "AMBIGUOUS",
    ]
    activation_recommendation: Literal["ACTIVE", "PENDING_APPROVAL", "BLOCKED", "IGNORED"]
    conditions: list[StrictText]
    committed_at: Rfc3339Timestamp
    deadline: Rfc3339Timestamp | None
    confidence: Confidence
    source_ids: Annotated[list[StrictText], Field(min_length=1)]


class ImageObservation(DomainModel):
    evidence_id: StrictText
    readability: Literal["HIGH", "LOW", "UNKNOWN"]
    product_identifiable: StrictBool
    sku_match: Literal["MATCH", "MISMATCH", "UNKNOWN"]
    product_role: Literal["PRIMARY", "GIFT", "BUNDLE_COMPONENT", "UNKNOWN"]
    issue_visible: StrictBool
    affected_component: AffectedComponent
    view_type: Literal["PRODUCT_OVERVIEW", "ISSUE_DETAIL", "PACKAGE_CONTEXT", "OTHER"]
    coverage: list[
        Literal[
            "PRODUCT_IDENTITY",
            "AFFECTED_COMPONENT",
            "DAMAGE_DETAIL",
            "PACKAGE_CONTEXT",
            "BATCH_LABEL",
        ]
    ]
    integrity_concern: StrictBool
    hygiene_risk_signal: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    confidence: Confidence


class JourneyUnderstanding(DomainModel):
    consumer_intent: NonEmptyText
    experience_expression: NonEmptyText
    service_cause: NonEmptyText
    latent_need: NonEmptyText
    cooperation_willingness: Literal["STABLE", "DECLINING", "LOW", "UNKNOWN"]
    action_impact: NonEmptyText
    source_ids: Annotated[list[StrictText], Field(min_length=1)]


class SourceTrace(DomainModel):
    field: StrictText
    source_type: Literal["CHAT", "IMAGE", "ORDER", "TICKET"]
    source_id: StrictText


class ModelMetadata(DomainModel):
    model_id: Literal["qwen3-vl-plus"]
    model_revision: StrictText | None = None
    prompt_version: StrictText
    run_id: StrictText
    cached_result: StrictBool


class ExtractedJourney(SchemaBackedModel):
    """Schema projection of an extraction; callers must treat it as candidate input."""

    SCHEMA_NAME: ClassVar[str] = "extracted-journey.schema.json"

    case_id: StrictText
    completed_actions: CompletedActions
    promise_events: list[PromiseEvent]
    image_observations: list[ImageObservation]
    extracted_scope: Scope
    journey_understanding: JourneyUnderstanding
    source_trace: list[SourceTrace]
    model_metadata: ModelMetadata


class ActiveCommitment(DomainModel):
    promise_type: StrictText
    raw_text: StrictText
    status: Literal["ACTIVE", "AT_RISK", "COMPLETED"]
    deadline: Rfc3339Timestamp
    source_ids: Annotated[list[StrictText], Field(min_length=1)]


class TraceableServiceFact(DomainModel):
    fact_type: Literal[
        "ISSUE_EXPLAINED",
        "EVIDENCE_SUBMITTED",
        "TICKET_CREATED",
        "PROMISE_ACTIVE",
        "PROMISE_OVERDUE",
        "REPEAT_CONTACT",
        "OTHER",
    ]
    statement: NonEmptyText
    source_ids: Annotated[list[StrictText], Field(min_length=1)]


class ResponsibilityJudgment(DomainModel):
    consumer_input_complete: StrictBool
    accountable_side: AccountableSide


class ExperienceGapDiagnosis(DomainModel):
    consumer_expression: NonEmptyText
    traceable_service_facts: Annotated[list[TraceableServiceFact], Field(min_length=1)]
    deterioration_cause: NonEmptyText
    latent_need: NonEmptyText
    responsibility_judgment: ResponsibilityJudgment
    action_impacts: Annotated[
        list[
            Literal[
                "BLOCK_REPEAT_EVIDENCE",
                "RAISE_PRIORITY",
                "ROUTE_TO_HUMAN",
                "CHECK_EXISTING_FULFILLMENT",
                "REQUEST_MISSING_INPUT",
                "START_PROACTIVE_UPDATE",
            ]
        ],
        Field(min_length=1),
    ]
    reply_strategy: NonEmptyText


class OpenObligation(DomainModel):
    obligation_type: Literal["REPLACEMENT_FULFILLMENT"]
    status: Literal["ON_TRACK", "AT_RISK", "COMPLETED"]
    accountable_side: Literal["BRAND"]
    executor: Literal["BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"]
    deadline: Rfc3339Timestamp
    next_check_at: Rfc3339Timestamp
    milestone: Literal["AWAITING_CARRIER_PICKUP", "IN_TRANSIT", "DELIVERED"]
    resolution_condition: Literal["REPLACEMENT_DELIVERED"]


class ServiceProgressReceipt(DomainModel):
    receipt_id: StrictText
    status: Literal["ACTIVE", "AT_RISK", "COMPLETED"]
    received_evidence: list[StrictText]
    brand_action: NonEmptyText
    latest_update_at: Rfc3339Timestamp
    next_update_by: Rfc3339Timestamp
    consumer_action_required: StrictBool
    recovery_if_missed: StrictText


class AuditEntry(DomainModel):
    at: Rfc3339Timestamp
    actor: NonEmptyText
    action: Literal[
        "ANALYZED",
        "RESOLUTION_APPROVED",
        "SHIPMENT_PICKED_UP",
        "SHIPMENT_NOT_PICKED_UP",
        "SHIPMENT_DELIVERED",
    ]
    changed_fields: list[StrictText]
    request_id: NonEmptyText


class AccountabilityState(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "accountability-state.schema.json"

    case_id: StrictText
    case_status: Literal[
        "WAITING_FOR_CONSUMER",
        "READY_FOR_BRAND",
        "ACTION_REVIEW",
        "IN_FULFILLMENT",
        "AT_RISK",
        "RESOLVED",
    ]
    consumer_input_required: StrictBool
    accountable_side: AccountableSide
    evidence_status: EvidenceStatus
    current_scope: Scope
    active_commitments: list[ActiveCommitment]
    prohibited_actions: list[
        Literal[
            "ASK_SAME_EVIDENCE",
            "ASK_REPEAT_EXPLANATION",
            "SHIFT_FOLLOW_UP_TO_CONSUMER",
            "MAKE_UNTRACKABLE_PROMISE",
            "CLOSE_BEFORE_RESOLUTION",
        ]
    ]
    experience_gap_diagnosis: ExperienceGapDiagnosis
    open_obligation: OpenObligation | None
    service_progress_receipt: ServiceProgressReceipt | None
    experience_risk: Literal["LOW", "MEDIUM", "HIGH"]
    audit_trail: list[AuditEntry]


class PreparedAction(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "prepared-action.schema.json"

    action_id: NonEmptyText
    action_type: Literal[
        "ASK_EVIDENCE",
        "CHECK_REPLACEMENT_PROGRESS",
        "CREATE_FOLLOW_UP_TASK",
        "CLOSE_CASE",
        "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "REPEAT_EXPLANATION_REQUEST",
    ]
    requested_scope: Scope | None = None
    requires_human_approval: StrictBool

    @model_validator(mode="after")
    def require_scope_for_evidence_request(self) -> Self:
        if self.action_type == "ASK_EVIDENCE" and self.requested_scope is None:
            raise ValueError("ASK_EVIDENCE requires requested_scope")
        return self


class FactTrace(DomainModel):
    evidence_status: EvidenceStatus
    prepared_action: StrictText
    scope_match: StrictBool | None = None
    active_promise_count: NonNegativeInt | None = None
    suppressed_rule_ids: list[Literal["P0_PROHIBITED_ACTION", "E1", "E2", "H1"]] | None = None


class TaskPrefill(DomainModel):
    task_type: Literal[
        "CHECK_REPLACEMENT_STATUS",
        "WAREHOUSE_FOLLOW_UP",
        "REQUEST_EVIDENCE",
        "HUMAN_EVIDENCE_REVIEW",
    ]
    existing_ticket_id: StrictText | None
    sku_id: StrictText | None = None
    affected_component: AffectedComponent | None = None
    summary: NonEmptyText


class CompiledServiceResponsibility(DomainModel):
    source_promise_text: StrictText
    commitment_class: Literal[
        "STANDARD_APPROVED",
        "APPROVAL_REQUIRED",
        "CONDITIONAL",
        "ERRONEOUS_OR_UNAUTHORIZED",
        "AMBIGUOUS",
    ]
    activation_status: Literal["ACTIVE", "PENDING_APPROVAL", "BLOCKED", "IGNORED"]
    deadline: Rfc3339Timestamp | None
    next_check_at: Rfc3339Timestamp | None
    recovery_if_missed: StrictText


class ResolutionPath(DomainModel):
    candidate_type: Literal[
        "CHECK_REPLACEMENT_FULFILLMENT",
        "ASK_CURRENT_SCOPE_EVIDENCE",
        "HUMAN_EVIDENCE_REVIEW",
    ]
    evidence_basis: list[StrictText]
    policy_basis: NonEmptyText
    consumer_reply_draft: NonEmptyText
    task_prefill: TaskPrefill
    accountable_side: AccountableSide
    executor: Literal[
        "CONSUMER", "BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER", "HUMAN_REVIEW_QUEUE"
    ]
    requires_human_approval: StrictBool
    creates_obligation: StrictBool
    compiled_service_responsibility: CompiledServiceResponsibility | None


class DecisionResult(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "decision-result.schema.json"

    case_id: StrictText
    decision: Literal["INTERVENE", "ALLOW", "HUMAN_REVIEW"]
    rule_id: Literal["E1", "E2", "H1", "E0_NO_RULE_MATCHED"]
    rule_priority: Literal[350, 300, 100, 0]
    accountability_state: AccountabilityState
    challenge_mode: StrictBool
    fact_trace: FactTrace
    reason: NonEmptyText
    resolution_path: ResolutionPath
    runtime_metrics: RuntimeMetrics

    @model_validator(mode="after")
    def match_locked_rule_outcome(self) -> Self:
        expected = {
            "E1": ("INTERVENE", 300),
            "H1": ("HUMAN_REVIEW", 350),
            "E2": ("ALLOW", 100),
            "E0_NO_RULE_MATCHED": ("ALLOW", 0),
        }[self.rule_id]
        if (self.decision, self.rule_priority) != expected:
            raise ValueError("decision and priority must match the locked rule mapping")
        return self


class ChallengeImageObservationOverride(DomainModel):
    evidence_id: StrictText
    readability: Literal["HIGH", "LOW", "UNKNOWN"]
    sku_match: Literal["MATCH", "MISMATCH", "UNKNOWN"] | None = None
    issue_visible: StrictBool | None = None


class ChallengeOverrides(DomainModel):
    requested_scope: Scope | None = None
    image_observation_overrides: Annotated[
        list[ChallengeImageObservationOverride] | None,
        Field(min_length=1),
    ] = None

    @model_validator(mode="after")
    def require_an_override(self) -> Self:
        if self.requested_scope is None and self.image_observation_overrides is None:
            raise ValueError("challenge_overrides must contain at least one override")
        return self


class EvaluateActionRequest(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "evaluate-action-request.schema.json"

    case_id: NonEmptyText
    prepared_action: PreparedAction
    evaluation_time: Rfc3339Timestamp | None = None
    challenge_mode: StrictBool = False
    challenge_overrides: Any | None = None
    accountability_state: Any | None = None
    evidence_status: Any | None = None
    active_commitments: Any | None = None
    prohibited_actions: Any | None = None
    current_scope: Any | None = None

    @model_validator(mode="after")
    def validate_enabled_challenge_overrides(self) -> Self:
        if self.challenge_mode and self.challenge_overrides is not None:
            ChallengeOverrides.model_validate(self.challenge_overrides)
        return self


class AnalyzeCaseRequest(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "analyze-case-request.schema.json"

    case_id: NonEmptyText
    evaluation_time: Rfc3339Timestamp | None = None
    challenge_mode: StrictBool = False
    case_input: CaseInput | None = None

    @model_validator(mode="after")
    def require_enabled_challenge_for_case_input(self) -> Self:
        if self.case_input is not None and not self.challenge_mode:
            raise ValueError("case_input requires an explicit true challenge_mode")
        return self


class AnalyzeCaseResponse(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "analyze-case-response.schema.json"

    extracted_journey: ExtractedJourney
    accountability_state: AccountabilityState
    model_metadata: ModelMetadata
    runtime_metrics: RuntimeMetrics


class HumanEdits(DomainModel):
    executor: Literal["BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"] | None = None
    next_check_at: Rfc3339Timestamp | None = None
    recovery_if_missed: NonEmptyText | None = None


class ApproveResolutionRequest(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "approve-resolution-request.schema.json"

    case_id: NonEmptyText
    candidate_type: Literal[
        "CHECK_REPLACEMENT_FULFILLMENT",
        "ASK_CURRENT_SCOPE_EVIDENCE",
        "HUMAN_EVIDENCE_REVIEW",
    ]
    approver_id: NonEmptyText
    idempotency_key: Annotated[StrictStr, Field(min_length=8, max_length=128)]
    human_edits: HumanEdits


class ApproveResolutionResponse(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "approve-resolution-response.schema.json"

    accountability_state: AccountabilityState
    approved_resolution: ResolutionPath
    audit_trail: Annotated[list[AuditEntry], Field(min_length=1)]

    @model_validator(mode="after")
    def require_approval_audit_entry(self) -> Self:
        if not any(entry.action == "RESOLUTION_APPROVED" for entry in self.audit_trail):
            raise ValueError("audit_trail requires a RESOLUTION_APPROVED entry")
        return self


class ShipmentEventRequest(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "shipment-event-request.schema.json"

    case_id: NonEmptyText
    event_id: NonEmptyText
    event_type: Literal[
        "SHIPMENT_PICKED_UP", "SHIPMENT_NOT_PICKED_UP", "SHIPMENT_DELIVERED"
    ]
    event_time: Rfc3339Timestamp
    idempotency_key: Annotated[StrictStr, Field(min_length=8, max_length=128)]


class FollowUpCandidate(DomainModel):
    task_type: Literal["WAREHOUSE_FOLLOW_UP"]
    existing_ticket_id: StrictText | None
    priority: Literal["NORMAL", "HIGH"]
    summary: NonEmptyText


class SupervisorEscalationCandidate(DomainModel):
    escalation_type: Literal["PROMISE_OVERDUE"]
    priority: Literal["HIGH"]
    summary: NonEmptyText


class ProactiveNotificationDraft(DomainModel):
    text: NonEmptyText
    commits_next_update_at: Rfc3339Timestamp
    requires_human_approval: Literal[True]
    channel: Literal["ORIGINAL_CHAT"]


class ShipmentEventResponse(SchemaBackedModel):
    SCHEMA_NAME: ClassVar[str] = "shipment-event-response.schema.json"

    accountability_state: AccountabilityState
    follow_up_candidate: FollowUpCandidate | None
    supervisor_escalation_candidate: SupervisorEscalationCandidate | None
    proactive_notification_draft: ProactiveNotificationDraft | None


# Internal-only DTOs.  These are not schema projections and must not be sent
# through the API envelope until a later module explicitly builds one.


@dataclass(frozen=True, slots=True)
class RowProvenance:
    source_sheet: str
    row_number: int
    column_name: str

    def __post_init__(self) -> None:
        if self.row_number < 1:
            raise ValueError("row_number must be one-based")


@dataclass(frozen=True, slots=True)
class ImportedDataset:
    dataset_id: str
    source_workbook_sha256: str
    rows: tuple[RowProvenance, ...]


@dataclass(frozen=True, slots=True)
class CandidateExtraction:
    """Untrusted model candidate; it cannot represent final responsibility."""

    case_id: str
    model_metadata: ModelMetadata
    observations: tuple[str, ...]
    source_trace: tuple[SourceTrace, ...]
    candidate_promise_texts: tuple[str, ...]
    candidate_only: Literal[True] = True


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    """Server-owned evidence aggregation, separate from model observations."""

    evidence_status: EvidenceStatus
    source_ids: tuple[str, ...]
    unread_image_ids: tuple[str, ...]
    conflicts_present: bool


@dataclass(frozen=True, slots=True)
class CompiledCommitment:
    source_promise_text: str
    commitment_class: str
    activation_status: str
    deadline: Rfc3339Timestamp | None
    next_check_at: Rfc3339Timestamp | None


@dataclass(frozen=True, slots=True)
class CompiledCommitments:
    """Server-owned commitment output, never a direct model-provider result."""

    commitments: tuple[CompiledCommitment, ...]
    compiled_from_evidence: bool


@dataclass(frozen=True, slots=True)
class ResolvedImage:
    evidence_id: str
    media_type: str
    content_sha256: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class SanitizedModelInput:
    case_id: str
    redacted_text: str
    images: tuple[ResolvedImage, ...]
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    """Internal persistence state; version and high-watermark are not API fields."""

    case_id: str
    version: int
    event_high_watermark: Rfc3339Timestamp | None
    accountability_state: AccountabilityState | None
    compiled_commitments: CompiledCommitments

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("ledger version cannot be negative")
