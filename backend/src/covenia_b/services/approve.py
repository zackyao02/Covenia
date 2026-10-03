"""Atomic, transport-free human approval of server-validated resolution paths.

Only the SQLite transaction callback sees and evaluates the current ledger
snapshot.  The request contributes an idempotency identity and the three
approved human-edit fields; it cannot supply an approved time, responsibility,
status, refund, or a precomputed client plan.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import uuid4

from covenia_b.domain.time import require_aware_datetime
from covenia_b.domain.types import (
    AccountabilityState,
    ActiveCommitment,
    ApproveResolutionRequest,
    ApproveResolutionResponse,
    AuditEntry,
    CompiledCommitment,
    CompiledCommitments,
    CompiledServiceResponsibility,
    LedgerSnapshot,
    OpenObligation,
    ResolutionPath,
    ServiceProgressReceipt,
    TaskPrefill,
)
from covenia_b.domain.validation import ContractValidationError, validate_contract_payload
from covenia_b.ports.contracts import Clock
from covenia_b.ports.errors import LedgerConflict, LedgerUnavailable
from covenia_b.receipts import NotificationDraft, ProgressLedger, ProgressStatus, project_progress
from covenia_b.resolutions.reply_templates import render_consumer_reply
from covenia_b.storage import IdempotencyConflict, Mutation, StoredResponse, TransactionResult

CandidateType = Literal[
    "CHECK_REPLACEMENT_FULFILLMENT",
    "ASK_CURRENT_SCOPE_EVIDENCE",
    "HUMAN_EVIDENCE_REVIEW",
]

_EDITABLE_FIELDS = ("executor", "next_check_at", "recovery_if_missed")
_FULFILLMENT_CANDIDATE: CandidateType = "CHECK_REPLACEMENT_FULFILLMENT"
_DEFAULT_RECOVERY = "The brand will escalate the follow-up if the update is missed."
_DEFAULT_BRAND_ACTION = "The brand is following up on the approved fulfillment."


class ApprovalServiceError(RuntimeError):
    """Transport-neutral base error for the future approve endpoint."""

    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, *, request_id: str) -> None:
        super().__init__(message)
        self.request_id = request_id


class ApprovalInputError(ApprovalServiceError):
    """The submitted approval request is invalid or outside its frozen scope."""

    code = "VALIDATION_ERROR"


class ApprovalCandidateInvalid(ApprovalInputError):
    """The candidate is not legal for the current locked server snapshot."""


class ApprovalConflictError(ApprovalServiceError):
    """A case-scoped idempotency key was reused with a different request body."""

    code = "IDEMPOTENCY_CONFLICT"


class ApprovalInfrastructureError(ApprovalServiceError):
    """The approved transaction boundary could not safely complete."""

    retryable = True


class ApprovalTransactionRepository(Protocol):
    """The BATCH-18 atomic request/replay boundary consumed by this service."""

    def execute(
        self,
        *,
        case_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, Any],
        mutate: Callable[[LedgerSnapshot | None], Mutation],
        expected_version: int | None = None,
    ) -> TransactionResult: ...


@dataclass(frozen=True, slots=True)
class ApprovalDiagnostics:
    """Internal trace fields deliberately separate from the frozen public audit."""

    submitted_fields: tuple[str, ...]
    derived_projection_fields: tuple[str, ...]
    effective_projection_values: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ApprovalExecution:
    """The typed public response plus non-transport approval execution details."""

    response: ApproveResolutionResponse
    request_id: str
    replayed: bool
    replay_source: str | None
    status_code: int
    proactive_notification_draft: NotificationDraft | None
    diagnostics: ApprovalDiagnostics


@dataclass(frozen=True, slots=True)
class _FulfillmentCandidate:
    compiled_index: int
    compiled: CompiledCommitment
    active_commitment: ActiveCommitment


class ApprovalService:
    """Approve a legal server candidate and save its first complete response atomically."""

    def __init__(
        self,
        *,
        repository: ApprovalTransactionRepository,
        clock: Clock,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._request_id_factory = request_id_factory or (lambda: f"approve-{uuid4().hex}")

    def approve(
        self,
        request: ApproveResolutionRequest,
        *,
        request_id: str | None = None,
    ) -> ApproveResolutionResponse:
        """Return the schema-backed approval response for a future transport adapter."""

        return self.approve_with_trace(request, request_id=request_id).response

    def approve_with_trace(
        self,
        request: ApproveResolutionRequest,
        *,
        request_id: str | None = None,
    ) -> ApprovalExecution:
        """Run one idempotent approval without trusting a client-side resolution plan."""

        correlation_id = self._request_id(request_id)
        request_body = _normalized_request(request, request_id=correlation_id)
        try:
            result = self._repository.execute(
                case_id=request.case_id,
                operation="approve",
                idempotency_key=request.idempotency_key,
                request_body=request_body,
                mutate=lambda current: self._mutate(
                    current=current,
                    request=request,
                    request_body=request_body,
                    request_id=correlation_id,
                ),
            )
        except IdempotencyConflict as error:
            raise ApprovalConflictError(
                "The idempotency key was already used with a different normalized body.",
                request_id=correlation_id,
            ) from error
        except ApprovalServiceError:
            raise
        except (LedgerConflict, LedgerUnavailable) as error:
            raise ApprovalInfrastructureError(
                "approval transaction could not safely complete",
                request_id=correlation_id,
            ) from error

        response, persisted_request_id = _response_from_transaction(result, correlation_id)
        notification = _notification_from_response(response, request_id=persisted_request_id)
        return ApprovalExecution(
            response=response,
            request_id=persisted_request_id,
            replayed=result.replayed,
            replay_source=result.replay_source,
            status_code=result.response.status_code,
            proactive_notification_draft=notification,
            diagnostics=_diagnostics_for(response),
        )

    def _mutate(
        self,
        *,
        current: LedgerSnapshot | None,
        request: ApproveResolutionRequest,
        request_body: Mapping[str, Any],
        request_id: str,
    ) -> Mutation:
        if current is None or current.accountability_state is None:
            raise ApprovalCandidateInvalid(
                "candidate_type is no longer valid for the current server state",
                request_id=request_id,
            )
        if (
            current.case_id != request.case_id
            or current.accountability_state.case_id != request.case_id
        ):
            raise ApprovalCandidateInvalid(
                "candidate_type is no longer valid for the current server state",
                request_id=request_id,
            )

        approved_at = _trusted_clock_now(self._clock, request_id=request_id)
        _require_clock_after_audit(current.accountability_state, approved_at, request_id=request_id)
        submitted_fields = _submitted_edit_fields(request_body, request_id=request_id)

        if request.candidate_type == _FULFILLMENT_CANDIDATE:
            candidate = _current_fulfillment_candidate(
                current,
                approved_at=approved_at,
                request_id=request_id,
            )
            return _fulfillment_mutation(
                current=current,
                candidate=candidate,
                request_body=request_body,
                approved_at=approved_at,
                submitted_fields=submitted_fields,
                approver_id=request.approver_id,
                request_id=request_id,
            )

        _reject_human_edits_for_non_fulfillment(
            submitted_fields,
            request_id=request_id,
        )
        resolution = _non_fulfillment_resolution(
            current.accountability_state,
            candidate_type=request.candidate_type,
            request_id=request_id,
        )
        state = _state_with_approval_audit(
            current.accountability_state,
            approved_at=approved_at,
            approver_id=request.approver_id,
            submitted_fields=submitted_fields,
            request_id=request_id,
        )
        response = ApproveResolutionResponse(
            accountability_state=state,
            approved_resolution=resolution,
            audit_trail=state.audit_trail,
        )
        return _mutation(current, state=state, response=response, request_id=request_id)

    def _request_id(self, requested: str | None) -> str:
        value = self._request_id_factory() if requested is None else requested
        if not isinstance(value, str) or not value.strip():
            raise ValueError("request_id must be a non-empty string")
        return value


def _normalized_request(
    request: ApproveResolutionRequest,
    *,
    request_id: str,
) -> dict[str, Any]:
    if not isinstance(request, ApproveResolutionRequest):
        raise ApprovalInputError(
            "approval request must use the locked request type",
            request_id=request_id,
        )
    approver_id = getattr(request, "approver_id", None)
    if not isinstance(approver_id, str) or not approver_id.strip():
        raise ApprovalInputError("approver_id is required for approval", request_id=request_id)
    try:
        body = request.to_contract()
    except (ContractValidationError, TypeError, ValueError) as error:
        raise ApprovalInputError(
            "approval request does not match the locked contract",
            request_id=request_id,
        ) from error
    human_edits = body.get("human_edits")
    if not isinstance(human_edits, Mapping):
        raise ApprovalInputError("human_edits must be an object", request_id=request_id)
    forbidden = set(human_edits).difference(_EDITABLE_FIELDS)
    if forbidden or "approved_at" in body or "approved_at" in human_edits:
        raise ApprovalInputError(
            "only executor, next_check_at, and recovery_if_missed may be human edits",
            request_id=request_id,
        )
    return body


def _submitted_edit_fields(
    request_body: Mapping[str, Any],
    *,
    request_id: str,
) -> tuple[str, ...]:
    human_edits = request_body.get("human_edits")
    if not isinstance(human_edits, Mapping):
        raise ApprovalInputError("human_edits must be an object", request_id=request_id)
    return tuple(field for field in _EDITABLE_FIELDS if field in human_edits)


def _trusted_clock_now(clock: Clock, *, request_id: str) -> datetime:
    try:
        approved_at = clock.now()
        return require_aware_datetime(approved_at)
    except (AttributeError, TypeError, ValueError) as error:
        raise ApprovalInfrastructureError(
            "approval requires a trusted timezone-aware server clock",
            request_id=request_id,
        ) from error


def _require_clock_after_audit(
    state: AccountabilityState,
    approved_at: datetime,
    *,
    request_id: str,
) -> None:
    prior = [_parse_timestamp(entry.at, request_id=request_id) for entry in state.audit_trail]
    if prior and approved_at <= max(prior):
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        )


def _current_fulfillment_candidate(
    current: LedgerSnapshot,
    *,
    approved_at: datetime,
    request_id: str,
) -> _FulfillmentCandidate:
    state = current.accountability_state
    assert state is not None
    if (
        state.evidence_status != "VALID"
        or state.consumer_input_required
        or state.accountable_side != "BRAND"
        or state.case_status not in {"READY_FOR_BRAND", "IN_FULFILLMENT"}
        or state.current_scope.issue_type == "ADVERSE_REACTION"
        or state.experience_risk == "HIGH"
        or (state.open_obligation is not None and state.open_obligation.status == "COMPLETED")
        or (
            state.service_progress_receipt is not None
            and state.service_progress_receipt.status == "COMPLETED"
        )
    ):
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        )

    candidate = _select_active_replacement(current.compiled_commitments, state)
    if candidate is None:
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        )
    deadline = _parse_timestamp(candidate.compiled.deadline, request_id=request_id)
    if approved_at >= deadline:
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        )
    return candidate


def _select_active_replacement(
    compiled_commitments: CompiledCommitments,
    state: AccountabilityState,
) -> _FulfillmentCandidate | None:
    candidates: list[_FulfillmentCandidate] = []
    for index, compiled in enumerate(compiled_commitments.commitments):
        if (
            compiled.commitment_class != "STANDARD_APPROVED"
            or compiled.activation_status != "ACTIVE"
            or compiled.deadline is None
            or compiled.next_check_at is None
        ):
            continue
        matching = [
            active
            for active in state.active_commitments
            if active.raw_text == compiled.source_promise_text
            and active.deadline == compiled.deadline
            and active.status == "ACTIVE"
            and active.source_ids
        ]
        for active in matching:
            candidates.append(_FulfillmentCandidate(index, compiled, active))
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.compiled.deadline or "",
            item.compiled.source_promise_text,
            tuple(sorted(item.active_commitment.source_ids)),
            item.compiled_index,
        ),
    )


def _fulfillment_mutation(
    *,
    current: LedgerSnapshot,
    candidate: _FulfillmentCandidate,
    request_body: Mapping[str, Any],
    approved_at: datetime,
    submitted_fields: tuple[str, ...],
    approver_id: str,
    request_id: str,
) -> Mutation:
    state = current.accountability_state
    assert state is not None
    human_edits = request_body["human_edits"]
    assert isinstance(human_edits, Mapping)

    deadline = _parse_timestamp(candidate.compiled.deadline, request_id=request_id)
    next_check_at = _next_check_at(
        human_edits.get("next_check_at", candidate.compiled.next_check_at),
        deadline=deadline,
        approved_at=approved_at,
        request_id=request_id,
    )
    executor = _executor_for(state, human_edits.get("executor"), request_id=request_id)
    recovery = _recovery_for(state, human_edits.get("recovery_if_missed"), request_id=request_id)

    existing = state.open_obligation
    obligation_status = "ON_TRACK" if existing is None else existing.status
    milestone = "AWAITING_CARRIER_PICKUP" if existing is None else existing.milestone
    receipt_id = _receipt_id_for(state)
    projection = project_progress(
        ProgressLedger(
            receipt_id=receipt_id,
            status=(
                ProgressStatus.AT_RISK
                if obligation_status == "AT_RISK"
                else ProgressStatus.ACTIVE
            ),
            received_evidence=_received_evidence_for(state),
            brand_action=(
                state.service_progress_receipt.brand_action
                if state.service_progress_receipt is not None
                else _DEFAULT_BRAND_ACTION
            ),
            latest_update_at=approved_at,
            next_check_at=next_check_at,
            recovery_if_missed=recovery,
        )
    )
    receipt = ServiceProgressReceipt.model_validate(projection.receipt.consumer_view())
    next_check_text = receipt.next_update_by
    assert next_check_text is not None
    obligation = OpenObligation(
        obligation_type="REPLACEMENT_FULFILLMENT",
        status=obligation_status,
        accountable_side="BRAND",
        executor=executor,
        deadline=candidate.compiled.deadline,
        next_check_at=next_check_text,
        milestone=milestone,
        resolution_condition="REPLACEMENT_DELIVERED",
    )
    responsibility = CompiledServiceResponsibility(
        source_promise_text=candidate.compiled.source_promise_text,
        commitment_class="STANDARD_APPROVED",
        activation_status="ACTIVE",
        deadline=candidate.compiled.deadline,
        next_check_at=next_check_text,
        recovery_if_missed=recovery,
    )
    resolution = ResolutionPath(
        candidate_type=_FULFILLMENT_CANDIDATE,
        evidence_basis=sorted(candidate.active_commitment.source_ids),
        policy_basis="server-validated active replacement responsibility",
        consumer_reply_draft=render_consumer_reply(_FULFILLMENT_CANDIDATE),
        task_prefill=TaskPrefill(
            task_type="WAREHOUSE_FOLLOW_UP",
            existing_ticket_id=_existing_ticket_id(state),
            sku_id=state.current_scope.sku_id,
            summary=(
                "Follow up on the existing fulfillment without creating refund or compensation."
            ),
        ),
        accountable_side="BRAND",
        executor=executor,
        requires_human_approval=True,
        creates_obligation=True,
        compiled_service_responsibility=responsibility,
    )
    updated = _state_with_approval_audit(
        state,
        approved_at=approved_at,
        approver_id=approver_id,
        submitted_fields=submitted_fields,
        request_id=request_id,
        open_obligation=obligation,
        receipt=receipt,
        case_status="AT_RISK" if obligation_status == "AT_RISK" else "IN_FULFILLMENT",
        experience_risk="HIGH" if obligation_status == "AT_RISK" else "MEDIUM",
    )
    commitments = list(current.compiled_commitments.commitments)
    commitments[candidate.compiled_index] = replace(
        candidate.compiled,
        next_check_at=next_check_text,
    )
    updated_compiled = CompiledCommitments(
        commitments=tuple(commitments),
        compiled_from_evidence=current.compiled_commitments.compiled_from_evidence,
    )
    snapshot = replace(
        current,
        accountability_state=updated,
        compiled_commitments=updated_compiled,
    )
    response = ApproveResolutionResponse(
        accountability_state=updated,
        approved_resolution=resolution,
        audit_trail=updated.audit_trail,
    )
    return _mutation(snapshot, state=updated, response=response, request_id=request_id)


def _next_check_at(
    value: object,
    *,
    deadline: datetime,
    approved_at: datetime,
    request_id: str,
) -> datetime:
    if not isinstance(value, str):
        raise ApprovalInputError(
            "next_check_at must be an RFC 3339 timestamp",
            request_id=request_id,
        )
    parsed = _parse_timestamp(value, request_id=request_id)
    if parsed <= deadline or parsed <= approved_at:
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        )
    return parsed


def _executor_for(
    state: AccountabilityState,
    requested: object,
    *,
    request_id: str,
) -> Literal["BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"]:
    executor = state.open_obligation.executor if state.open_obligation is not None else "WAREHOUSE"
    if requested is not None:
        if requested not in {"BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"}:
            raise ApprovalInputError(
                "executor is outside the approved edit scope",
                request_id=request_id,
            )
        executor = requested
    return executor


def _recovery_for(state: AccountabilityState, requested: object, *, request_id: str) -> str:
    recovery = (
        state.service_progress_receipt.recovery_if_missed
        if state.service_progress_receipt is not None
        else _DEFAULT_RECOVERY
    )
    if requested is not None:
        if not isinstance(requested, str) or not requested.strip():
            raise ApprovalInputError(
                "recovery_if_missed is outside the approved edit scope",
                request_id=request_id,
            )
        recovery = requested
    return recovery


def _receipt_id_for(state: AccountabilityState) -> str:
    if state.service_progress_receipt is not None:
        return state.service_progress_receipt.receipt_id
    return f"{state.case_id}:replacement"


def _received_evidence_for(state: AccountabilityState) -> tuple[str, ...]:
    if state.service_progress_receipt is not None:
        return tuple(state.service_progress_receipt.received_evidence)
    return tuple(
        sorted(
            {
                source_id
                for fact in state.experience_gap_diagnosis.traceable_service_facts
                if fact.fact_type == "EVIDENCE_SUBMITTED"
                for source_id in fact.source_ids
            }
        )
    )


def _existing_ticket_id(state: AccountabilityState) -> str | None:
    ticket_ids = sorted(
        {
            source_id
            for fact in state.experience_gap_diagnosis.traceable_service_facts
            if fact.fact_type == "TICKET_CREATED"
            for source_id in fact.source_ids
        }
    )
    return ticket_ids[0] if ticket_ids else None


def _reject_human_edits_for_non_fulfillment(
    submitted_fields: tuple[str, ...],
    *,
    request_id: str,
) -> None:
    if submitted_fields:
        raise ApprovalInputError(
            "human edits are only legal for a server-validated fulfillment candidate",
            request_id=request_id,
        )


def _non_fulfillment_resolution(
    state: AccountabilityState,
    *,
    candidate_type: CandidateType,
    request_id: str,
) -> ResolutionPath:
    if candidate_type == "ASK_CURRENT_SCOPE_EVIDENCE":
        if (
            state.evidence_status != "MISMATCHED"
            or not state.consumer_input_required
            or state.accountable_side != "CONSUMER"
        ):
            raise ApprovalCandidateInvalid(
                "candidate_type is no longer valid for the current server state",
                request_id=request_id,
            )
        return ResolutionPath(
            candidate_type=candidate_type,
            evidence_basis=["server:evidence_status:MISMATCHED"],
            policy_basis="server-validated current-scope evidence gap",
            consumer_reply_draft="Please provide only the missing evidence for the current issue.",
            task_prefill=TaskPrefill(
                task_type="REQUEST_EVIDENCE",
                existing_ticket_id=None,
                sku_id=state.current_scope.sku_id,
                summary="Request only the missing material for the current issue scope.",
            ),
            accountable_side="CONSUMER",
            executor="CONSUMER",
            requires_human_approval=True,
            creates_obligation=False,
            compiled_service_responsibility=None,
        )
    if candidate_type == "HUMAN_EVIDENCE_REVIEW":
        if state.evidence_status != "NEED_HUMAN_REVIEW" and state.experience_risk != "HIGH":
            raise ApprovalCandidateInvalid(
                "candidate_type is no longer valid for the current server state",
                request_id=request_id,
            )
        return ResolutionPath(
            candidate_type=candidate_type,
            evidence_basis=[f"server:evidence_status:{state.evidence_status}"],
            policy_basis="server-validated human evidence review",
            consumer_reply_draft=render_consumer_reply(candidate_type),
            task_prefill=TaskPrefill(
                task_type="HUMAN_EVIDENCE_REVIEW",
                existing_ticket_id=_existing_ticket_id(state),
                sku_id=state.current_scope.sku_id,
                summary=(
                    "Review the current server evidence without creating a financial obligation."
                ),
            ),
            accountable_side=state.accountable_side,
            executor="HUMAN_REVIEW_QUEUE",
            requires_human_approval=True,
            creates_obligation=False,
            compiled_service_responsibility=None,
        )
    raise ApprovalCandidateInvalid(
        "candidate_type is no longer valid for the current server state",
        request_id=request_id,
    )


def _state_with_approval_audit(
    state: AccountabilityState,
    *,
    approved_at: datetime,
    approver_id: str,
    submitted_fields: tuple[str, ...],
    request_id: str,
    open_obligation: OpenObligation | None = None,
    receipt: ServiceProgressReceipt | None = None,
    case_status: str | None = None,
    experience_risk: str | None = None,
) -> AccountabilityState:
    audit = AuditEntry(
        at=_format_projection_timestamp(approved_at),
        actor=approver_id,
        action="RESOLUTION_APPROVED",
        changed_fields=list(submitted_fields),
        request_id=request_id,
    )
    updates: dict[str, object] = {"audit_trail": [*state.audit_trail, audit]}
    if open_obligation is not None:
        updates["open_obligation"] = open_obligation
    if receipt is not None:
        updates["service_progress_receipt"] = receipt
    if case_status is not None:
        updates["case_status"] = case_status
    if experience_risk is not None:
        updates["experience_risk"] = experience_risk
    return state.model_copy(update=updates)


def _mutation(
    snapshot: LedgerSnapshot,
    *,
    state: AccountabilityState,
    response: ApproveResolutionResponse,
    request_id: str,
) -> Mutation:
    if snapshot.accountability_state != state:
        snapshot = replace(snapshot, accountability_state=state)
    response_data = response.to_contract()
    envelope: dict[str, Any] = {"data": response_data, "error": None, "request_id": request_id}
    try:
        validate_contract_payload("api-envelope.schema.json", envelope)
    except ContractValidationError as error:
        raise ApprovalInfrastructureError(
            "approval response did not satisfy the frozen envelope contract",
            request_id=request_id,
        ) from error
    return Mutation(
        snapshot=snapshot,
        response=StoredResponse(envelope, status_code=200, headers={"X-Request-Id": request_id}),
    )


def _response_from_transaction(
    result: TransactionResult,
    request_id: str,
) -> tuple[ApproveResolutionResponse, str]:
    body = result.response.body
    if not isinstance(body, Mapping) or body.get("error") is not None:
        raise ApprovalInfrastructureError(
            "stored approval response is not a successful envelope",
            request_id=request_id,
        )
    data = body.get("data")
    persisted_request_id = body.get("request_id")
    if (
        not isinstance(data, Mapping)
        or not isinstance(persisted_request_id, str)
        or not persisted_request_id
    ):
        raise ApprovalInfrastructureError(
            "stored approval response is incomplete",
            request_id=request_id,
        )
    try:
        return ApproveResolutionResponse.from_contract(dict(data)), persisted_request_id
    except (ContractValidationError, TypeError, ValueError) as error:
        raise ApprovalInfrastructureError(
            "stored approval response does not match the frozen contract",
            request_id=request_id,
        ) from error


def _notification_from_response(
    response: ApproveResolutionResponse,
    *,
    request_id: str,
) -> NotificationDraft | None:
    if not response.approved_resolution.creates_obligation:
        return None
    obligation = response.accountability_state.open_obligation
    receipt = response.accountability_state.service_progress_receipt
    if obligation is None or receipt is None or receipt.next_update_by != obligation.next_check_at:
        raise ApprovalInfrastructureError(
            "stored approval projections are inconsistent",
            request_id=request_id,
        )
    try:
        projection = project_progress(
            ProgressLedger(
                receipt_id=receipt.receipt_id,
                status=ProgressStatus(receipt.status),
                received_evidence=tuple(receipt.received_evidence),
                brand_action=receipt.brand_action,
                latest_update_at=_parse_timestamp(receipt.latest_update_at, request_id=request_id),
                next_check_at=_parse_timestamp(obligation.next_check_at, request_id=request_id),
                recovery_if_missed=receipt.recovery_if_missed,
            )
        )
    except (TypeError, ValueError) as error:
        raise ApprovalInfrastructureError(
            "stored approval notification projection is invalid",
            request_id=request_id,
        ) from error
    if projection.receipt.consumer_view()["next_update_by"] != receipt.next_update_by:
        raise ApprovalInfrastructureError(
            "stored approval receipt lost its projected update instant",
            request_id=request_id,
        )
    return projection.proactive_notification_draft


def _diagnostics_for(response: ApproveResolutionResponse) -> ApprovalDiagnostics:
    audit = response.audit_trail[-1]
    derived = ["approved_resolution", "audit_trail"]
    values: list[tuple[str, str]] = []
    if response.approved_resolution.creates_obligation:
        obligation = response.accountability_state.open_obligation
        receipt = response.accountability_state.service_progress_receipt
        responsibility = response.approved_resolution.compiled_service_responsibility
        assert obligation is not None and receipt is not None and responsibility is not None
        derived.extend(
            (
                "open_obligation",
                "compiled_service_responsibility",
                "service_progress_receipt",
                "proactive_notification_draft",
            )
        )
        values.extend(
            (
                ("open_obligation.executor", obligation.executor),
                ("open_obligation.next_check_at", obligation.next_check_at),
                ("compiled_service_responsibility.next_check_at", responsibility.next_check_at),
                ("service_progress_receipt.next_update_by", receipt.next_update_by),
                ("notification_draft.commits_next_update_at", obligation.next_check_at),
            )
        )
    return ApprovalDiagnostics(
        submitted_fields=tuple(audit.changed_fields),
        derived_projection_fields=tuple(derived),
        effective_projection_values=tuple(values),
    )


def _parse_timestamp(value: str | None, *, request_id: str) -> datetime:
    if not isinstance(value, str):
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        )
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00" if value.endswith("Z") else value)
        return require_aware_datetime(parsed)
    except (TypeError, ValueError) as error:
        raise ApprovalCandidateInvalid(
            "candidate_type is no longer valid for the current server state",
            request_id=request_id,
        ) from error


def _format_projection_timestamp(value: datetime) -> str:
    return require_aware_datetime(value).isoformat(timespec="seconds")
