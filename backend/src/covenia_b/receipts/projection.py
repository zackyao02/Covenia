"""Project responsibility-ledger progress without sending notifications.

This module has no HTTP, persistence, or delivery dependency.  It creates a
consumer-safe receipt and, while progress remains open, an internal draft that
must be confirmed by a human in the approved consumer surface.  The caller is
responsible for retaining any local confirmation record; this module never
claims that a notification has been sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal


class ProgressStatus(StrEnum):
    """The receipt states approved for responsibility-progress projections."""

    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    COMPLETED = "COMPLETED"


class NotificationState(StrEnum):
    """Internal state only; neither value represents an external send."""

    INTERNAL_PENDING_HUMAN_APPROVAL = "INTERNAL_PENDING_HUMAN_APPROVAL"


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _format_instant(value: datetime) -> str:
    """Use one stable RFC 3339-compatible rendering in fields and text."""

    return value.isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ProgressLedger:
    """Trusted, server-owned ledger facts required to make a projection.

    ``next_check_at`` is the sole future-update source.  A completed ledger
    deliberately has no such source: completion is terminal, not a promise of
    another update.  ``internal_note`` is accepted as ledger context but is
    intentionally absent from every consumer projection.
    """

    receipt_id: str
    status: ProgressStatus
    received_evidence: tuple[str, ...]
    brand_action: str
    latest_update_at: datetime
    next_check_at: datetime | None
    recovery_if_missed: str
    internal_note: str | None = None

    def __post_init__(self) -> None:
        if not self.receipt_id:
            raise ValueError("receipt_id must not be empty")
        if not self.brand_action.strip():
            raise ValueError("brand_action must not be blank")
        if not self.recovery_if_missed.strip():
            raise ValueError("recovery_if_missed must not be blank")
        _require_aware(self.latest_update_at, field="latest_update_at")

        if self.status is ProgressStatus.COMPLETED:
            if self.next_check_at is not None:
                raise ValueError("COMPLETED progress must not schedule a future next_check_at")
            return

        if self.next_check_at is None:
            raise ValueError("open progress requires next_check_at")
        _require_aware(self.next_check_at, field="next_check_at")
        if self.next_check_at <= self.latest_update_at:
            raise ValueError("next_check_at must be later than latest_update_at for open progress")


@dataclass(frozen=True, slots=True)
class ReceiptProjection:
    """Receipt data plus an internal scheduled/terminal validation marker."""

    receipt_id: str
    status: ProgressStatus
    received_evidence: tuple[str, ...]
    brand_action: str
    latest_update_at: datetime
    next_update_by: datetime | None
    next_update_state: Literal["SCHEDULED", "TERMINAL"]
    consumer_action_required: Literal[False]
    recovery_if_missed: str

    def consumer_view(self) -> dict[str, object]:
        """Return only fields intended for a consumer-visible receipt."""

        return {
            "receipt_id": self.receipt_id,
            "status": self.status.value,
            "received_evidence": list(self.received_evidence),
            "brand_action": self.brand_action,
            "latest_update_at": _format_instant(self.latest_update_at),
            "next_update_by": (
                _format_instant(self.next_update_by) if self.next_update_by is not None else None
            ),
            "consumer_action_required": self.consumer_action_required,
            "recovery_if_missed": self.recovery_if_missed,
        }


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    """An internal draft, never a sent notification or delivery command."""

    text: str
    commits_next_update_at: datetime
    requires_human_approval: Literal[True] = True
    state: NotificationState = NotificationState.INTERNAL_PENDING_HUMAN_APPROVAL
    is_sent: Literal[False] = False
    channel: Literal["ORIGINAL_CHAT"] = "ORIGINAL_CHAT"

    def __post_init__(self) -> None:
        _require_aware(self.commits_next_update_at, field="commits_next_update_at")
        if self.requires_human_approval is not True:
            raise ValueError("notification drafts always require human approval")
        if self.is_sent is not False:
            raise ValueError("a projection cannot represent a sent notification")
        if _format_instant(self.commits_next_update_at) not in self.text:
            raise ValueError("notification text must contain commits_next_update_at")


@dataclass(frozen=True, slots=True)
class ProgressProjection:
    """The complete pure output; draft content is not part of ``consumer_view``."""

    next_check_at: datetime | None
    receipt: ReceiptProjection
    proactive_notification_draft: NotificationDraft | None

    def validate(self) -> None:
        """Enforce the one-source-of-time and no-unconfirmed-send invariants."""

        expected_state: Literal["SCHEDULED", "TERMINAL"] = (
            "TERMINAL"
            if self.receipt.status is ProgressStatus.COMPLETED
            else "SCHEDULED"
        )
        if self.receipt.next_update_state != expected_state:
            raise ValueError(
                "internal next_update_state must match the receipt progress status"
            )

        if self.receipt.next_update_state == "TERMINAL":
            if self.next_check_at is not None or self.receipt.next_update_by is not None:
                raise ValueError("terminal receipt must not expose a future next update")
            if self.proactive_notification_draft is not None:
                raise ValueError("terminal receipt must not create a notification draft")
            return

        if self.next_check_at is None or self.receipt.next_update_by is None:
            raise ValueError("scheduled receipt requires a next-update instant")
        if self.receipt.next_update_by != self.next_check_at:
            raise ValueError("receipt next_update_by must equal next_check_at")
        draft = self.proactive_notification_draft
        if draft is None:
            raise ValueError("scheduled receipt requires an internal notification draft")
        if draft.commits_next_update_at != self.next_check_at:
            raise ValueError("draft commits_next_update_at must equal next_check_at")
        if draft.requires_human_approval is not True or draft.is_sent is not False:
            raise ValueError("notification draft must remain pending human approval")


def project_progress(ledger: ProgressLedger) -> ProgressProjection:
    """Create a receipt plus an internal, human-gated notification draft.

    The brand remains accountable in ACTIVE, AT_RISK, and COMPLETED states, so
    no projected state asks the consumer to take an action.  Completion has no
    future timestamp and produces no draft; open states derive all three
    next-update projections from ``ledger.next_check_at``.
    """

    if ledger.status is ProgressStatus.COMPLETED:
        projection = ProgressProjection(
            next_check_at=None,
            receipt=ReceiptProjection(
                receipt_id=ledger.receipt_id,
                status=ledger.status,
                received_evidence=ledger.received_evidence,
                brand_action=ledger.brand_action,
                latest_update_at=ledger.latest_update_at,
                next_update_by=None,
                next_update_state="TERMINAL",
                consumer_action_required=False,
                recovery_if_missed=ledger.recovery_if_missed,
            ),
            proactive_notification_draft=None,
        )
        projection.validate()
        return projection

    assert ledger.next_check_at is not None
    committed_at = ledger.next_check_at
    text = _notification_text(ledger.status, committed_at)
    projection = ProgressProjection(
        next_check_at=committed_at,
        receipt=ReceiptProjection(
            receipt_id=ledger.receipt_id,
            status=ledger.status,
            received_evidence=ledger.received_evidence,
            brand_action=ledger.brand_action,
            latest_update_at=ledger.latest_update_at,
            next_update_by=committed_at,
            next_update_state="SCHEDULED",
            consumer_action_required=False,
            recovery_if_missed=ledger.recovery_if_missed,
        ),
        proactive_notification_draft=NotificationDraft(
            text=text,
            commits_next_update_at=committed_at,
        ),
    )
    projection.validate()
    return projection


def _notification_text(status: ProgressStatus, committed_at: datetime) -> str:
    prefix = {
        ProgressStatus.ACTIVE: "The brand is continuing the service process.",
        ProgressStatus.AT_RISK: "The brand is addressing the service risk.",
    }[status]
    return f"{prefix} The next update will follow by {_format_instant(committed_at)}."
