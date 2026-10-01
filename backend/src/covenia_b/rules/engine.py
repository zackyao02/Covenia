"""Pure firewall evaluation; no case loading, inference, or response planning.

Callers pass an authoritative AccountabilityState, never a request's compatibility
fields. A P0 selection remains auditable here and cannot become a successful
DecisionResult. Resolution planning and observed metrics are supplied by callers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from covenia_b.domain.types import (
    AccountabilityState,
    ApiEnvelope,
    DecisionResult,
    ErrorPayload,
    FactTrace,
    PreparedAction,
    ResolutionPath,
    RuntimeMetrics,
)
from covenia_b.evidence.aggregation import SCOPE_ORDER, EvidenceAggregation

RULE_VERSION = "deterministic-firewall-v1"
type RuleId = Literal["P0_PROHIBITED_ACTION", "H1", "E1", "E2", "E0_NO_RULE_MATCHED"]
type Decision = Literal["INTERVENE", "ALLOW", "HUMAN_REVIEW"]

# D03/D04: ASK_SAME_EVIDENCE is display-only; no implicit NLP/action-id mapping.
_PROHIBITED_ACTIONS = MappingProxyType(
    {
        "CLOSE_CASE": "CLOSE_BEFORE_RESOLUTION",
        "SHIFT_FOLLOW_UP_TO_CONSUMER": "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "REPEAT_EXPLANATION_REQUEST": "ASK_REPEAT_EXPLANATION",
    }
)


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: RuleId
    priority: int
    decision: Decision
    matches: Callable[[AccountabilityState, PreparedAction, bool | None], bool]


def _p0(state: AccountabilityState, action: PreparedAction, scope_match: bool | None) -> bool:
    prohibition = _PROHIBITED_ACTIONS.get(action.action_type)
    return prohibition is not None and prohibition in state.prohibited_actions


def _h1(state: AccountabilityState, action: PreparedAction, scope_match: bool | None) -> bool:
    return (
        state.evidence_status == "NEED_HUMAN_REVIEW"
        or state.current_scope.issue_type == "ADVERSE_REACTION"
    )


def _e1(state: AccountabilityState, action: PreparedAction, scope_match: bool | None) -> bool:
    return (
        state.evidence_status == "VALID"
        and action.action_type == "ASK_EVIDENCE"
        and scope_match is True
    )


def _e2(state: AccountabilityState, action: PreparedAction, scope_match: bool | None) -> bool:
    return state.evidence_status == "MISMATCHED" and action.action_type == "ASK_EVIDENCE"


_RULES = (
    _Rule("P0_PROHIBITED_ACTION", 400, "INTERVENE", _p0),
    _Rule("H1", 350, "HUMAN_REVIEW", _h1),
    _Rule("E1", 300, "INTERVENE", _e1),
    _Rule("E2", 100, "ALLOW", _e2),
)
_FALLBACK = _Rule("E0_NO_RULE_MATCHED", 0, "ALLOW", lambda state, action, scope_match: True)


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """Internal decision and complete hit trace, including transport-rejected P0."""

    rule_id: RuleId
    rule_priority: int
    decision: Decision
    matched_rule_ids: tuple[RuleId, ...]
    fact_trace: FactTrace
    reason: str
    accountability_state: AccountabilityState
    challenge_mode: bool
    rule_version: str = RULE_VERSION

    @property
    def suppressed_rule_ids(self) -> tuple[str, ...]:
        return tuple(self.fact_trace.suppressed_rule_ids or ())

    @property
    def http_status(self) -> int:
        return 400 if self.rule_id == "P0_PROHIBITED_ACTION" else 200

    def to_decision_result(
        self, *, resolution_path: ResolutionPath, runtime_metrics: RuntimeMetrics
    ) -> DecisionResult:
        """Combine the rule verdict with caller-owned planning and real metrics."""

        if self.rule_id == "P0_PROHIBITED_ACTION":
            raise ProhibitedActionError(self)
        return DecisionResult(
            case_id=self.accountability_state.case_id,
            decision=self.decision,
            rule_id=self.rule_id,
            rule_priority=self.rule_priority,
            accountability_state=self.accountability_state,
            challenge_mode=self.challenge_mode,
            fact_trace=self.fact_trace,
            reason=self.reason,
            resolution_path=resolution_path,
            runtime_metrics=runtime_metrics,
        )

    def require_permitted_action(self) -> None:
        """Raise a transport-neutral prohibition while retaining all audit facts."""

        if self.rule_id == "P0_PROHIBITED_ACTION":
            raise ProhibitedActionError(self)


class ProhibitedActionError(Exception):
    """P0's HTTP mapping; internal evaluation holds any suppressed successful hits."""

    http_status = 400
    code = "P0_PROHIBITED_ACTION"

    def __init__(self, evaluation: RuleEvaluation) -> None:
        if evaluation.rule_id != self.code:
            raise ValueError("ProhibitedActionError requires a P0 evaluation")
        self.evaluation = evaluation
        super().__init__(evaluation.reason)

    def to_error_envelope(self, request_id: str) -> ApiEnvelope:
        return ApiEnvelope(
            data=None,
            error=ErrorPayload(code=self.code, message=str(self), retryable=False),
            request_id=request_id,
        )


def evaluate_decision(
    state: AccountabilityState,
    prepared_action: PreparedAction,
    *,
    challenge_mode: bool = False,
    evidence: EvidenceAggregation | None = None,
) -> RuleEvaluation:
    """Evaluate all candidates, select highest priority, and trace real suppression.

    IDs and narrative content have no decision role. ``evidence`` is optional
    server aggregation detail for explaining E2 component/role/coverage changes;
    it never overrides the authoritative state's evidence status.
    """

    if not isinstance(state, AccountabilityState) or not isinstance(
        prepared_action, PreparedAction
    ):
        raise TypeError("rules require authoritative AccountabilityState and PreparedAction")
    if type(challenge_mode) is not bool:
        raise TypeError("challenge_mode must be a bool")
    if evidence is not None and evidence.evidence_status != state.evidence_status:
        raise ValueError("evidence detail must match the authoritative state")
    requested = prepared_action.requested_scope
    scope_match = (
        all(getattr(state.current_scope, key) == getattr(requested, key) for key in SCOPE_ORDER)
        if requested is not None
        else None
    )
    hits = sorted(
        (rule for rule in _RULES if rule.matches(state, prepared_action, scope_match)),
        key=lambda rule: rule.priority,
        reverse=True,
    )
    selected = hits[0] if hits else _FALLBACK
    trace = FactTrace(
        evidence_status=state.evidence_status,
        prepared_action=prepared_action.action_type,
        scope_match=scope_match,
        active_promise_count=sum(
            commitment.status in ("ACTIVE", "AT_RISK") for commitment in state.active_commitments
        ),
        suppressed_rule_ids=[rule.rule_id for rule in hits[1:]],
    )
    return RuleEvaluation(
        rule_id=selected.rule_id,
        rule_priority=selected.priority,
        decision=selected.decision,
        matched_rule_ids=tuple(rule.rule_id for rule in hits),
        fact_trace=trace,
        reason=_reason(selected.rule_id, state, prepared_action, evidence),
        accountability_state=state,
        challenge_mode=challenge_mode,
    )


def _reason(
    rule_id: RuleId,
    state: AccountabilityState,
    action: PreparedAction,
    evidence: EvidenceAggregation | None,
) -> str:
    if rule_id == "P0_PROHIBITED_ACTION":
        return f"服务端禁止项 {_PROHIBITED_ACTIONS[action.action_type]} 阻止 {action.action_type}。"
    if rule_id == "H1":
        causes = []
        if state.current_scope.issue_type == "ADVERSE_REACTION":
            causes.append("当前问题为 ADVERSE_REACTION")
        if state.evidence_status == "NEED_HUMAN_REVIEW":
            causes.append("证据状态为 NEED_HUMAN_REVIEW")
        return "；".join(causes) + "，需人工复核。"
    if rule_id == "E1":
        return "当前范围证据已 VALID，相同范围的 ASK_EVIDENCE 属于重复索证。"
    if rule_id == "E2":
        changes = (
            [
                key
                for key in SCOPE_ORDER
                if getattr(state.current_scope, key) != getattr(action.requested_scope, key)
            ]
            if action.requested_scope is not None
            else []
        )
        details = [f"请求范围变化字段：{', '.join(changes)}"] if changes else []
        if evidence is not None:
            details.extend(reason.detail for reason in evidence.reasons)
        if not details:
            details.append("服务端判定现有证据与当前范围不匹配（MISMATCHED）")
        return "；".join(details) + "；只补充当前范围缺失的证据。"
    return "当前动作未命中禁止动作、人工复核、重复索证或范围变化规则，允许执行。"
