"""Pure compilation of authorized customer-service commitments.

This module performs no HTTP calls, persistence, model inference, notification,
or fulfillment operation.  It only derives a traceable responsibility from an
original agent message, trusted work-order facts, and an approved policy.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from covenia_b.commitments.models import (
    ActivationStatus,
    CommitmentClass,
    CommitmentCompilation,
    CommitmentFacts,
    CommitmentPolicy,
    CompilationReason,
    CompiledPromise,
    ModelCommitmentHint,
    PromiseAction,
    PromiseIssuanceStatus,
    ServiceDeliveryStatus,
    TicketFact,
    TrustedMessage,
)
from covenia_b.domain.types import CaseInput


class TrustedClock(Protocol):
    """The minimal trusted-clock surface needed by the pure compiler."""

    def now(self) -> datetime: ...


_HOUR_PATTERNS = (
    re.compile(r"(?P<hours>[1-9][0-9]*)\s*(?:个)?小时(?:内)?"),
    re.compile(r"(?:within\s+)?(?P<hours>[1-9][0-9]*)\s*hours?(?:\s+within)?", re.IGNORECASE),
)
_AMBIGUOUS_MARKERS = ("尽快", "第一时间", "尽早", "稍后", "有结果", "尽量")
_CONDITIONAL_MARKERS = ("如果", "若", "视情况", "视库存", "满足条件", "待审核")
_REFUND_MARKERS = ("退款", "返款")
_COMPENSATION_MARKERS = ("赔偿", "补偿")
_REPLACEMENT_MARKERS = ("换货", "补发", "发出", "寄出")
_CONDITIONAL_PATTERNS = (
    re.compile(r"(?:如果|如若|若|倘若|假如|一旦|除非|只有|前提是|取决于)"),
    re.compile(r"(?:视(?:情况|库存|审核|结果)|待(?:审核|确认))"),
    re.compile(r"如(?!期)"),
)
_INDETERMINATE_PATTERNS = (
    re.compile(r"(?:可能|也许|或许|大概|大约|预计|估计|大致|差不多|左右|应该|未必|不确定|待定)"),
)
_NEGATED_REPLACEMENT_PATTERNS = (
    re.compile(r"(?:不|未|无|没有|无法|不能|不会|尚未|暂不|未能).{0,12}?(?:换货|补发|发出|寄出)"),
    re.compile(r"(?:换货|补发|发出|寄出).{0,8}?(?:不了|不能|不可以|未能|失败)"),
)


def compile_commitments(
    messages: Iterable[TrustedMessage],
    facts: CommitmentFacts,
    policy: CommitmentPolicy,
    clock: TrustedClock,
    *,
    model_hints: Sequence[ModelCommitmentHint] = (),
) -> CommitmentCompilation:
    """Compile only source-grounded promises from a trusted transcript.

    ``model_hints`` is intentionally discarded before any decision.  A caller
    may retain an AI ``activation_recommendation`` for audit, but it can never
    make a consumer message or high-risk request active.
    """

    del model_hints
    compiled_at = _trusted_now(clock)
    candidates = tuple(message for message in messages if _looks_like_promise(message.text))
    promises = tuple(
        _compile_message(
            message=message,
            facts=facts,
            policy=policy,
            compiled_at=compiled_at,
        )
        for message in candidates
    )
    return CommitmentCompilation(
        compiled_at=compiled_at,
        policy_id=policy.policy_id,
        next_check_policy_id=policy.next_check_policy.policy_id,
        promises=promises,
    )


def compile_case_input(
    case_input: CaseInput,
    policy: CommitmentPolicy,
    clock: TrustedClock,
    *,
    model_hints: Sequence[ModelCommitmentHint] = (),
) -> CommitmentCompilation:
    """Adapt BATCH-04's trusted ``CaseInput`` into the pure compiler boundary."""

    messages = tuple(
        TrustedMessage(
            message_id=message.message_id,
            speaker=message.speaker,
            text=message.text,
            sent_at=_parse_rfc3339(message.timestamp),
        )
        for message in case_input.conversation
    )
    facts = CommitmentFacts(
        policy_requirement_id=case_input.policy_requirement_id,
        tickets=tuple(
            TicketFact(
                ticket_id=ticket.ticket_id,
                ticket_type=ticket.ticket_type,
                is_open=ticket.completed_at is None,
            )
            for ticket in case_input.service_tickets
        ),
    )
    return compile_commitments(messages, facts, policy, clock, model_hints=model_hints)


def compilation_to_dict(compilation: CommitmentCompilation) -> dict[str, object]:
    """Return a JSON-ready trace without changing any service or ticket state."""

    return {
        "compiled_at": _format_timestamp(compilation.compiled_at),
        "policy_id": compilation.policy_id,
        "next_check_policy_id": compilation.next_check_policy_id,
        "promises": [
            {
                "source_message_id": promise.source_message_id,
                "raw_text": promise.raw_text,
                "action": promise.action.value,
                "commitment_class": promise.commitment_class.value,
                "activation_status": promise.activation_status.value,
                "deadline": _format_optional_timestamp(promise.deadline),
                "next_check_at": _format_optional_timestamp(promise.next_check_at),
                "promise_issuance_status": promise.promise_issuance_status.value,
                "service_delivery_status": promise.service_delivery_status.value,
                "policy_id": promise.policy_id,
                "supporting_ticket_ids": list(promise.supporting_ticket_ids),
                "reasons": [reason.value for reason in promise.reasons],
                "automatic_execution": promise.automatic_execution,
            }
            for promise in compilation.promises
        ],
    }


def _compile_message(
    *,
    message: TrustedMessage,
    facts: CommitmentFacts,
    policy: CommitmentPolicy,
    compiled_at: datetime,
) -> CompiledPromise:
    action = _action_from_text(message.text)
    issued = (
        PromiseIssuanceStatus.ISSUED
        if message.speaker == "AGENT" and message.sent_at <= compiled_at
        else PromiseIssuanceStatus.NOT_ISSUED
    )

    if message.speaker != "AGENT":
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED,
            activation_status=ActivationStatus.IGNORED,
            issuance_status=issued,
            reasons=(CompilationReason.SOURCE_NOT_AGENT,),
        )
    if message.sent_at > compiled_at:
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED,
            activation_status=ActivationStatus.BLOCKED,
            issuance_status=issued,
            reasons=(CompilationReason.FUTURE_SOURCE_MESSAGE,),
        )
    if action in {PromiseAction.REFUND, PromiseAction.COMPENSATION}:
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.APPROVAL_REQUIRED,
            activation_status=ActivationStatus.PENDING_APPROVAL,
            issuance_status=issued,
            reasons=(CompilationReason.HIGH_RISK_FINANCIAL_ACTION,),
        )
    if _has_conditional_language(message.text):
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.CONDITIONAL,
            activation_status=ActivationStatus.PENDING_APPROVAL,
            issuance_status=issued,
            reasons=(CompilationReason.CONDITIONAL_LANGUAGE,),
        )
    if _has_negated_replacement_action(message.text):
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED,
            activation_status=ActivationStatus.BLOCKED,
            issuance_status=issued,
            reasons=(CompilationReason.NEGATED_COMMITMENT,),
        )
    duration = _duration_from_text(message.text)
    if _has_indeterminate_language(message.text) or duration is None:
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.AMBIGUOUS,
            activation_status=ActivationStatus.IGNORED,
            issuance_status=issued,
            reasons=(
                CompilationReason.INDETERMINATE_LANGUAGE
                if _has_indeterminate_language(message.text)
                else CompilationReason.AMBIGUOUS_TIME_EXPRESSION,
            ),
        )
    if action is not PromiseAction.REPLACEMENT_DISPATCH:
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED,
            activation_status=ActivationStatus.BLOCKED,
            issuance_status=issued,
            reasons=(CompilationReason.UNSUPPORTED_ACTION,),
        )

    support_ticket_ids = _open_supporting_ticket_ids(facts, policy)
    missing_reasons: list[CompilationReason] = []
    if not policy.supports(facts, action):
        missing_reasons.append(CompilationReason.POLICY_NOT_APPROVED)
    if not support_ticket_ids:
        missing_reasons.append(CompilationReason.MISSING_OPEN_TICKET)
    if missing_reasons:
        return _non_active(
            message,
            action=action,
            commitment_class=CommitmentClass.APPROVAL_REQUIRED,
            activation_status=ActivationStatus.PENDING_APPROVAL,
            issuance_status=issued,
            supporting_ticket_ids=support_ticket_ids,
            reasons=tuple(missing_reasons),
        )

    deadline = message.sent_at + duration
    return CompiledPromise(
        source_message_id=message.message_id,
        raw_text=message.text,
        action=action,
        commitment_class=CommitmentClass.STANDARD_APPROVED,
        activation_status=ActivationStatus.ACTIVE,
        deadline=deadline,
        next_check_at=policy.next_check_policy.derive(deadline),
        promise_issuance_status=issued,
        service_delivery_status=ServiceDeliveryStatus.PENDING_DELIVERY,
        policy_id=policy.policy_id,
        supporting_ticket_ids=support_ticket_ids,
        reasons=(CompilationReason.AUTHORIZED_STANDARD,),
    )


def _non_active(
    message: TrustedMessage,
    *,
    action: PromiseAction,
    commitment_class: CommitmentClass,
    activation_status: ActivationStatus,
    issuance_status: PromiseIssuanceStatus,
    reasons: tuple[CompilationReason, ...],
    supporting_ticket_ids: tuple[str, ...] = (),
) -> CompiledPromise:
    return CompiledPromise(
        source_message_id=message.message_id,
        raw_text=message.text,
        action=action,
        commitment_class=commitment_class,
        activation_status=activation_status,
        deadline=None,
        next_check_at=None,
        promise_issuance_status=issuance_status,
        service_delivery_status=ServiceDeliveryStatus.NOT_CREATED,
        policy_id=None,
        supporting_ticket_ids=supporting_ticket_ids,
        reasons=reasons,
    )


def _looks_like_promise(text: str) -> bool:
    markers = (
        *_AMBIGUOUS_MARKERS,
        *_CONDITIONAL_MARKERS,
        *_REFUND_MARKERS,
        *_COMPENSATION_MARKERS,
        *_REPLACEMENT_MARKERS,
    )
    return _duration_from_text(text) is not None or _contains_any(text, markers)


def _action_from_text(text: str) -> PromiseAction:
    if _contains_any(text, _REFUND_MARKERS):
        return PromiseAction.REFUND
    if _contains_any(text, _COMPENSATION_MARKERS):
        return PromiseAction.COMPENSATION
    if _contains_any(text, _REPLACEMENT_MARKERS):
        return PromiseAction.REPLACEMENT_DISPATCH
    return PromiseAction.UNKNOWN


def _duration_from_text(text: str) -> timedelta | None:
    for pattern in _HOUR_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return timedelta(hours=int(match["hours"]))
    return None


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    return any(marker in text for marker in markers)


def _matches_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)


def _has_conditional_language(text: str) -> bool:
    return _contains_any(text, _CONDITIONAL_MARKERS) or _matches_any(text, _CONDITIONAL_PATTERNS)


def _has_indeterminate_language(text: str) -> bool:
    return _contains_any(text, _AMBIGUOUS_MARKERS) or _matches_any(text, _INDETERMINATE_PATTERNS)


def _has_negated_replacement_action(text: str) -> bool:
    return _matches_any(text, _NEGATED_REPLACEMENT_PATTERNS)


def _open_supporting_ticket_ids(
    facts: CommitmentFacts,
    policy: CommitmentPolicy,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            ticket.ticket_id
            for ticket in facts.tickets
            if ticket.ticket_type == policy.required_ticket_type and ticket.is_open
        )
    )


def _trusted_now(clock: TrustedClock) -> datetime:
    now = clock.now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock.now() must return a timezone-aware datetime")
    return now


def _parse_rfc3339(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CaseInput timestamps must be timezone-aware")
    return parsed


def _format_timestamp(value: datetime) -> str:
    rendered = value.isoformat()
    return rendered.replace("+00:00", "Z") if value.utcoffset() == timedelta(0) else rendered


def _format_optional_timestamp(value: datetime | None) -> str | None:
    return _format_timestamp(value) if value is not None else None
