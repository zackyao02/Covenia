from __future__ import annotations

from datetime import datetime, timedelta

from covenia_b.commitments.models import (
    ActivationStatus,
    CommitmentClass,
    CommitmentCompilation,
    CompiledPromise,
    PromiseAction,
    PromiseIssuanceStatus,
    ServiceDeliveryStatus,
)
from covenia_b.domain.types import (
    CaseInput,
    ExtractedJourney,
    ImageObservation,
    Scope,
)
from covenia_b.evidence import CandidateEvidence, CurrentEvidenceContext, aggregate_evidence
from covenia_b.state import (
    ApprovedResolution,
    ChallengeOverrides,
    FulfillmentProgress,
    PersistedLedger,
    build_accountability_state,
    rebuild_accountability_state,
)

SOURCE = "2026-05-05T10:27:37+08:00"
EVALUATION = "2026-05-07T09:40:00+08:00"


def make_case(*, expression: str = "我已经提交图片，但还不知道什么时候能解决") -> CaseInput:
    return CaseInput.model_validate(
        {
            "case_id": "case-state-1",
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-state-1",
                "augmentation_notes": [],
            },
            "evaluation_time": EVALUATION,
            "conversation": [
                {
                    "message_id": "consumer-1",
                    "timestamp": SOURCE,
                    "speaker": "CONSUMER",
                    "text": expression,
                    "source_kind": "COMPETITION_MOCK",
                },
                {
                    "message_id": "agent-1",
                    "timestamp": SOURCE,
                    "speaker": "AGENT",
                    "text": "换货单已创建，48小时内发出",
                    "source_kind": "COMPETITION_MOCK",
                },
            ],
            "order": {
                "order_id": "order-state-1",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "item-state-1",
                        "sku_id": "sku-state-1",
                        "product_name": "粉底液",
                        "batch_code": None,
                        "item_role": "PRIMARY",
                    }
                ],
                "original_logistics_number": "logistics-state-1",
            },
            "service_tickets": [
                {
                    "ticket_id": "ticket-state-1",
                    "ticket_type": "REPLACEMENT",
                    "status": "OPEN",
                    "assignee_id": "agent-state-1",
                    "executor_name": "仓库",
                    "replacement_logistics_number": None,
                    "created_at": SOURCE,
                    "completed_at": None,
                    "source_sheet": "replacement",
                }
            ],
            "evidence_images": [
                {
                    "evidence_id": "image-state-1",
                    "file_name": "proof.jpg",
                    "submitted_at": SOURCE,
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": "consumer-1",
                    "competition_reference_path": None,
                }
            ],
            "current_issue": {
                "fulfillment_item_id": "item-state-1",
                "sku_id": "sku-state-1",
                "issue_type": "PACKAGE_DAMAGE",
                "affected_component": "PUMP",
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )


def make_journey(
    case: CaseInput, *, expression: str = "我已经提交图片，但还不知道什么时候能解决"
) -> ExtractedJourney:
    return ExtractedJourney.model_validate(
        {
            "case_id": case.case_id,
            "completed_actions": {
                "issue_explained": True,
                "order_verified": True,
                "evidence_submitted": True,
            },
            "promise_events": [],
            "image_observations": [],
            "extracted_scope": {
                "order_id": "order-state-1",
                "fulfillment_item_id": "item-state-1",
                "sku_id": "sku-state-1",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "journey_understanding": {
                "consumer_intent": "获得可追踪的补发处理",
                "experience_expression": expression,
                "service_cause": "等待补发履约",
                "latent_need": "明确的处理进度",
                "cooperation_willingness": "STABLE",
                "action_impact": "需要服务方持续更新",
                "source_ids": ["consumer-1"],
            },
            "source_trace": [
                {"field": "experience_expression", "source_type": "CHAT", "source_id": "consumer-1"}
            ],
            "model_metadata": {
                "model_id": "Qwen/Qwen2-VL-2B-Instruct",
                "model_revision": None,
                "prompt_version": "test",
                "run_id": "test-run",
                "cached_result": True,
            },
        }
    )


def make_evidence(case: CaseInput, *, status_scope: Scope | None = None):
    scope = Scope(
        order_id=case.order.order_id,
        fulfillment_item_id=case.current_issue.fulfillment_item_id,
        sku_id=case.current_issue.sku_id,
        issue_type=case.current_issue.issue_type,
    )
    candidate_scope = status_scope or scope
    observation = ImageObservation(
        evidence_id="image-state-1",
        readability="HIGH",
        product_identifiable=True,
        sku_match="MATCH",
        product_role="PRIMARY",
        issue_visible=True,
        affected_component="PUMP",
        view_type="ISSUE_DETAIL",
        coverage=["PRODUCT_IDENTITY", "AFFECTED_COMPONENT", "DAMAGE_DETAIL"],
        integrity_concern=False,
        hygiene_risk_signal="LOW",
        confidence=0.1,
    )
    return aggregate_evidence(
        CurrentEvidenceContext(scope=scope, item_role="PRIMARY", affected_component="PUMP"),
        CandidateEvidence(
            candidate_id="candidate-state-1",
            extracted_scope=candidate_scope,
            image_observations=(observation,),
        ),
    )


DEFAULT_DEADLINE = datetime.fromisoformat("2026-05-07T10:27:37+08:00")


def make_compilation(*, deadline: datetime = DEFAULT_DEADLINE):
    return CommitmentCompilation(
        compiled_at=datetime.fromisoformat(EVALUATION),
        policy_id="PACKAGE_DAMAGE_REPLACEMENT_V1",
        next_check_policy_id="D08_FIRST_POST_DEADLINE_CHECK_V1",
        promises=(
            CompiledPromise(
                source_message_id="agent-1",
                raw_text="换货单已创建，48小时内发出",
                action=PromiseAction.REPLACEMENT_DISPATCH,
                commitment_class=CommitmentClass.STANDARD_APPROVED,
                activation_status=ActivationStatus.ACTIVE,
                deadline=deadline,
                next_check_at=deadline + timedelta(minutes=2, seconds=23),
                promise_issuance_status=PromiseIssuanceStatus.ISSUED,
                service_delivery_status=ServiceDeliveryStatus.PENDING_DELIVERY,
                policy_id="PACKAGE_DAMAGE_REPLACEMENT_V1",
                supporting_ticket_ids=("ticket-state-1",),
                reasons=(),
            ),
        ),
    )


def test_same_facts_produce_schema_valid_deterministic_snapshot() -> None:
    case = make_case()
    kwargs = {
        "case_input": case,
        "journey": make_journey(case),
        "evidence": make_evidence(case),
        "compilation": make_compilation(),
        "request_id": "request-state-1",
    }

    first = build_accountability_state(**kwargs)
    second = build_accountability_state(**kwargs)

    assert first == second
    assert first.case_status == "IN_FULFILLMENT"
    assert first.accountable_side == "BRAND"
    assert first.experience_risk == "MEDIUM"
    assert first.prohibited_actions == [
        "ASK_SAME_EVIDENCE",
        "ASK_REPEAT_EXPLANATION",
        "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "MAKE_UNTRACKABLE_PROMISE",
        "CLOSE_BEFORE_RESOLUTION",
    ]
    first.to_contract()


def test_pickup_is_not_resolved_and_delivered_wins_over_old_reanalysis() -> None:
    case = make_case()
    initial = build_accountability_state(
        case_input=case,
        journey=make_journey(case),
        evidence=make_evidence(case),
        compilation=make_compilation(),
        request_id="request-initial",
    )
    assert initial.case_status == "IN_FULFILLMENT"
    assert initial.open_obligation is not None
    assert initial.open_obligation.milestone == "AWAITING_CARRIER_PICKUP"

    persisted = PersistedLedger(
        initialized=True,
        approved_resolution=ApprovedResolution(
            deadline=datetime.fromisoformat("2026-05-07T10:27:37+08:00"),
            next_check_at=datetime.fromisoformat("2026-05-07T10:30:00+08:00"),
            source_ids=("agent-1",),
        ),
        fulfillment_progress=FulfillmentProgress(
            milestone="DELIVERED",
            status="COMPLETED",
            event_at=datetime.fromisoformat("2026-05-08T10:00:00+08:00"),
            receipt_id="receipt-state-1",
        ),
        prior_commitments=tuple(initial.active_commitments),
    )
    rebuilt = rebuild_accountability_state(
        case_input=case,
        journey=make_journey(case, expression="旧聊天语言"),
        evidence=make_evidence(case),
        compilation=make_compilation(),
        persisted=persisted,
        request_id="request-rebuild",
    )

    assert rebuilt.case_status == "RESOLVED"
    assert rebuilt.open_obligation is not None
    assert rebuilt.open_obligation.milestone == "DELIVERED"
    assert rebuilt.service_progress_receipt is not None
    assert rebuilt.service_progress_receipt.status == "COMPLETED"
    assert {commitment.status for commitment in rebuilt.active_commitments} == {"COMPLETED"}
    assert rebuilt.experience_risk == "LOW"
    assert "CLOSE_BEFORE_RESOLUTION" not in rebuilt.prohibited_actions


def test_challenge_override_is_isolated_and_does_not_change_history_or_normal_state() -> None:
    case = make_case()
    evidence = make_evidence(case)
    normal = build_accountability_state(
        case_input=case,
        journey=make_journey(case),
        evidence=evidence,
        compilation=make_compilation(),
        request_id="request-normal",
    )
    challenge = build_accountability_state(
        case_input=case,
        journey=make_journey(case),
        evidence=evidence,
        compilation=make_compilation(),
        request_id="request-challenge",
        challenge_overrides=ChallengeOverrides(evidence_status="MISMATCHED"),
    )

    assert normal.case_status == "IN_FULFILLMENT"
    assert challenge.case_status == "WAITING_FOR_CONSUMER"
    assert challenge.consumer_input_required is True
    assert normal.case_status == "IN_FULFILLMENT"
    assert evidence.evidence_status == "VALID"


def test_rebuild_requires_explicit_initialized_history_and_human_history_wins() -> None:
    case = make_case()
    empty = PersistedLedger()
    try:
        rebuild_accountability_state(
            case_input=case,
            journey=make_journey(case),
            evidence=make_evidence(case),
            compilation=make_compilation(),
            persisted=empty,
            request_id="request-invalid-rebuild",
        )
    except ValueError as error:
        assert "initialized" in str(error)
    else:
        raise AssertionError("uninitialized history must not enter rebuild path")

    approved = ApprovedResolution(
        deadline=datetime.fromisoformat("2026-05-09T10:00:00+08:00"),
        next_check_at=datetime.fromisoformat("2026-05-09T10:05:00+08:00"),
        executor="LOGISTICS_PROVIDER",
        source_ids=("human-approval-1",),
    )
    state = rebuild_accountability_state(
        case_input=case,
        journey=make_journey(case),
        evidence=make_evidence(case),
        compilation=make_compilation(deadline=datetime.fromisoformat("2026-05-07T10:27:37+08:00")),
        persisted=PersistedLedger(initialized=True, approved_resolution=approved),
        request_id="request-human-history",
    )
    assert state.open_obligation is not None
    assert state.open_obligation.executor == "LOGISTICS_PROVIDER"
    assert state.open_obligation.deadline == "2026-05-09T10:00:00+08:00"
