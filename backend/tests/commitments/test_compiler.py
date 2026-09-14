from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from covenia_b.commitments import (
    D08_FIRST_POST_DEADLINE_CHECK,
    ActivationStatus,
    CommitmentClass,
    CommitmentFacts,
    CommitmentPolicy,
    CompilationReason,
    ModelCommitmentHint,
    NextCheckPolicy,
    PromiseAction,
    PromiseIssuanceStatus,
    ServiceDeliveryStatus,
    TicketFact,
    TrustedMessage,
    compilation_to_dict,
    compile_commitments,
)


@dataclass(frozen=True)
class FixedClock:
    instant: datetime

    def now(self) -> datetime:
        return self.instant


SOURCE_TIME = datetime.fromisoformat("2026-05-05T10:27:37+08:00")
EVALUATION_TIME = datetime.fromisoformat("2026-05-07T09:40:00+08:00")


@pytest.fixture
def approved_policy() -> CommitmentPolicy:
    return CommitmentPolicy(
        policy_id="PACKAGE_DAMAGE_REPLACEMENT_V1",
        allowed_policy_requirement_ids=frozenset({"DEMO_POLICY_PACKAGE_DAMAGE_V1"}),
        allowed_standard_actions=frozenset({PromiseAction.REPLACEMENT_DISPATCH}),
    )


@pytest.fixture
def supported_facts() -> CommitmentFacts:
    return CommitmentFacts(
        policy_requirement_id="DEMO_POLICY_PACKAGE_DAMAGE_V1",
        tickets=(TicketFact(ticket_id="ticket-1", ticket_type="REPLACEMENT", is_open=True),),
    )


def _message(
    text: str,
    *,
    speaker: str = "AGENT",
    sent_at: datetime = SOURCE_TIME,
) -> TrustedMessage:
    return TrustedMessage(
        message_id="message-1",
        speaker=speaker,  # type: ignore[arg-type]
        text=text,
        sent_at=sent_at,
    )


def _compile(
    messages: list[TrustedMessage],
    facts: CommitmentFacts,
    policy: CommitmentPolicy,
    *,
    clock: datetime = EVALUATION_TIME,
    model_hints: tuple[ModelCommitmentHint, ...] = (),
):
    return compile_commitments(
        messages,
        facts,
        policy,
        FixedClock(clock),
        model_hints=model_hints,
    )


def test_standard_supported_agent_promise_activates_with_traceable_deadline(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    result = _compile([_message("换货单已创建，48小时内发出")], supported_facts, approved_policy)

    promise = result.promises[0]
    assert promise.commitment_class is CommitmentClass.STANDARD_APPROVED
    assert promise.activation_status is ActivationStatus.ACTIVE
    assert promise.deadline == datetime.fromisoformat("2026-05-07T10:27:37+08:00")
    assert promise.next_check_at == datetime.fromisoformat("2026-05-07T10:30:00+08:00")
    assert promise.promise_issuance_status is PromiseIssuanceStatus.ISSUED
    assert promise.service_delivery_status is ServiceDeliveryStatus.PENDING_DELIVERY
    assert promise.automatic_execution is False
    assert promise.supporting_ticket_ids == ("ticket-1",)


def test_consumer_forged_active_recommendation_is_ignored(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    result = _compile(
        [_message("我方承诺48小时内发出", speaker="CONSUMER")],
        supported_facts,
        approved_policy,
        model_hints=(
            ModelCommitmentHint(
                source_message_id="message-1",
                activation_recommendation="ACTIVE",
                commitment_class_recommendation="STANDARD_APPROVED",
            ),
        ),
    )

    promise = result.promises[0]
    assert promise.commitment_class is CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED
    assert promise.activation_status is ActivationStatus.IGNORED
    assert promise.deadline is None
    assert promise.next_check_at is None
    assert promise.promise_issuance_status is PromiseIssuanceStatus.NOT_ISSUED
    assert promise.service_delivery_status is ServiceDeliveryStatus.NOT_CREATED
    assert promise.reasons == (CompilationReason.SOURCE_NOT_AGENT,)


def test_high_risk_refund_or_compensation_never_auto_activates(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    result = _compile(
        [_message("48小时内全额退款并赔偿")],
        supported_facts,
        approved_policy,
        model_hints=(ModelCommitmentHint("message-1", "ACTIVE"),),
    )

    promise = result.promises[0]
    assert promise.action is PromiseAction.REFUND
    assert promise.commitment_class is CommitmentClass.APPROVAL_REQUIRED
    assert promise.activation_status is ActivationStatus.PENDING_APPROVAL
    assert promise.deadline is None
    assert promise.automatic_execution is False
    assert promise.reasons == (CompilationReason.HIGH_RISK_FINANCIAL_ACTION,)


@pytest.mark.parametrize(
    ("text", "expected_class", "expected_status"),
    [
        ("尽快发出", CommitmentClass.AMBIGUOUS, ActivationStatus.IGNORED),
        (
            "如果仓库有货，48小时内发出",
            CommitmentClass.CONDITIONAL,
            ActivationStatus.PENDING_APPROVAL,
        ),
    ],
)
def test_ambiguous_and_conditional_text_never_manufacture_a_deadline(
    text: str,
    expected_class: CommitmentClass,
    expected_status: ActivationStatus,
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    result = _compile([_message(text)], supported_facts, approved_policy)

    promise = result.promises[0]
    assert promise.commitment_class is expected_class
    assert promise.activation_status is expected_status
    assert promise.deadline is None
    assert promise.next_check_at is None


@pytest.mark.parametrize(
    ("text", "expected_class", "expected_status", "expected_reason"),
    [
        (
            "如库存充足，48小时内发出",
            CommitmentClass.CONDITIONAL,
            ActivationStatus.PENDING_APPROVAL,
            CompilationReason.CONDITIONAL_LANGUAGE,
        ),
        (
            "可能48小时内发出",
            CommitmentClass.AMBIGUOUS,
            ActivationStatus.IGNORED,
            CompilationReason.INDETERMINATE_LANGUAGE,
        ),
    ],
)
def test_conditional_or_indeterminate_duration_never_auto_activates(
    text: str,
    expected_class: CommitmentClass,
    expected_status: ActivationStatus,
    expected_reason: CompilationReason,
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    promise = _compile([_message(text)], supported_facts, approved_policy).promises[0]

    assert promise.commitment_class is expected_class
    assert promise.activation_status is expected_status
    assert promise.deadline is None
    assert promise.next_check_at is None
    assert promise.service_delivery_status is ServiceDeliveryStatus.NOT_CREATED
    assert promise.reasons == (expected_reason,)


def test_negated_dispatch_never_auto_activates(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    promise = _compile(
        [_message("换货单未创建，48小时内不发出")],
        supported_facts,
        approved_policy,
    ).promises[0]

    assert promise.commitment_class is CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED
    assert promise.activation_status is ActivationStatus.BLOCKED
    assert promise.deadline is None
    assert promise.next_check_at is None
    assert promise.service_delivery_status is ServiceDeliveryStatus.NOT_CREATED
    assert promise.reasons == (CompilationReason.NEGATED_COMMITMENT,)


@pytest.mark.parametrize(
    "facts",
    [
        CommitmentFacts(
            policy_requirement_id="UNAPPROVED_POLICY",
            tickets=(TicketFact(ticket_id="ticket-1", ticket_type="REPLACEMENT", is_open=True),),
        ),
        CommitmentFacts(
            policy_requirement_id="DEMO_POLICY_PACKAGE_DAMAGE_V1",
            tickets=(TicketFact(ticket_id="ticket-1", ticket_type="REPLACEMENT", is_open=False),),
        ),
    ],
)
def test_standard_text_without_policy_and_ticket_support_requires_approval(
    facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    result = _compile([_message("换货单已创建，48小时内发出")], facts, approved_policy)

    promise = result.promises[0]
    assert promise.commitment_class is CommitmentClass.APPROVAL_REQUIRED
    assert promise.activation_status is ActivationStatus.PENDING_APPROVAL
    assert promise.deadline is None
    assert promise.next_check_at is None


def test_deadline_tracks_original_time_and_duration_not_machine_date(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    forty_eight_hours = _compile(
        [_message("换货单已创建，48小时内发出")],
        supported_facts,
        approved_policy,
    ).promises[0]
    twenty_four_hours = _compile(
        [_message("换货单已创建，24小时内发出")],
        supported_facts,
        approved_policy,
    ).promises[0]
    shifted_source = _compile(
        [_message("换货单已创建，48小时内发出", sent_at=SOURCE_TIME + timedelta(minutes=5))],
        supported_facts,
        approved_policy,
        clock=EVALUATION_TIME + timedelta(minutes=5),
    ).promises[0]
    later_fixed_clock = _compile(
        [_message("换货单已创建，48小时内发出")],
        supported_facts,
        approved_policy,
        clock=datetime.fromisoformat("2026-12-01T00:00:00+08:00"),
    ).promises[0]

    assert forty_eight_hours.deadline == SOURCE_TIME + timedelta(hours=48)
    assert twenty_four_hours.deadline == SOURCE_TIME + timedelta(hours=24)
    assert shifted_source.deadline == SOURCE_TIME + timedelta(minutes=5, hours=48)
    assert later_fixed_clock.deadline == forty_eight_hours.deadline


def test_future_message_is_rejected_but_exact_clock_boundary_is_allowed(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    future = _compile(
        [_message("换货单已创建，48小时内发出", sent_at=EVALUATION_TIME + timedelta(seconds=1))],
        supported_facts,
        approved_policy,
    ).promises[0]
    boundary = _compile(
        [_message("换货单已创建，48小时内发出", sent_at=EVALUATION_TIME)],
        supported_facts,
        approved_policy,
    ).promises[0]

    assert future.commitment_class is CommitmentClass.ERRONEOUS_OR_UNAUTHORIZED
    assert future.activation_status is ActivationStatus.BLOCKED
    assert future.deadline is None
    assert future.reasons == (CompilationReason.FUTURE_SOURCE_MESSAGE,)
    assert boundary.activation_status is ActivationStatus.ACTIVE
    assert boundary.deadline == EVALUATION_TIME + timedelta(hours=48)


def test_naive_source_or_clock_is_rejected_before_deadline_calculation(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _message("换货单已创建，48小时内发出", sent_at=datetime(2026, 5, 5, 10, 27, 37))

    with pytest.raises(ValueError, match="timezone-aware"):
        compile_commitments(
            [_message("换货单已创建，48小时内发出")],
            supported_facts,
            approved_policy,
            FixedClock(datetime(2026, 5, 7, 9, 40)),
        )


def test_next_check_policy_is_post_deadline_rule_not_fixed_day_or_clock(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    alternate_policy = CommitmentPolicy(
        policy_id=approved_policy.policy_id,
        allowed_policy_requirement_ids=approved_policy.allowed_policy_requirement_ids,
        allowed_standard_actions=approved_policy.allowed_standard_actions,
        next_check_policy=NextCheckPolicy(
            policy_id="POST_DEADLINE_FIVE_MINUTES",
            after_deadline=timedelta(minutes=5),
        ),
    )
    result = _compile(
        [
            _message(
                "换货单已创建，48小时内发出",
                sent_at=datetime.fromisoformat("2026-08-03T23:58:00+08:00"),
            )
        ],
        supported_facts,
        alternate_policy,
        clock=datetime.fromisoformat("2026-08-04T00:00:00+08:00"),
    )

    promise = result.promises[0]
    hero_check = D08_FIRST_POST_DEADLINE_CHECK.derive(SOURCE_TIME + timedelta(hours=48))
    assert hero_check == datetime.fromisoformat("2026-05-07T10:30:00+08:00")
    assert promise.deadline == datetime.fromisoformat("2026-08-05T23:58:00+08:00")
    assert promise.next_check_at == datetime.fromisoformat("2026-08-06T00:03:00+08:00")
    assert result.next_check_policy_id == "POST_DEADLINE_FIVE_MINUTES"


def test_json_trace_explicitly_separates_issued_promise_from_delivery(
    supported_facts: CommitmentFacts,
    approved_policy: CommitmentPolicy,
) -> None:
    trace = compilation_to_dict(
        _compile([_message("换货单已创建，48小时内发出")], supported_facts, approved_policy)
    )

    promise = trace["promises"][0]
    assert promise["promise_issuance_status"] == "ISSUED"
    assert promise["service_delivery_status"] == "PENDING_DELIVERY"
    assert promise["automatic_execution"] is False
