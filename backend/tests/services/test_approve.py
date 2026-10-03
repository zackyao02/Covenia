from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from covenia_b.domain.types import (
    AccountabilityState,
    ApproveResolutionRequest,
    CompiledCommitment,
    CompiledCommitments,
    LedgerSnapshot,
)
from covenia_b.domain.validation import ContractValidationError
from covenia_b.ports.clock import DemoClock
from covenia_b.services.analyze import _persisted_ledger_from_snapshot
from covenia_b.services.approve import (
    ApprovalCandidateInvalid,
    ApprovalConflictError,
    ApprovalInfrastructureError,
    ApprovalInputError,
    ApprovalService,
)
from covenia_b.storage import SQLiteLedgerRepository

CASE_ID = "CASE-APPROVE-UNIT-001"
ANALYZED_AT = "2030-01-01T10:00:00+00:00"
APPROVED_AT = datetime(2030, 1, 1, 10, 2, tzinfo=UTC)
DEADLINE = "2030-01-01T12:00:00+00:00"
NEXT_CHECK = "2030-01-01T12:15:00+00:00"


def _state(
    *,
    evidence_status: str = "VALID",
    accountable_side: str = "BRAND",
    consumer_input_required: bool = False,
    case_status: str = "READY_FOR_BRAND",
    experience_risk: str = "MEDIUM",
) -> AccountabilityState:
    return AccountabilityState.model_validate(
        {
            "case_id": CASE_ID,
            "case_status": case_status,
            "consumer_input_required": consumer_input_required,
            "accountable_side": accountable_side,
            "evidence_status": evidence_status,
            "current_scope": {
                "order_id": "ORDER-UNIT-001",
                "fulfillment_item_id": "ITEM-UNIT-001",
                "sku_id": "SKU-UNIT-001",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "active_commitments": [
                {
                    "promise_type": "REPLACEMENT_DISPATCH",
                    "raw_text": "A server-validated replacement commitment exists.",
                    "status": "ACTIVE",
                    "deadline": DEADLINE,
                    "source_ids": ["SOURCE-UNIT-001"],
                }
            ],
            "prohibited_actions": [
                "ASK_SAME_EVIDENCE",
                "MAKE_UNTRACKABLE_PROMISE",
                "CLOSE_BEFORE_RESOLUTION",
            ],
            "experience_gap_diagnosis": {
                "consumer_expression": "A reliable update is needed.",
                "traceable_service_facts": [
                    {
                        "fact_type": "EVIDENCE_SUBMITTED",
                        "statement": "Server facts include current evidence.",
                        "source_ids": ["EVIDENCE-UNIT-001"],
                    },
                    {
                        "fact_type": "TICKET_CREATED",
                        "statement": "An existing fulfillment ticket is present.",
                        "source_ids": ["TICKET-UNIT-001"],
                    },
                ],
                "deterioration_cause": "Fulfillment needs ownership.",
                "latent_need": "A reliable next update.",
                "responsibility_judgment": {
                    "consumer_input_complete": not consumer_input_required,
                    "accountable_side": accountable_side,
                },
                "action_impacts": ["START_PROACTIVE_UPDATE"],
                "reply_strategy": "The brand will provide an update.",
            },
            "open_obligation": None,
            "service_progress_receipt": None,
            "experience_risk": experience_risk,
            "audit_trail": [
                {
                    "at": ANALYZED_AT,
                    "actor": "ANALYZE_SERVICE",
                    "action": "ANALYZED",
                    "changed_fields": ["accountability_state"],
                    "request_id": "analyze-unit-001",
                }
            ],
        }
    )


def _snapshot(state: AccountabilityState | None = None) -> LedgerSnapshot:
    return LedgerSnapshot(
        case_id=CASE_ID,
        version=0,
        event_high_watermark=None,
        accountability_state=state or _state(),
        compiled_commitments=CompiledCommitments(
            commitments=(
                CompiledCommitment(
                    source_promise_text="A server-validated replacement commitment exists.",
                    commitment_class="STANDARD_APPROVED",
                    activation_status="ACTIVE",
                    deadline=DEADLINE,
                    next_check_at=NEXT_CHECK,
                ),
            ),
            compiled_from_evidence=True,
        ),
    )


def _repository(tmp_path, *, state: AccountabilityState | None = None) -> SQLiteLedgerRepository:
    repository = SQLiteLedgerRepository(tmp_path / "approve-ledger.db")
    repository.save(_snapshot(state), expected_version=None)
    return repository


def _service(repository: SQLiteLedgerRepository) -> ApprovalService:
    return ApprovalService(
        repository=repository,
        clock=DemoClock(APPROVED_AT),
        request_id_factory=lambda: "generated-approve-request-id",
    )


def _request(
    *,
    key: str = "approve-unit-key-001",
    edits: dict[str, object] | None = None,
    candidate_type: str = "CHECK_REPLACEMENT_FULFILLMENT",
) -> ApproveResolutionRequest:
    return ApproveResolutionRequest.from_contract(
        {
            "case_id": CASE_ID,
            "candidate_type": candidate_type,
            "approver_id": "AGENT-UNIT-001",
            "idempotency_key": key,
            "human_edits": edits or {},
        }
    )


def test_approval_uses_server_clock_and_synchronizes_all_open_projections(tmp_path):
    repository = _repository(tmp_path)
    execution = _service(repository).approve_with_trace(
        _request(edits={"executor": "LOGISTICS_PROVIDER", "next_check_at": NEXT_CHECK}),
        request_id="approve-request-001",
    )

    response = execution.response
    state = response.accountability_state
    obligation = state.open_obligation
    receipt = state.service_progress_receipt
    responsibility = response.approved_resolution.compiled_service_responsibility
    assert obligation is not None and receipt is not None and responsibility is not None
    assert state.accountable_side == "BRAND"
    assert obligation.executor == "LOGISTICS_PROVIDER"
    assert obligation.next_check_at == receipt.next_update_by == responsibility.next_check_at
    assert response.audit_trail[-1].at == receipt.latest_update_at == "2030-01-01T10:02:00+00:00"
    assert response.audit_trail[-1].actor == "AGENT-UNIT-001"
    assert response.audit_trail[-1].changed_fields == ["executor", "next_check_at"]
    assert execution.proactive_notification_draft is not None
    assert execution.proactive_notification_draft.requires_human_approval is True
    assert execution.proactive_notification_draft.is_sent is False
    assert execution.proactive_notification_draft.commits_next_update_at.isoformat() == NEXT_CHECK
    assert execution.diagnostics.submitted_fields == ("executor", "next_check_at")
    assert execution.diagnostics.derived_projection_fields == (
        "approved_resolution",
        "audit_trail",
        "open_obligation",
        "compiled_service_responsibility",
        "service_progress_receipt",
        "proactive_notification_draft",
    )
    assert execution.diagnostics.effective_projection_values == (
        ("open_obligation.executor", "LOGISTICS_PROVIDER"),
        ("open_obligation.next_check_at", NEXT_CHECK),
        ("compiled_service_responsibility.next_check_at", NEXT_CHECK),
        ("service_progress_receipt.next_update_by", NEXT_CHECK),
        ("notification_draft.commits_next_update_at", NEXT_CHECK),
    )
    assert response.to_contract()["approved_resolution"]["accountable_side"] == "BRAND"

    saved = repository.load(CASE_ID)
    assert saved is not None
    assert saved.compiled_commitments.commitments[0].next_check_at == NEXT_CHECK
    persisted = _persisted_ledger_from_snapshot(saved)
    assert persisted is not None and persisted.approved_resolution is not None
    assert persisted.approved_resolution.executor == "LOGISTICS_PROVIDER"
    assert persisted.approved_resolution.next_check_at.isoformat() == NEXT_CHECK


def test_same_key_replays_first_response_and_request_id_without_duplicate_audit(tmp_path):
    repository = _repository(tmp_path)
    service = _service(repository)
    request = _request(edits={"executor": "WAREHOUSE"})

    first = service.approve_with_trace(request, request_id="first-approve-request")
    before = repository.load(CASE_ID)
    replay = service.approve_with_trace(request, request_id="second-approve-request")

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.request_id == "first-approve-request"
    assert replay.response.to_contract() == first.response.to_contract()
    assert repository.load(CASE_ID) == before
    assert len(replay.response.audit_trail) == 2


def test_same_key_with_different_normalized_body_conflicts_without_state_change(tmp_path):
    repository = _repository(tmp_path)
    service = _service(repository)
    service.approve(_request(edits={"executor": "WAREHOUSE"}), request_id="first-request")
    before = repository.load(CASE_ID)

    with pytest.raises(ApprovalConflictError) as error:
        service.approve(
            _request(edits={"executor": "LOGISTICS_PROVIDER"}),
            request_id="conflicting-request",
        )

    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert repository.load(CASE_ID) == before


def test_permitted_recovery_edit_is_synchronized_to_the_receipt_and_responsibility(tmp_path):
    repository = _repository(tmp_path)
    execution = _service(repository).approve_with_trace(
        _request(edits={"recovery_if_missed": "A supervisor will review the missed update."}),
        request_id="recovery-edit-request",
    )

    receipt = execution.response.accountability_state.service_progress_receipt
    responsibility = execution.response.approved_resolution.compiled_service_responsibility
    assert receipt is not None and responsibility is not None
    assert receipt.recovery_if_missed == "A supervisor will review the missed update."
    assert responsibility.recovery_if_missed == receipt.recovery_if_missed
    assert execution.response.audit_trail[-1].changed_fields == ["recovery_if_missed"]


def test_final_response_write_failure_rolls_back_approval_snapshot_and_audit(tmp_path):
    repository = _repository(tmp_path)
    service = _service(repository)
    before = repository.load(CASE_ID)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_approval BEFORE INSERT ON idempotent_requests "
            "BEGIN SELECT RAISE(ABORT, 'injected approval response failure'); END"
        )

    with pytest.raises(ApprovalInfrastructureError):
        service.approve(_request(), request_id="atomic-failure-request")

    assert repository.load(CASE_ID) == before


def test_missing_or_blank_approver_is_rejected_before_a_transaction(tmp_path):
    repository = _repository(tmp_path)
    service = _service(repository)
    valid = _request()
    before = repository.load(CASE_ID)
    blank = valid.model_construct(
        case_id=valid.case_id,
        candidate_type=valid.candidate_type,
        approver_id=" ",
        idempotency_key=valid.idempotency_key,
        human_edits=valid.human_edits,
    )

    with pytest.raises(ApprovalInputError, match="approver_id is required") as error:
        service.approve(blank, request_id="blank-approver-request")

    assert error.value.code == "VALIDATION_ERROR"
    assert repository.load(CASE_ID) == before


def test_current_server_state_rejects_stale_or_high_risk_fulfillment_candidate(tmp_path):
    state = _state(case_status="ACTION_REVIEW", experience_risk="HIGH")
    repository = _repository(tmp_path, state=state)
    service = _service(repository)
    before = repository.load(CASE_ID)

    with pytest.raises(ApprovalCandidateInvalid) as error:
        service.approve(_request(), request_id="stale-request")

    assert error.value.code == "VALIDATION_ERROR"
    assert repository.load(CASE_ID) == before


def test_current_server_state_revalidates_non_fulfillment_candidates_and_rejects_edits(tmp_path):
    state = _state(
        evidence_status="MISMATCHED",
        accountable_side="CONSUMER",
        consumer_input_required=True,
        case_status="WAITING_FOR_CONSUMER",
        experience_risk="LOW",
    )
    repository = _repository(tmp_path, state=state)
    service = _service(repository)

    with pytest.raises(ApprovalCandidateInvalid):
        service.approve(_request(), request_id="wrong-client-plan")
    with pytest.raises(ApprovalInputError, match="only legal for a server-validated fulfillment"):
        service.approve(
            _request(
                key="approve-evidence-key-002",
                candidate_type="ASK_CURRENT_SCOPE_EVIDENCE",
                edits={"executor": "WAREHOUSE"},
            ),
            request_id="evidence-edit-request",
        )

    execution = service.approve_with_trace(
        _request(
            key="approve-evidence-key-003",
            candidate_type="ASK_CURRENT_SCOPE_EVIDENCE",
        ),
        request_id="evidence-approval-request",
    )
    assert execution.response.approved_resolution.creates_obligation is False
    assert execution.response.accountability_state.open_obligation is None
    assert execution.proactive_notification_draft is None
    assert execution.response.audit_trail[-1].changed_fields == []


def test_human_review_candidate_is_revalidated_from_server_review_state(tmp_path):
    state = _state(
        evidence_status="NEED_HUMAN_REVIEW",
        accountable_side="UNKNOWN",
        consumer_input_required=False,
        case_status="ACTION_REVIEW",
        experience_risk="HIGH",
    )
    repository = _repository(tmp_path, state=state)
    execution = _service(repository).approve_with_trace(
        _request(
            key="approve-human-review-key-001",
            candidate_type="HUMAN_EVIDENCE_REVIEW",
        ),
        request_id="human-review-request",
    )

    assert execution.response.approved_resolution.candidate_type == "HUMAN_EVIDENCE_REVIEW"
    assert execution.response.approved_resolution.creates_obligation is False
    assert execution.response.accountability_state.open_obligation is None
    assert execution.proactive_notification_draft is None
    assert execution.response.audit_trail[-1].actor == "AGENT-UNIT-001"


def test_contract_rejects_client_authority_fields_including_approved_at_and_refund(tmp_path):
    del tmp_path
    request = {
        "case_id": CASE_ID,
        "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT-UNIT-001",
        "idempotency_key": "approve-forbidden-key-001",
        "approved_at": "2030-01-01T09:00:00+00:00",
        "human_edits": {
            "refund": "FULL",
            "accountable_side": "CONSUMER",
            "case_status": "RESOLVED",
        },
    }

    with pytest.raises((ContractValidationError, ValidationError)):
        ApproveResolutionRequest.from_contract(request)


def test_next_check_must_remain_after_server_deadline_and_approval_time(tmp_path):
    repository = _repository(tmp_path)
    service = _service(repository)
    before = repository.load(CASE_ID)

    with pytest.raises(ApprovalCandidateInvalid):
        service.approve(
            _request(edits={"next_check_at": "2030-01-01T11:59:59+00:00"}),
            request_id="early-next-check-request",
        )

    assert repository.load(CASE_ID) == before
