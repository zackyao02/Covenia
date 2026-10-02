"""Pure, deterministic planning of legal resolution candidates.

This module converts a previously evaluated firewall result into one of the
three schema-approved candidates.  It only describes a next task: it does not
create a ticket, dispatch a replacement, issue a refund, pay compensation, or
send a consumer message.
"""

from __future__ import annotations

from dataclasses import dataclass

from covenia_b.commitments.models import (
    ActivationStatus,
    CommitmentCompilation,
    CompiledPromise,
    PromiseAction,
)
from covenia_b.domain.time import format_rfc3339_timestamp
from covenia_b.domain.types import (
    CaseInput,
    CompiledServiceResponsibility,
    PreparedAction,
    ResolutionPath,
    ServiceTicket,
    TaskPrefill,
)
from covenia_b.evidence.aggregation import EvidenceAggregation
from covenia_b.resolutions.reply_templates import (
    ReplyTemplateError,
    missing_material_labels,
    render_consumer_reply,
)
from covenia_b.rules.engine import RuleEvaluation

_DEFAULT_RECOVERY = "品牌将主动催办并通知新的处理时间"
_REQUIRED_COVERAGE = frozenset(
    {"PRODUCT_IDENTITY", "AFFECTED_COMPONENT", "DAMAGE_DETAIL"}
)


class ResolutionPlanningError(ValueError):
    """Raised when trusted inputs cannot produce a safe, legal candidate."""


@dataclass(frozen=True, slots=True)
class _ExistingFulfillment:
    ticket: ServiceTicket | None
    promise: CompiledPromise | None


def plan_resolution(
    evaluation: RuleEvaluation,
    prepared_action: PreparedAction,
    case_input: CaseInput,
    compilation: CommitmentCompilation,
    *,
    evidence: EvidenceAggregation | None = None,
) -> ResolutionPath:
    """Plan a candidate without changing trusted state or creating an obligation.

    A caller must provide the same evaluated ``PreparedAction`` and authoritative
    ``CaseInput`` that produced the firewall result.  Unsupported combinations
    fail closed rather than assigning a candidate type by force.
    """

    _validate_inputs(evaluation, prepared_action, case_input, compilation, evidence)
    evaluation.require_permitted_action()

    if evidence is not None and evidence.conflicting_source_ids:
        return _human_review_path(
            evaluation,
            case_input,
            compilation,
            evidence,
            policy_reason="source_conflict",
        )

    if evaluation.rule_id == "H1":
        return _human_review_path(
            evaluation,
            case_input,
            compilation,
            evidence,
            policy_reason="rule_required_review",
        )
    if evaluation.rule_id == "E1":
        _require_action(prepared_action, "ASK_EVIDENCE")
        return _fulfillment_check_path(evaluation, case_input, compilation)
    if evaluation.rule_id == "E2":
        _require_action(prepared_action, "ASK_EVIDENCE")
        return _current_scope_evidence_path(
            evaluation,
            prepared_action,
            case_input,
            compilation,
            evidence,
        )
    if evaluation.rule_id == "E0_NO_RULE_MATCHED":
        _require_action(prepared_action, "CHECK_REPLACEMENT_PROGRESS")
        return _fulfillment_check_path(evaluation, case_input, compilation)
    raise ResolutionPlanningError("the rule result has no legal resolution candidate")


def _validate_inputs(
    evaluation: RuleEvaluation,
    prepared_action: PreparedAction,
    case_input: CaseInput,
    compilation: CommitmentCompilation,
    evidence: EvidenceAggregation | None,
) -> None:
    if not isinstance(evaluation, RuleEvaluation):
        raise TypeError("evaluation must be a RuleEvaluation")
    if not isinstance(prepared_action, PreparedAction):
        raise TypeError("prepared_action must be a PreparedAction")
    if not isinstance(case_input, CaseInput):
        raise TypeError("case_input must be a CaseInput")
    if not isinstance(compilation, CommitmentCompilation):
        raise TypeError("compilation must be a CommitmentCompilation")
    state = evaluation.accountability_state
    if state.case_id != case_input.case_id:
        raise ResolutionPlanningError("case input and rule evaluation must have the same case_id")
    if evaluation.fact_trace.prepared_action != prepared_action.action_type:
        raise ResolutionPlanningError("prepared action does not match the rule evaluation trace")
    if evaluation.fact_trace.evidence_status != state.evidence_status:
        raise ResolutionPlanningError("rule evaluation evidence status is not authoritative")
    if evidence is not None:
        if not isinstance(evidence, EvidenceAggregation):
            raise TypeError("evidence must be an EvidenceAggregation")
        if evidence.evidence_status != state.evidence_status:
            raise ResolutionPlanningError("evidence aggregation must match the authoritative state")
    case_scope = case_input.current_issue
    state_scope = state.current_scope
    if (
        case_input.order.order_id != state_scope.order_id
        or case_scope.fulfillment_item_id != state_scope.fulfillment_item_id
        or case_scope.sku_id != state_scope.sku_id
        or case_scope.issue_type != state_scope.issue_type
    ):
        raise ResolutionPlanningError("case input scope does not match the authoritative state")


def _require_action(prepared_action: PreparedAction, expected_action_type: str) -> None:
    if prepared_action.action_type != expected_action_type:
        raise ResolutionPlanningError(
            f"{expected_action_type} is required for this rule result, not "
            f"{prepared_action.action_type}"
        )


def _fulfillment_check_path(
    evaluation: RuleEvaluation,
    case_input: CaseInput,
    compilation: CommitmentCompilation,
) -> ResolutionPath:
    state = evaluation.accountability_state
    fulfillment = _existing_fulfillment(case_input, compilation)
    evidence_basis = [f"rule:{evaluation.rule_id}"]
    if fulfillment.ticket is not None:
        evidence_basis.append(f"existing_replacement_ticket:{fulfillment.ticket.ticket_id}")
    if fulfillment.promise is not None:
        evidence_basis.append(f"compiled_promise_source:{fulfillment.promise.source_message_id}")
    if state.service_progress_receipt is not None:
        evidence_basis.append(f"service_progress_receipt:{state.service_progress_receipt.receipt_id}")
    return ResolutionPath(
        candidate_type="CHECK_REPLACEMENT_FULFILLMENT",
        evidence_basis=evidence_basis,
        policy_basis=(
            f"rule:{evaluation.rule_id}; existing_fulfillment_query_only; "
            f"commitment_policy:{compilation.policy_id}"
        ),
        consumer_reply_draft=render_consumer_reply("CHECK_REPLACEMENT_FULFILLMENT"),
        task_prefill=TaskPrefill(
            task_type="CHECK_REPLACEMENT_STATUS",
            existing_ticket_id=(
                fulfillment.ticket.ticket_id if fulfillment.ticket is not None else None
            ),
            sku_id=state.current_scope.sku_id,
            affected_component=case_input.current_issue.affected_component,
            summary="查询既有换货工单进度，不创建新换货、退款、赔偿或补发。",
        ),
        accountable_side=state.accountable_side,
        executor="BRAND",
        requires_human_approval=False,
        creates_obligation=False,
        compiled_service_responsibility=_compiled_responsibility(fulfillment.promise, evaluation),
    )


def _current_scope_evidence_path(
    evaluation: RuleEvaluation,
    prepared_action: PreparedAction,
    case_input: CaseInput,
    compilation: CommitmentCompilation,
    evidence: EvidenceAggregation | None,
) -> ResolutionPath:
    if evidence is None:
        raise ResolutionPlanningError("E2 planning requires server evidence aggregation detail")
    if prepared_action.requested_scope is None:
        raise ResolutionPlanningError("E2 planning requires an evidence request scope")
    if evidence.evidence_status != "MISMATCHED":
        raise ResolutionPlanningError("E2 planning requires mismatched evidence")
    coverage = tuple(evidence.missing_coverage)
    if not coverage:
        return _human_review_path(
            evaluation,
            case_input,
            compilation,
            evidence,
            policy_reason="no_deterministic_missing_material",
        )
    if not set(coverage).issubset(_REQUIRED_COVERAGE):
        raise ResolutionPlanningError("evidence aggregation requested unsupported coverage")
    try:
        missing_material_labels(coverage)
        consumer_reply = render_consumer_reply(
            "ASK_CURRENT_SCOPE_EVIDENCE", missing_coverage=coverage
        )
    except ReplyTemplateError as error:
        raise ResolutionPlanningError("unable to render a bounded evidence request") from error

    state = evaluation.accountability_state
    fulfillment = _existing_fulfillment(case_input, compilation)
    evidence_basis = [f"rule:{evaluation.rule_id}", "authoritative_current_scope"]
    evidence_basis.extend(f"missing_coverage:{item}" for item in coverage)
    evidence_basis.extend(_source_basis("mismatched_source", evidence.mismatched_source_ids))
    evidence_basis.extend(_source_basis("missing_source", evidence.missing_source_ids))
    return ResolutionPath(
        candidate_type="ASK_CURRENT_SCOPE_EVIDENCE",
        evidence_basis=evidence_basis,
        policy_basis=(
            f"rule:{evaluation.rule_id}; current_scope_missing_coverage_only; "
            f"commitment_policy:{compilation.policy_id}"
        ),
        consumer_reply_draft=consumer_reply,
        task_prefill=TaskPrefill(
            task_type="REQUEST_EVIDENCE",
            existing_ticket_id=None,
            sku_id=state.current_scope.sku_id,
            affected_component=case_input.current_issue.affected_component,
            summary="仅补充当前范围缺失材料，不重复索取已有材料。",
        ),
        accountable_side=state.accountable_side,
        executor="CONSUMER",
        requires_human_approval=False,
        creates_obligation=False,
        compiled_service_responsibility=_compiled_responsibility(fulfillment.promise, evaluation),
    )


def _human_review_path(
    evaluation: RuleEvaluation,
    case_input: CaseInput,
    compilation: CommitmentCompilation,
    evidence: EvidenceAggregation | None,
    *,
    policy_reason: str,
) -> ResolutionPath:
    state = evaluation.accountability_state
    fulfillment = _existing_fulfillment(case_input, compilation)
    evidence_basis = [f"rule:{evaluation.rule_id}", f"review_reason:{policy_reason}"]
    if evidence is not None:
        evidence_basis.append(f"evidence_status:{evidence.evidence_status}")
        evidence_basis.extend(_source_basis("conflicting_source", evidence.conflicting_source_ids))
        evidence_basis.extend(_source_basis("mismatched_source", evidence.mismatched_source_ids))
        evidence_basis.extend(_source_basis("missing_source", evidence.missing_source_ids))
    if fulfillment.ticket is not None:
        evidence_basis.append(f"existing_replacement_ticket:{fulfillment.ticket.ticket_id}")
    if fulfillment.promise is not None:
        evidence_basis.append(f"compiled_promise_source:{fulfillment.promise.source_message_id}")
    return ResolutionPath(
        candidate_type="HUMAN_EVIDENCE_REVIEW",
        evidence_basis=evidence_basis,
        policy_basis=(
            f"rule:{evaluation.rule_id}; {policy_reason}; human_approval_required; "
            f"commitment_policy:{compilation.policy_id}"
        ),
        consumer_reply_draft=render_consumer_reply("HUMAN_EVIDENCE_REVIEW"),
        task_prefill=TaskPrefill(
            task_type="HUMAN_EVIDENCE_REVIEW",
            existing_ticket_id=(
                fulfillment.ticket.ticket_id if fulfillment.ticket is not None else None
            ),
            sku_id=state.current_scope.sku_id,
            affected_component=case_input.current_issue.affected_component,
            summary="人工复核证据范围或来源冲突，不创建新的履约或资金义务。",
        ),
        accountable_side=state.accountable_side,
        executor="HUMAN_REVIEW_QUEUE",
        requires_human_approval=True,
        creates_obligation=False,
        compiled_service_responsibility=_compiled_responsibility(fulfillment.promise, evaluation),
    )


def _existing_fulfillment(
    case_input: CaseInput,
    compilation: CommitmentCompilation,
) -> _ExistingFulfillment:
    open_tickets = sorted(
        (
            ticket
            for ticket in case_input.service_tickets
            if ticket.ticket_type == "REPLACEMENT" and ticket.completed_at is None
        ),
        key=lambda ticket: ticket.ticket_id,
    )
    ticket_by_id = {ticket.ticket_id: ticket for ticket in open_tickets}
    promises = sorted(
        (
            promise
            for promise in compilation.promises
            if promise.action is PromiseAction.REPLACEMENT_DISPATCH
            and promise.activation_status is ActivationStatus.ACTIVE
        ),
        key=lambda promise: (promise.source_message_id, promise.raw_text),
    )
    for promise in promises:
        for ticket_id in sorted(promise.supporting_ticket_ids):
            ticket = ticket_by_id.get(ticket_id)
            if ticket is not None:
                return _ExistingFulfillment(ticket=ticket, promise=promise)
    return _ExistingFulfillment(
        ticket=open_tickets[0] if open_tickets else None,
        promise=promises[0] if promises else None,
    )


def _compiled_responsibility(
    promise: CompiledPromise | None,
    evaluation: RuleEvaluation,
) -> CompiledServiceResponsibility | None:
    if promise is None:
        return None
    if (
        promise.action is not PromiseAction.REPLACEMENT_DISPATCH
        or promise.activation_status is not ActivationStatus.ACTIVE
        or promise.deadline is None
        or promise.next_check_at is None
    ):
        raise ResolutionPlanningError(
            "only active compiled replacement responsibility is plannable"
        )
    receipt = evaluation.accountability_state.service_progress_receipt
    return CompiledServiceResponsibility(
        source_promise_text=promise.raw_text,
        commitment_class=promise.commitment_class.value,
        activation_status=promise.activation_status.value,
        deadline=format_rfc3339_timestamp(promise.deadline),
        next_check_at=format_rfc3339_timestamp(promise.next_check_at),
        recovery_if_missed=receipt.recovery_if_missed if receipt is not None else _DEFAULT_RECOVERY,
    )


def _source_basis(prefix: str, source_ids: tuple[str, ...]) -> list[str]:
    return [f"{prefix}:{source_id}" for source_id in sorted(set(source_ids))]
