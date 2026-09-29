"""Deterministic, side-effect-free construction of ``AccountabilityState``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from covenia_b.commitments.models import (
    D08_FIRST_POST_DEADLINE_CHECK,
    ActivationStatus,
    CommitmentCompilation,
    CompiledPromise,
)
from covenia_b.domain.time import format_rfc3339_timestamp
from covenia_b.domain.types import (
    AccountabilityState,
    ActiveCommitment,
    AuditEntry,
    CaseInput,
    ExperienceGapDiagnosis,
    ExtractedJourney,
    OpenObligation,
    ResponsibilityJudgment,
    Scope,
    ServiceProgressReceipt,
    TraceableServiceFact,
)
from covenia_b.evidence.aggregation import EvidenceAggregation

from .models import (
    ApprovedResolution,
    ChallengeOverrides,
    FulfillmentProgress,
    PersistedLedger,
)

_DEFAULT_RECOVERY = "品牌将主动催办并通知新的处理时间"
_ANALYZED_FIELDS = [
    "case_status",
    "consumer_input_required",
    "accountable_side",
    "evidence_status",
    "active_commitments",
    "prohibited_actions",
    "open_obligation",
    "service_progress_receipt",
    "experience_risk",
]


@dataclass(frozen=True, slots=True)
class _ResponsibilityProjection:
    commitments: list[ActiveCommitment]
    obligation: OpenObligation | None
    receipt: ServiceProgressReceipt | None
    completed: bool
    at_risk: bool


def build_accountability_state(
    *,
    case_input: CaseInput,
    journey: ExtractedJourney,
    evidence: EvidenceAggregation,
    compilation: CommitmentCompilation,
    request_id: str,
    persisted: PersistedLedger | None = None,
    actor: str = "ACCOUNTABILITY_BUILDER",
    challenge_overrides: ChallengeOverrides | None = None,
) -> AccountabilityState:
    """Build a snapshot without writing storage, calling a model, or mutating input.

    With no ``persisted`` ledger this is the initialization path.  Passing a
    ledger is the pure rebuild path; its approved responsibility and shipment
    progress take precedence over a fresh chat/AI-derived compilation.
    """

    if persisted is None:
        return initialize_accountability_state(
            case_input=case_input,
            journey=journey,
            evidence=evidence,
            compilation=compilation,
            request_id=request_id,
            actor=actor,
            challenge_overrides=challenge_overrides,
        )
    return rebuild_accountability_state(
        case_input=case_input,
        journey=journey,
        evidence=evidence,
        compilation=compilation,
        persisted=persisted,
        request_id=request_id,
        actor=actor,
        challenge_overrides=challenge_overrides,
    )


def initialize_accountability_state(
    *,
    case_input: CaseInput,
    journey: ExtractedJourney,
    evidence: EvidenceAggregation,
    compilation: CommitmentCompilation,
    request_id: str,
    actor: str = "ACCOUNTABILITY_BUILDER",
    challenge_overrides: ChallengeOverrides | None = None,
) -> AccountabilityState:
    """Construct the first ledger snapshot from current trusted facts."""

    return _build(
        case_input=case_input,
        journey=journey,
        evidence=evidence,
        compilation=compilation,
        persisted=PersistedLedger(),
        request_id=request_id,
        actor=actor,
        challenge_overrides=challenge_overrides,
    )


def rebuild_accountability_state(
    *,
    case_input: CaseInput,
    journey: ExtractedJourney,
    evidence: EvidenceAggregation,
    compilation: CommitmentCompilation,
    persisted: PersistedLedger,
    request_id: str,
    actor: str = "ACCOUNTABILITY_BUILDER",
    challenge_overrides: ChallengeOverrides | None = None,
) -> AccountabilityState:
    """Rebuild a snapshot while preserving the supplied persisted history."""

    if not persisted.initialized:
        raise ValueError("rebuild_accountability_state requires initialized persisted history")
    return _build(
        case_input=case_input,
        journey=journey,
        evidence=evidence,
        compilation=compilation,
        persisted=persisted,
        request_id=request_id,
        actor=actor,
        challenge_overrides=challenge_overrides,
    )


def _build(
    *,
    case_input: CaseInput,
    journey: ExtractedJourney,
    evidence: EvidenceAggregation,
    compilation: CommitmentCompilation,
    persisted: PersistedLedger,
    request_id: str,
    actor: str,
    challenge_overrides: ChallengeOverrides | None,
) -> AccountabilityState:
    if not request_id.strip():
        raise ValueError("request_id must not be blank")
    if not actor.strip():
        raise ValueError("actor must not be blank")

    evaluation_time = _parse_timestamp(case_input.evaluation_time)
    scope = _scope_from_case(case_input)
    if challenge_overrides is not None and challenge_overrides.current_scope is not None:
        scope = challenge_overrides.current_scope
    evidence_status = (
        challenge_overrides.evidence_status
        if challenge_overrides is not None and challenge_overrides.evidence_status is not None
        else evidence.evidence_status
    )

    projection = _responsibility_projection(
        case_input=case_input,
        compilation=compilation,
        persisted=persisted,
        evaluation_time=evaluation_time,
    )
    case_status = _case_status(
        case_input=case_input,
        evidence_status=evidence_status,
        compilation=compilation,
        projection=projection,
    )
    consumer_input_required = evidence_status == "MISMATCHED"
    accountable_side = _accountable_side(
        case_status=case_status,
        consumer_input_required=consumer_input_required,
        projection=projection,
    )
    prohibited_actions = _prohibited_actions(
        case_input=case_input,
        evidence_status=evidence_status,
        consumer_input_required=consumer_input_required,
        case_status=case_status,
        projection=projection,
        persisted=persisted,
    )
    experience_risk = _experience_risk(
        case_input=case_input,
        evidence_status=evidence_status,
        projection=projection,
        prohibited_actions=prohibited_actions,
    )
    diagnosis = _diagnosis(
        case_input=case_input,
        journey=journey,
        evidence_status=evidence_status,
        case_status=case_status,
        accountable_side=accountable_side,
        consumer_input_required=consumer_input_required,
        projection=projection,
        persisted=persisted,
    )
    audit_trail = [*persisted.audit_trail]
    audit_trail.append(
        AuditEntry(
            at=format_rfc3339_timestamp(evaluation_time),
            actor=actor,
            action="ANALYZED",
            changed_fields=list(_ANALYZED_FIELDS),
            request_id=request_id,
        )
    )
    return AccountabilityState(
        case_id=case_input.case_id,
        case_status=case_status,
        consumer_input_required=consumer_input_required,
        accountable_side=accountable_side,
        evidence_status=evidence_status,
        current_scope=scope,
        active_commitments=projection.commitments,
        prohibited_actions=prohibited_actions,
        experience_gap_diagnosis=diagnosis,
        open_obligation=projection.obligation,
        service_progress_receipt=projection.receipt,
        experience_risk=experience_risk,
        audit_trail=audit_trail,
    )


def _responsibility_projection(
    *,
    case_input: CaseInput,
    compilation: CommitmentCompilation,
    persisted: PersistedLedger,
    evaluation_time: datetime,
) -> _ResponsibilityProjection:
    active_promises = tuple(
        sorted(
            (
                promise
                for promise in compilation.promises
                if promise.activation_status is ActivationStatus.ACTIVE
            ),
            key=lambda promise: (promise.source_message_id, promise.raw_text),
        )
    )
    progress = persisted.fulfillment_progress
    approved = persisted.approved_resolution
    existing = list(persisted.prior_commitments)
    completed = progress is not None and progress.milestone == "DELIVERED"
    at_risk = progress is not None and progress.status == "AT_RISK"

    commitments = list(existing)
    for promise in active_promises:
        source_ids = (promise.source_message_id,)
        status = _commitment_status(
            deadline=promise.deadline,
            previous=None,
            completed=completed,
            at_risk=at_risk,
            evaluation_time=evaluation_time,
        )
        replacement = ActiveCommitment(
            promise_type=promise.action.value,
            raw_text=promise.raw_text,
            status=status,
            deadline=format_rfc3339_timestamp(promise.deadline),
            source_ids=list(source_ids),
        )
        _merge_commitment(commitments, replacement, source_ids)

    if approved is not None and not any(
        set(approved.source_ids).intersection(commitment.source_ids) for commitment in commitments
    ):
        status = _commitment_status(
            deadline=approved.deadline,
            previous=None,
            completed=completed,
            at_risk=at_risk,
            evaluation_time=evaluation_time,
        )
        commitments.append(
            ActiveCommitment(
                promise_type=approved.promise_type,
                raw_text=approved.raw_text,
                status=status,
                deadline=format_rfc3339_timestamp(approved.deadline),
                source_ids=list(approved.source_ids),
            )
        )

    for index, commitment in enumerate(commitments):
        deadline = _parse_timestamp(commitment.deadline)
        status = _commitment_status(
            deadline=deadline,
            previous=commitment.status,
            completed=completed,
            at_risk=at_risk,
            evaluation_time=evaluation_time,
        )
        if status != commitment.status:
            commitments[index] = commitment.model_copy(update={"status": status})

    responsibility = _select_responsibility(
        active_promises=active_promises,
        approved=approved,
        commitments=commitments,
        progress=progress,
    )
    if responsibility is None:
        return _ResponsibilityProjection(
            commitments=commitments,
            obligation=None,
            receipt=None,
            completed=completed,
            at_risk=at_risk,
        )

    deadline, next_check_at, executor, recovery, milestone = responsibility
    if progress is not None:
        milestone = progress.milestone
        executor = progress.executor
        completed = milestone == "DELIVERED"
        at_risk = progress.status == "AT_RISK" and not completed
    elif deadline <= evaluation_time:
        at_risk = True

    obligation_status = "COMPLETED" if completed else "AT_RISK" if at_risk else "ON_TRACK"
    obligation = OpenObligation(
        obligation_type="REPLACEMENT_FULFILLMENT",
        status=obligation_status,
        accountable_side="BRAND",
        executor=executor,
        deadline=format_rfc3339_timestamp(deadline),
        next_check_at=format_rfc3339_timestamp(next_check_at),
        milestone=milestone,
        resolution_condition="REPLACEMENT_DELIVERED",
    )
    latest_update = (
        persisted.latest_update_at
        or (progress.event_at if progress is not None else None)
        or evaluation_time
    )
    receipt = ServiceProgressReceipt(
        receipt_id=(
            persisted.receipt_id
            or (progress.receipt_id if progress is not None else None)
            or f"{case_input.case_id}:replacement"
        ),
        status="COMPLETED" if completed else "AT_RISK" if at_risk else "ACTIVE",
        received_evidence=sorted(image.evidence_id for image in case_input.evidence_images),
        brand_action=_brand_action(milestone),
        latest_update_at=format_rfc3339_timestamp(latest_update),
        next_update_by=format_rfc3339_timestamp(next_check_at),
        consumer_action_required=False,
        recovery_if_missed=recovery,
    )
    return _ResponsibilityProjection(
        commitments=commitments,
        obligation=obligation,
        receipt=receipt,
        completed=completed,
        at_risk=at_risk,
    )


def _select_responsibility(
    *,
    active_promises: tuple[CompiledPromise, ...],
    approved: ApprovedResolution | None,
    commitments: list[ActiveCommitment],
    progress: FulfillmentProgress | None,
) -> tuple[datetime, datetime, str, str, str] | None:
    if approved is not None:
        return (
            approved.deadline,
            approved.next_check_at,
            approved.executor,
            approved.recovery_if_missed,
            progress.milestone if progress is not None else "AWAITING_CARRIER_PICKUP",
        )
    if active_promises:
        promise = active_promises[0]
        assert promise.deadline is not None and promise.next_check_at is not None
        return (
            promise.deadline,
            promise.next_check_at,
            "WAREHOUSE",
            _DEFAULT_RECOVERY,
            progress.milestone if progress is not None else "AWAITING_CARRIER_PICKUP",
        )
    if progress is not None:
        prior = _earliest_commitment(commitments)
        if prior is None:
            return None
        deadline = _parse_timestamp(prior.deadline)
        return (
            deadline,
            deadline + D08_FIRST_POST_DEADLINE_CHECK.after_deadline,
            progress.executor,
            _DEFAULT_RECOVERY,
            progress.milestone,
        )
    return None


def _merge_commitment(
    commitments: list[ActiveCommitment], replacement: ActiveCommitment, source_ids: tuple[str, ...]
) -> None:
    for index, existing in enumerate(commitments):
        if set(source_ids).intersection(existing.source_ids):
            preserved_status = (
                "COMPLETED" if existing.status == "COMPLETED" else replacement.status
            )
            commitments[index] = replacement.model_copy(update={"status": preserved_status})
            return
    commitments.append(replacement)


def _commitment_status(
    *,
    deadline: datetime,
    previous: str | None,
    completed: bool,
    at_risk: bool,
    evaluation_time: datetime,
) -> str:
    if completed or previous == "COMPLETED":
        return "COMPLETED"
    if at_risk or deadline <= evaluation_time:
        return "AT_RISK"
    return "ACTIVE"


def _earliest_commitment(commitments: list[ActiveCommitment]) -> ActiveCommitment | None:
    if not commitments:
        return None
    return min(commitments, key=lambda commitment: (commitment.deadline, commitment.source_ids))


def _case_status(
    *,
    case_input: CaseInput,
    evidence_status: str,
    compilation: CommitmentCompilation,
    projection: _ResponsibilityProjection,
) -> str:
    if projection.completed:
        return "RESOLVED"
    if evidence_status == "MISMATCHED":
        return "WAITING_FOR_CONSUMER"
    if evidence_status == "NEED_HUMAN_REVIEW" or (
        case_input.current_issue.issue_type == "ADVERSE_REACTION"
    ):
        return "ACTION_REVIEW"
    if projection.at_risk:
        return "AT_RISK"
    if projection.obligation is not None:
        return "IN_FULFILLMENT"
    if any(
        promise.activation_status is not ActivationStatus.ACTIVE
        for promise in compilation.promises
    ):
        return "ACTION_REVIEW"
    return "READY_FOR_BRAND"


def _accountable_side(
    *,
    case_status: str,
    consumer_input_required: bool,
    projection: _ResponsibilityProjection,
) -> str:
    if consumer_input_required:
        return "CONSUMER"
    if projection.obligation is not None or case_status in {
        "READY_FOR_BRAND",
        "IN_FULFILLMENT",
        "AT_RISK",
        "RESOLVED",
    }:
        return "BRAND"
    return "UNKNOWN"


def _prohibited_actions(
    *,
    case_input: CaseInput,
    evidence_status: str,
    consumer_input_required: bool,
    case_status: str,
    projection: _ResponsibilityProjection,
    persisted: PersistedLedger,
) -> list[str]:
    actions: list[str] = []
    if evidence_status == "VALID":
        actions.append("ASK_SAME_EVIDENCE")
    explanation_received = persisted.explanation_received or any(
        message.speaker == "CONSUMER" and message.text.strip()
        for message in case_input.conversation
    )
    if explanation_received:
        actions.append("ASK_REPEAT_EXPLANATION")
    if not consumer_input_required and case_status != "WAITING_FOR_CONSUMER":
        actions.append("SHIFT_FOLLOW_UP_TO_CONSUMER")
    actions.append("MAKE_UNTRACKABLE_PROMISE")
    if case_status != "RESOLVED":
        actions.append("CLOSE_BEFORE_RESOLUTION")
    return actions


def _experience_risk(
    *,
    case_input: CaseInput,
    evidence_status: str,
    projection: _ResponsibilityProjection,
    prohibited_actions: list[str],
) -> str:
    if projection.completed:
        return "LOW"
    if case_input.current_issue.issue_type == "ADVERSE_REACTION":
        return "HIGH"
    if evidence_status == "NEED_HUMAN_REVIEW" or projection.at_risk:
        return "HIGH"
    if projection.obligation is not None or "ASK_REPEAT_EXPLANATION" in prohibited_actions:
        return "MEDIUM"
    return "LOW"


def _diagnosis(
    *,
    case_input: CaseInput,
    journey: ExtractedJourney,
    evidence_status: str,
    case_status: str,
    accountable_side: str,
    consumer_input_required: bool,
    projection: _ResponsibilityProjection,
    persisted: PersistedLedger,
) -> ExperienceGapDiagnosis:
    facts: list[TraceableServiceFact] = []
    image_ids = sorted(image.evidence_id for image in case_input.evidence_images)
    if image_ids:
        facts.append(
            TraceableServiceFact(
                fact_type="EVIDENCE_SUBMITTED",
                statement="当前问题证据已提交并进入服务事实链",
                source_ids=image_ids,
            )
        )
    ticket_ids = sorted(ticket.ticket_id for ticket in case_input.service_tickets)
    if ticket_ids:
        facts.append(
            TraceableServiceFact(
                fact_type="TICKET_CREATED",
                statement="已有服务工单记录当前处理范围",
                source_ids=ticket_ids,
            )
        )
    if projection.commitments:
        fact_type = "PROMISE_OVERDUE" if projection.at_risk else "PROMISE_ACTIVE"
        facts.append(
            TraceableServiceFact(
                fact_type=fact_type,
                statement="服务责任账本保留已编译的履约承诺",
                source_ids=sorted(
                    {
                        source_id
                        for commitment in projection.commitments
                        for source_id in commitment.source_ids
                    }
                ),
            )
        )
    if persisted.repeat_contact_count > 0:
        facts.append(
            TraceableServiceFact(
                fact_type="REPEAT_CONTACT",
                statement="服务历史记录存在重复联系",
                source_ids=[f"repeat-contact:{persisted.repeat_contact_count}"],
            )
        )
    if not facts:
        facts.append(
            TraceableServiceFact(
                fact_type="OTHER",
                statement="服务事实正在等待可追溯输入",
                source_ids=[f"case:{case_input.case_id}"],
            )
        )

    impacts: list[str] = []
    if consumer_input_required:
        impacts.append("REQUEST_MISSING_INPUT")
    if evidence_status == "NEED_HUMAN_REVIEW" or case_status == "ACTION_REVIEW":
        impacts.append("ROUTE_TO_HUMAN")
    if evidence_status == "VALID":
        impacts.extend(["BLOCK_REPEAT_EVIDENCE", "CHECK_EXISTING_FULFILLMENT"])
    if projection.obligation is not None:
        impacts.append("START_PROACTIVE_UPDATE")
    if projection.at_risk:
        impacts.append("RAISE_PRIORITY")
    impacts = _ordered_unique(impacts)
    if not impacts:
        impacts.append("ROUTE_TO_HUMAN")

    causes = {
        "WAITING_FOR_CONSUMER": "当前问题范围所需输入未完整",
        "ACTION_REVIEW": "责任动作尚未形成可执行批准",
        "READY_FOR_BRAND": "问题证据已完整，待品牌动作",
        "IN_FULFILLMENT": "已收录问题仍等待服务履约完成",
        "AT_RISK": "已批准服务承诺未按时推进",
        "RESOLVED": "服务承诺已完成",
    }
    replies = {
        "WAITING_FOR_CONSUMER": "请仅补充当前范围缺失的输入，已提交内容无需重复提供。",
        "ACTION_REVIEW": "当前事实已保留，转入人工复核并等待可审计的责任动作。",
        "READY_FOR_BRAND": "当前证据已收到，品牌侧将确认并推进后续处理。",
        "IN_FULFILLMENT": "已收到当前证据，品牌将按责任账本推进补发并更新进度。",
        "AT_RISK": "服务承诺已进入风险状态，品牌将主动催办并通知新的处理时间。",
        "RESOLVED": "补发商品已送达，当前服务责任已完成。",
    }
    return ExperienceGapDiagnosis(
        consumer_expression=journey.journey_understanding.experience_expression,
        traceable_service_facts=facts,
        deterioration_cause=causes[case_status],
        latent_need=journey.journey_understanding.latent_need,
        responsibility_judgment=ResponsibilityJudgment(
            consumer_input_complete=not consumer_input_required,
            accountable_side=accountable_side,
        ),
        action_impacts=impacts,
        reply_strategy=replies[case_status],
    )


def _scope_from_case(case_input: CaseInput) -> Scope:
    return Scope(
        order_id=case_input.order.order_id,
        fulfillment_item_id=case_input.current_issue.fulfillment_item_id,
        sku_id=case_input.current_issue.sku_id,
        issue_type=case_input.current_issue.issue_type,
    )


def _brand_action(milestone: str) -> str:
    return {
        "AWAITING_CARRIER_PICKUP": "品牌将跟进补发商品并等待物流揽收",
        "IN_TRANSIT": "品牌将持续提供物流进度",
        "DELIVERED": "品牌已完成补发交付",
    }[milestone]


def _accountability_deadline(commitment: ActiveCommitment) -> datetime:
    return _parse_timestamp(commitment.deadline)


def _parse_timestamp(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("accountability timestamps must be timezone-aware")
    return parsed


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
