"""Immutable inputs used by the accountability state builder.

These DTOs represent facts already held by the service layer.  They do not
perform persistence and intentionally have no model or network dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from covenia_b.domain.time import require_aware_datetime
from covenia_b.domain.types import ActiveCommitment, AuditEntry, EvidenceStatus, Scope

Executor = Literal["BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"]
Milestone = Literal["AWAITING_CARRIER_PICKUP", "IN_TRANSIT", "DELIVERED"]
ProgressStatus = Literal["ON_TRACK", "AT_RISK", "COMPLETED"]


@dataclass(frozen=True, slots=True)
class ApprovedResolution:
    """A human/server-approved responsibility that survives re-analysis."""

    deadline: datetime
    next_check_at: datetime
    executor: Executor = "WAREHOUSE"
    recovery_if_missed: str = "品牌将主动催办并通知新的处理时间"
    raw_text: str = "已批准的补发履约责任"
    promise_type: str = "REPLACEMENT_DISPATCH"
    source_ids: tuple[str, ...] = ("human-approval",)

    def __post_init__(self) -> None:
        require_aware_datetime(self.deadline)
        require_aware_datetime(self.next_check_at)
        if not self.recovery_if_missed.strip():
            raise ValueError("recovery_if_missed must not be blank")
        if not self.raw_text.strip():
            raise ValueError("raw_text must not be blank")
        if not self.promise_type.strip():
            raise ValueError("promise_type must not be blank")
        if not self.source_ids or any(not source_id for source_id in self.source_ids):
            raise ValueError("source_ids must not be empty")


@dataclass(frozen=True, slots=True)
class FulfillmentProgress:
    """The latest server-recorded fulfillment milestone and its event time."""

    milestone: Milestone
    status: ProgressStatus
    event_at: datetime
    executor: Executor = "WAREHOUSE"
    receipt_id: str | None = None

    def __post_init__(self) -> None:
        require_aware_datetime(self.event_at)
        if self.receipt_id is not None and not self.receipt_id.strip():
            raise ValueError("receipt_id must not be blank")


@dataclass(frozen=True, slots=True)
class PersistedLedger:
    """Read-only responsibility history supplied to a pure reconstruction.

    ``initialized`` separates the first ledger construction from re-analysis
    of an existing ledger.  The builder never mutates this object.
    """

    initialized: bool = False
    approved_resolution: ApprovedResolution | None = None
    fulfillment_progress: FulfillmentProgress | None = None
    prior_commitments: tuple[ActiveCommitment, ...] = ()
    audit_trail: tuple[AuditEntry, ...] = ()
    latest_update_at: datetime | None = None
    receipt_id: str | None = None
    explanation_received: bool = False
    repeat_contact_count: int = 0

    def __post_init__(self) -> None:
        if self.latest_update_at is not None:
            require_aware_datetime(self.latest_update_at)
        if self.receipt_id is not None and not self.receipt_id.strip():
            raise ValueError("receipt_id must not be blank")
        if self.repeat_contact_count < 0:
            raise ValueError("repeat_contact_count must not be negative")


@dataclass(frozen=True, slots=True)
class ChallengeOverrides:
    """Optional projection changes used only for an isolated challenge snapshot."""

    current_scope: Scope | None = None
    evidence_status: EvidenceStatus | None = None
