"""Trusted inputs and immutable outputs for commitment compilation.

The types in this module deliberately keep a customer-service promise separate
from an actual fulfillment operation.  Compilation records an already-issued
agent message and, when authorized, a pending service responsibility; it never
dispatches a replacement, refund, or compensation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal


class CommitmentClass(StrEnum):
    """The five approved classifications for a candidate promise."""

    STANDARD_APPROVED = "STANDARD_APPROVED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    CONDITIONAL = "CONDITIONAL"
    ERRONEOUS_OR_UNAUTHORIZED = "ERRONEOUS_OR_UNAUTHORIZED"
    AMBIGUOUS = "AMBIGUOUS"


class ActivationStatus(StrEnum):
    """Server-owned activation states; model recommendations cannot set these."""

    ACTIVE = "ACTIVE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    BLOCKED = "BLOCKED"
    IGNORED = "IGNORED"


class PromiseAction(StrEnum):
    """Bounded actions that can be recognized from the trusted original text."""

    REPLACEMENT_DISPATCH = "REPLACEMENT_DISPATCH"
    REFUND = "REFUND"
    COMPENSATION = "COMPENSATION"
    UNKNOWN = "UNKNOWN"


class PromiseIssuanceStatus(StrEnum):
    """Whether an original agent message was already sent to the consumer."""

    ISSUED = "ISSUED"
    NOT_ISSUED = "NOT_ISSUED"


class ServiceDeliveryStatus(StrEnum):
    """The service state, deliberately distinct from issuing a promise."""

    PENDING_DELIVERY = "PENDING_DELIVERY"
    NOT_CREATED = "NOT_CREATED"


class CompilationReason(StrEnum):
    """Traceable, server-determined reasons for a compilation outcome."""

    AUTHORIZED_STANDARD = "AUTHORIZED_STANDARD"
    SOURCE_NOT_AGENT = "SOURCE_NOT_AGENT"
    FUTURE_SOURCE_MESSAGE = "FUTURE_SOURCE_MESSAGE"
    HIGH_RISK_FINANCIAL_ACTION = "HIGH_RISK_FINANCIAL_ACTION"
    CONDITIONAL_LANGUAGE = "CONDITIONAL_LANGUAGE"
    INDETERMINATE_LANGUAGE = "INDETERMINATE_LANGUAGE"
    NEGATED_COMMITMENT = "NEGATED_COMMITMENT"
    AMBIGUOUS_TIME_EXPRESSION = "AMBIGUOUS_TIME_EXPRESSION"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    POLICY_NOT_APPROVED = "POLICY_NOT_APPROVED"
    MISSING_OPEN_TICKET = "MISSING_OPEN_TICKET"


Speaker = Literal["AGENT", "CONSUMER", "SYSTEM"]


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TrustedMessage:
    """An immutable message from the authoritative conversation transcript."""

    message_id: str
    speaker: Speaker
    text: str
    sent_at: datetime

    def __post_init__(self) -> None:
        if not self.message_id:
            raise ValueError("message_id must not be empty")
        if self.speaker not in {"AGENT", "CONSUMER", "SYSTEM"}:
            raise ValueError("speaker must be AGENT, CONSUMER, or SYSTEM")
        if not self.text.strip():
            raise ValueError("text must not be blank")
        _require_aware(self.sent_at, field="sent_at")


@dataclass(frozen=True, slots=True)
class TicketFact:
    """A trusted work-order fact, not a model inference."""

    ticket_id: str
    ticket_type: str
    is_open: bool

    def __post_init__(self) -> None:
        if not self.ticket_id:
            raise ValueError("ticket_id must not be empty")
        if not self.ticket_type:
            raise ValueError("ticket_type must not be empty")


@dataclass(frozen=True, slots=True)
class CommitmentFacts:
    """The case facts that may authorize a standard service commitment."""

    policy_requirement_id: str
    tickets: tuple[TicketFact, ...]

    def __post_init__(self) -> None:
        if not self.policy_requirement_id:
            raise ValueError("policy_requirement_id must not be empty")


@dataclass(frozen=True, slots=True)
class NextCheckPolicy:
    """An approved rule for deriving a check from a deadline, never a wall clock."""

    policy_id: str
    after_deadline: timedelta

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must not be empty")
        if self.after_deadline <= timedelta(0):
            raise ValueError("after_deadline must be strictly positive")

    def derive(self, deadline: datetime) -> datetime:
        _require_aware(deadline, field="deadline")
        return deadline + self.after_deadline


# D08 keeps the Hero's 10:30 check by deriving it from 10:27:37 plus 2m23s.
# The rule intentionally contains no date, case identifier, or fixed clock time.
D08_FIRST_POST_DEADLINE_CHECK = NextCheckPolicy(
    policy_id="D08_FIRST_POST_DEADLINE_CHECK_V1",
    after_deadline=timedelta(minutes=2, seconds=23),
)


@dataclass(frozen=True, slots=True)
class CommitmentPolicy:
    """A product-approved policy fact used to authorize standard commitments."""

    policy_id: str
    allowed_policy_requirement_ids: frozenset[str]
    allowed_standard_actions: frozenset[PromiseAction]
    required_ticket_type: str = "REPLACEMENT"
    next_check_policy: NextCheckPolicy = D08_FIRST_POST_DEADLINE_CHECK

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("policy_id must not be empty")
        if not self.allowed_policy_requirement_ids:
            raise ValueError("allowed_policy_requirement_ids must not be empty")
        if not self.allowed_standard_actions:
            raise ValueError("allowed_standard_actions must not be empty")
        if not self.required_ticket_type:
            raise ValueError("required_ticket_type must not be empty")

    def supports(self, facts: CommitmentFacts, action: PromiseAction) -> bool:
        return (
            facts.policy_requirement_id in self.allowed_policy_requirement_ids
            and action in self.allowed_standard_actions
        )


@dataclass(frozen=True, slots=True)
class ModelCommitmentHint:
    """Untrusted model metadata retained at the boundary but never consulted.

    Passing a hint to ``compile_commitments`` proves an integration caller may
    retain its candidate data without granting it authority over classification,
    activation, or a deadline.
    """

    source_message_id: str
    activation_recommendation: str
    commitment_class_recommendation: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledPromise:
    """A server-owned, traceable result with no side effect on fulfillment."""

    source_message_id: str
    raw_text: str
    action: PromiseAction
    commitment_class: CommitmentClass
    activation_status: ActivationStatus
    deadline: datetime | None
    next_check_at: datetime | None
    promise_issuance_status: PromiseIssuanceStatus
    service_delivery_status: ServiceDeliveryStatus
    policy_id: str | None
    supporting_ticket_ids: tuple[str, ...]
    reasons: tuple[CompilationReason, ...]
    automatic_execution: Literal[False] = False

    def __post_init__(self) -> None:
        if self.automatic_execution is not False:
            raise ValueError("commitment compilation must not trigger automatic execution")
        if self.deadline is not None:
            _require_aware(self.deadline, field="deadline")
        if self.next_check_at is not None:
            _require_aware(self.next_check_at, field="next_check_at")
        if (self.deadline is None) != (self.next_check_at is None):
            raise ValueError("deadline and next_check_at must be both present or both absent")
        if self.activation_status is ActivationStatus.ACTIVE:
            if self.deadline is None:
                raise ValueError("ACTIVE commitments require a deadline")
            if self.service_delivery_status is not ServiceDeliveryStatus.PENDING_DELIVERY:
                raise ValueError("ACTIVE commitments must remain pending delivery")
        elif self.deadline is not None:
            raise ValueError("non-ACTIVE commitments cannot produce a deterministic deadline")


@dataclass(frozen=True, slots=True)
class CommitmentCompilation:
    """A deterministic batch of commitments derived at one trusted clock instant."""

    compiled_at: datetime
    policy_id: str
    next_check_policy_id: str
    promises: tuple[CompiledPromise, ...]

    def __post_init__(self) -> None:
        _require_aware(self.compiled_at, field="compiled_at")
