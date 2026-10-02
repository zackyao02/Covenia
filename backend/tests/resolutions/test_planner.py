from __future__ import annotations

from datetime import datetime

import pytest

from covenia_b.commitments.models import (
    ActivationStatus,
    CommitmentClass,
    CommitmentCompilation,
    CompilationReason,
    CompiledPromise,
    PromiseAction,
    PromiseIssuanceStatus,
    ServiceDeliveryStatus,
)
from covenia_b.domain.types import (
    AccountabilityState,
    CaseInput,
    PreparedAction,
    Scope,
    ServiceTicket,
)
from covenia_b.evidence.aggregation import EvidenceAggregation
from covenia_b.resolutions.planner import ResolutionPlanningError, plan_resolution
from covenia_b.resolutions.reply_templates import ReplyTemplateError, render_consumer_reply
from covenia_b.rules.engine import ProhibitedActionError, evaluate_decision

_DEADLINE = datetime.fromisoformat("2026-05-07T10:27:37+08:00")
_NEXT_CHECK = datetime.fromisoformat("2026-05-07T10:30:00+08:00")
_COMPILED_AT = datetime.fromisoformat("2026-05-07T09:40:00+08:00")


def _ticket(ticket_id: str, *, completed: bool = False) -> ServiceTicket:
    return ServiceTicket(
        ticket_id=ticket_id,
        ticket_type="REPLACEMENT",
        status="OPEN" if not completed else "DONE",
        assignee_id="internal-assignee-16",
        executor_name="内部员工王小明",
        replacement_logistics_number="logistics-16",
        created_at="2026-05-05T10:27:37+08:00",
        completed_at="2026-05-08T10:27:37+08:00" if completed else None,
        source_sheet="trusted-ticket-sheet",
    )


def _case(*, tickets: tuple[ServiceTicket, ...] = ()) -> CaseInput:
    return CaseInput.model_validate(
        {
            "case_id": "case-16",
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-16",
                "augmentation_notes": [],
            },
            "evaluation_time": "2026-05-07T09:40:00+08:00",
            "conversation": [
                {
                    "message_id": "agent-promise-16",
                    "timestamp": "2026-05-05T10:27:37+08:00",
                    "speaker": "AGENT",
                    "text": "换货单已创建，48小时内发出。",
                    "source_kind": "COMPETITION_MOCK",
                },
                {
                    "message_id": "consumer-16",
                    "timestamp": "2026-05-07T09:30:00+08:00",
                    "speaker": "CONSUMER",
                    "text": "请帮我核对进度。",
                    "source_kind": "COMPETITION_MOCK",
                },
            ],
            "order": {
                "order_id": "order-16",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "item-16",
                        "sku_id": "sku-16",
                        "product_name": "mock-product",
                        "item_role": "PRIMARY",
                    }
                ],
                "original_logistics_number": "original-logistics-16",
            },
            "service_tickets": list(tickets),
            "evidence_images": [
                {
                    "evidence_id": "image-16",
                    "file_name": "synthetic.png",
                    "submitted_at": "2026-05-07T09:20:00+08:00",
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": "consumer-16",
                }
            ],
            "current_issue": {
                "fulfillment_item_id": "item-16",
                "sku_id": "sku-16",
                "issue_type": "PACKAGE_DAMAGE",
                "affected_component": "PUMP",
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )


def _state(
    case: CaseInput,
    *,
    evidence_status: str = "VALID",
    prohibited_actions: tuple[str, ...] = (),
    include_progress_receipt: bool = False,
) -> AccountabilityState:
    receipt = (
        {
            "receipt_id": "receipt-16",
            "status": "ACTIVE",
            "received_evidence": ["image-16"],
            "brand_action": "已记录换货进度查询。",
            "latest_update_at": "2026-05-07T09:30:00+08:00",
            "next_update_by": "2026-05-07T10:30:00+08:00",
            "consumer_action_required": False,
            "recovery_if_missed": "品牌将主动催办并通知新的处理时间",
        }
        if include_progress_receipt
        else None
    )
    obligation = (
        {
            "obligation_type": "REPLACEMENT_FULFILLMENT",
            "status": "ON_TRACK",
            "accountable_side": "BRAND",
            "executor": "BRAND",
            "deadline": "2026-05-07T10:27:37+08:00",
            "next_check_at": "2026-05-07T10:30:00+08:00",
            "milestone": "AWAITING_CARRIER_PICKUP",
            "resolution_condition": "REPLACEMENT_DELIVERED",
        }
        if include_progress_receipt
        else None
    )
    return AccountabilityState.model_validate(
        {
            "case_id": case.case_id,
            "case_status": "IN_FULFILLMENT" if include_progress_receipt else "READY_FOR_BRAND",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": evidence_status,
            "current_scope": {
                "order_id": case.order.order_id,
                "fulfillment_item_id": case.current_issue.fulfillment_item_id,
                "sku_id": case.current_issue.sku_id,
                "issue_type": case.current_issue.issue_type,
            },
            "active_commitments": [
                {
                    "promise_type": "REPLACEMENT_DISPATCH",
                    "raw_text": "换货单已创建，48小时内发出。",
                    "status": "ACTIVE",
                    "deadline": "2026-05-07T10:27:37+08:00",
                    "source_ids": ["agent-promise-16"],
                }
            ],
            "prohibited_actions": list(prohibited_actions),
            "experience_gap_diagnosis": {
                "consumer_expression": "请核对服务进度。",
                "traceable_service_facts": [
                    {
                        "fact_type": "TICKET_CREATED",
                        "statement": "系统已存在换货工单。",
                        "source_ids": ["ticket-source-16"],
                    }
                ],
                "deterioration_cause": "等待既有服务进度。",
                "latent_need": "可追溯的处理更新。",
                "responsibility_judgment": {
                    "consumer_input_complete": True,
                    "accountable_side": "BRAND",
                },
                "action_impacts": ["CHECK_EXISTING_FULFILLMENT"],
                "reply_strategy": "查询既有工单。",
            },
            "open_obligation": obligation,
            "service_progress_receipt": receipt,
            "experience_risk": "HIGH",
            "audit_trail": [],
        }
    )


def _action(
    state: AccountabilityState,
    *,
    action_type: str = "ASK_EVIDENCE",
    requested_scope: Scope | None = None,
) -> PreparedAction:
    if action_type == "ASK_EVIDENCE" and requested_scope is None:
        requested_scope = state.current_scope
    return PreparedAction.model_validate(
        {
            "action_id": "prepared-action-16",
            "action_type": action_type,
            "requested_scope": (
                requested_scope.model_dump() if requested_scope is not None else None
            ),
            "requires_human_approval": False,
        }
    )


def _compilation(*, supporting_ticket_ids: tuple[str, ...] = ()) -> CommitmentCompilation:
    promise = CompiledPromise(
        source_message_id="agent-promise-16",
        raw_text="换货单已创建，48小时内发出。",
        action=PromiseAction.REPLACEMENT_DISPATCH,
        commitment_class=CommitmentClass.STANDARD_APPROVED,
        activation_status=ActivationStatus.ACTIVE,
        deadline=_DEADLINE,
        next_check_at=_NEXT_CHECK,
        promise_issuance_status=PromiseIssuanceStatus.ISSUED,
        service_delivery_status=ServiceDeliveryStatus.PENDING_DELIVERY,
        policy_id="PACKAGE_DAMAGE_REPLACEMENT_V1",
        supporting_ticket_ids=supporting_ticket_ids,
        reasons=(CompilationReason.AUTHORIZED_STANDARD,),
    )
    return CommitmentCompilation(
        compiled_at=_COMPILED_AT,
        policy_id="PACKAGE_DAMAGE_REPLACEMENT_V1",
        next_check_policy_id="D08_FIRST_POST_DEADLINE_CHECK_V1",
        promises=(promise,),
    )


def _evidence(
    evidence_status: str,
    *,
    missing_coverage: tuple[str, ...] = (),
    mismatched_source_ids: tuple[str, ...] = (),
    missing_source_ids: tuple[str, ...] = (),
    conflicting_source_ids: tuple[str, ...] = (),
) -> EvidenceAggregation:
    return EvidenceAggregation(
        evidence_status=evidence_status,
        scope_trace=(),
        matching_source_ids=(),
        mismatched_source_ids=mismatched_source_ids,
        missing_source_ids=missing_source_ids,
        conflicting_source_ids=conflicting_source_ids,
        missing_coverage=missing_coverage,
        reasons=(),
    )


def test_hero_prefers_the_existing_compiled_replacement_ticket_and_times() -> None:
    case = _case(tickets=(_ticket("replacement-a"), _ticket("replacement-z")))
    state = _state(case, include_progress_receipt=True)
    action = _action(state)
    evaluation = evaluate_decision(state, action)

    path = plan_resolution(
        evaluation,
        action,
        case,
        _compilation(supporting_ticket_ids=("replacement-z",)),
    )

    assert evaluation.rule_id == "E1"
    assert path.candidate_type == "CHECK_REPLACEMENT_FULFILLMENT"
    assert path.task_prefill.task_type == "CHECK_REPLACEMENT_STATUS"
    assert path.task_prefill.existing_ticket_id == "replacement-z"
    assert "existing_replacement_ticket:replacement-z" in path.evidence_basis
    assert path.requires_human_approval is False
    assert path.creates_obligation is False
    assert path.compiled_service_responsibility is not None
    assert path.compiled_service_responsibility.deadline == "2026-05-07T10:27:37+08:00"
    assert path.compiled_service_responsibility.next_check_at == "2026-05-07T10:30:00+08:00"


def test_e2_requests_only_missing_current_scope_materials() -> None:
    case = _case()
    state = _state(case, evidence_status="MISMATCHED")
    changed_scope = Scope.model_validate({**state.current_scope.model_dump(), "sku_id": "old-sku"})
    action = _action(state, requested_scope=changed_scope)
    evidence = _evidence(
        "MISMATCHED",
        missing_coverage=("PRODUCT_IDENTITY", "DAMAGE_DETAIL"),
        mismatched_source_ids=("old-image",),
        missing_source_ids=("blurred-image",),
    )

    evaluation = evaluate_decision(state, action, evidence=evidence)
    path = plan_resolution(evaluation, action, case, _compilation(), evidence=evidence)

    assert path.candidate_type == "ASK_CURRENT_SCOPE_EVIDENCE"
    assert path.task_prefill.task_type == "REQUEST_EVIDENCE"
    assert path.task_prefill.existing_ticket_id is None
    assert path.task_prefill.sku_id == "sku-16"
    assert "商品整体与标识照片" in path.consumer_reply_draft
    assert "问题细节照片" in path.consumer_reply_draft
    assert "受影响部位照片" not in path.consumer_reply_draft
    assert path.requires_human_approval is False
    assert path.creates_obligation is False


def test_e2_without_a_deterministic_missing_material_escalates_to_human_review() -> None:
    case = _case()
    state = _state(case, evidence_status="MISMATCHED")
    changed_scope = Scope.model_validate(
        {**state.current_scope.model_dump(), "sku_id": "old-sku"}
    )
    action = _action(state, requested_scope=changed_scope)
    evidence = _evidence("MISMATCHED", mismatched_source_ids=("old-image",))

    evaluation = evaluate_decision(state, action, evidence=evidence)
    path = plan_resolution(evaluation, action, case, _compilation(), evidence=evidence)

    assert path.candidate_type == "HUMAN_EVIDENCE_REVIEW"
    assert path.task_prefill.task_type == "HUMAN_EVIDENCE_REVIEW"
    assert path.requires_human_approval is True
    assert path.creates_obligation is False
    assert "no_deterministic_missing_material" in path.policy_basis


def test_source_conflict_escalates_even_when_the_firewall_result_is_e2() -> None:
    case = _case(tickets=(_ticket("replacement-16"),))
    state = _state(case, evidence_status="MISMATCHED")
    changed_scope = Scope.model_validate(
        {**state.current_scope.model_dump(), "sku_id": "old-sku"}
    )
    action = _action(state, requested_scope=changed_scope)
    evidence = _evidence(
        "MISMATCHED",
        missing_coverage=("DAMAGE_DETAIL",),
        conflicting_source_ids=("conflicting-image",),
    )

    evaluation = evaluate_decision(state, action, evidence=evidence)
    path = plan_resolution(
        evaluation,
        action,
        case,
        _compilation(supporting_ticket_ids=("replacement-16",)),
        evidence=evidence,
    )

    assert evaluation.rule_id == "E2"
    assert path.candidate_type == "HUMAN_EVIDENCE_REVIEW"
    assert path.executor == "HUMAN_REVIEW_QUEUE"
    assert path.requires_human_approval is True
    assert path.creates_obligation is False
    assert "conflicting_source:conflicting-image" in path.evidence_basis


def test_h1_and_existing_progress_e0_have_only_their_legal_candidates() -> None:
    case = _case(tickets=(_ticket("replacement-16"),))
    review_state = _state(case, evidence_status="NEED_HUMAN_REVIEW")
    review_action = _action(review_state)
    review_evidence = _evidence("NEED_HUMAN_REVIEW", missing_source_ids=("unclear-image",))

    review_path = plan_resolution(
        evaluate_decision(review_state, review_action, evidence=review_evidence),
        review_action,
        case,
        _compilation(supporting_ticket_ids=("replacement-16",)),
        evidence=review_evidence,
    )

    progress_state = _state(case)
    progress_action = _action(progress_state, action_type="CHECK_REPLACEMENT_PROGRESS")
    progress_path = plan_resolution(
        evaluate_decision(progress_state, progress_action),
        progress_action,
        case,
        _compilation(supporting_ticket_ids=("replacement-16",)),
    )

    assert review_path.candidate_type == "HUMAN_EVIDENCE_REVIEW"
    assert review_path.requires_human_approval is True
    assert review_path.creates_obligation is False
    assert progress_path.candidate_type == "CHECK_REPLACEMENT_FULFILLMENT"
    assert progress_path.task_prefill.existing_ticket_id == "replacement-16"
    assert progress_path.requires_human_approval is False
    assert progress_path.creates_obligation is False


def test_illegal_or_prohibited_rule_results_cannot_be_forced_into_a_candidate() -> None:
    case = _case()
    prohibited_state = _state(case, prohibited_actions=("CLOSE_BEFORE_RESOLUTION",))
    prohibited_action = _action(prohibited_state, action_type="CLOSE_CASE")

    with pytest.raises(ProhibitedActionError):
        plan_resolution(
            evaluate_decision(prohibited_state, prohibited_action),
            prohibited_action,
            case,
            _compilation(),
        )

    fallback_state = _state(case)
    unsupported_action = _action(fallback_state, action_type="CREATE_FOLLOW_UP_TASK")
    with pytest.raises(ResolutionPlanningError, match="CHECK_REPLACEMENT_PROGRESS"):
        plan_resolution(
            evaluate_decision(fallback_state, unsupported_action),
            unsupported_action,
            case,
            _compilation(),
        )


def test_reply_templates_do_not_leak_internal_values_or_accept_free_text() -> None:
    case = _case(tickets=(_ticket("replacement-16"),))
    state = _state(case, include_progress_receipt=True)
    action = _action(state)
    path = plan_resolution(
        evaluate_decision(state, action),
        action,
        case,
        _compilation(supporting_ticket_ids=("replacement-16",)),
    )

    for forbidden in ("王小明", "HIGH", "99分", "48小时", "2026-05-07T10:27:37"):
        assert forbidden not in path.consumer_reply_draft
    with pytest.raises(ReplyTemplateError):
        render_consumer_reply("ASK_CURRENT_SCOPE_EVIDENCE", missing_coverage=("99分",))
    with pytest.raises(ReplyTemplateError):
        render_consumer_reply("CHECK_REPLACEMENT_FULFILLMENT", missing_coverage=("DAMAGE_DETAIL",))
