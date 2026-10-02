"""Deterministic shipment-state transitions with no persistence or HTTP work."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from covenia_b.receipts import (
    NotificationDraft,
    ProgressLedger,
    ProgressProjection,
    ProgressStatus,
    project_progress,
)
from covenia_b.shipments.models import (
    ProcessedShipmentEvent,
    ShipmentEvent,
    ShipmentEventType,
    ShipmentIdempotencyConflict,
    ShipmentLedger,
    ShipmentOutcome,
    ShipmentTransition,
    ShipmentTransitionError,
)

# The contract has no client-controlled next-update field.  When an inherited
# check has already elapsed at a shipment event, schedule a new deterministic
# check rather than returning an already-past consumer commitment.
POST_EVENT_CHECK_DELAY = timedelta(minutes=30)
DEFAULT_RECOVERY = "The brand will provide another update."
_FULFILLMENT_PROMISE_TYPES = {"REPLACEMENT_DISPATCH", "REPLACEMENT_FULFILLMENT"}


def reduce_shipment_event(ledger: ShipmentLedger, event: ShipmentEvent) -> ShipmentTransition:
    """Apply one valid event or raise without changing the supplied ledger.

    Replay is deliberately checked before current-state validation.  Thus an
    exact historical event remains replayable after a later delivery made the
    responsibility terminal; a new event after completion is still rejected.
    """

    if event.case_id != ledger.case_id:
        raise ShipmentTransitionError("Shipment event case_id does not match the ledger.")

    for record in ledger.processed_events:
        if record.event.event_id != event.event_id:
            continue
        if record.event.fingerprint == event.fingerprint:
            return ShipmentTransition(ledger=ledger, outcome=record.outcome, replayed=True)
        raise ShipmentIdempotencyConflict(
            "event_id was already recorded with different event content."
        )

    obligation = _open_obligation(ledger.accountability_state)
    if obligation is None:
        raise ShipmentTransitionError("Shipment event requires an open replacement obligation.")
    if _is_terminal(ledger.accountability_state, obligation):
        raise ShipmentTransitionError(
            "Completed shipment only permits an exact recorded replay."
        )

    if (
        ledger.event_high_watermark is not None
        and event.event_time < ledger.event_high_watermark
    ):
        raise ShipmentTransitionError("Shipment event_time is earlier than event high-watermark.")

    _require_legal_transition(str(obligation["milestone"]), event.event_type)
    return _apply_transition(ledger, event, obligation)


def _apply_transition(
    ledger: ShipmentLedger,
    event: ShipmentEvent,
    current_obligation: Mapping[str, Any],
) -> ShipmentTransition:
    state = deepcopy(dict(ledger.accountability_state))
    obligation = state["open_obligation"]
    assert isinstance(obligation, dict)

    deadline = _parse_instant(str(current_obligation["deadline"]))
    next_check = _next_check_after_event(
        current_value=str(current_obligation["next_check_at"]),
        event_time=event.event_time,
    )

    if event.event_type is ShipmentEventType.NOT_PICKED_UP:
        at_risk = event.event_time >= deadline
        obligation["milestone"] = "AWAITING_CARRIER_PICKUP"
        obligation["status"] = "AT_RISK" if at_risk else "ON_TRACK"
        obligation["next_check_at"] = _format_instant(next_check)
        _set_case_status(state, "AT_RISK" if at_risk else "IN_FULFILLMENT")
        _set_matching_commitment_status(state, "AT_RISK" if at_risk else None)
        receipt_status = "AT_RISK" if at_risk else "ON_TRACK"
        follow_up = _follow_up_candidate(ledger.existing_ticket_id) if at_risk else None
        escalation = _supervisor_escalation_candidate() if at_risk else None
    elif event.event_type is ShipmentEventType.PICKED_UP:
        obligation["milestone"] = "IN_TRANSIT"
        obligation["status"] = "ON_TRACK"
        obligation["executor"] = "LOGISTICS_PROVIDER"
        obligation["next_check_at"] = _format_instant(next_check)
        _set_case_status(state, "IN_FULFILLMENT")
        _set_matching_commitment_status(state, "COMPLETED")
        receipt_status = "ON_TRACK"
        follow_up = None
        escalation = None
    else:
        obligation["milestone"] = "DELIVERED"
        obligation["status"] = "COMPLETED"
        obligation["executor"] = "LOGISTICS_PROVIDER"
        # The frozen state schema requires this field even for a completed
        # obligation.  Event time is a terminal historical marker, never a
        # future update promise; the receipt and draft correctly become null.
        obligation["next_check_at"] = _format_instant(event.event_time)
        _set_case_status(state, "RESOLVED")
        _set_matching_commitment_status(state, "COMPLETED")
        receipt_status = "COMPLETED"
        next_check = None
        follow_up = None
        escalation = None

    projection = _project_progress(
        state=state,
        status=receipt_status,
        milestone=str(obligation["milestone"]),
        event_time=event.event_time,
        next_check=next_check,
    )
    state["service_progress_receipt"] = projection.receipt.consumer_view()
    before_audit = deepcopy(state)
    state["audit_trail"].append(
        {
            "at": _format_instant(event.event_time),
            "actor": event.actor,
            "action": event.event_type.value,
            "changed_fields": [
                *_changed_fields(ledger.accountability_state, before_audit),
                "audit_trail",
            ],
            "request_id": event.request_id,
        }
    )

    draft = projection.proactive_notification_draft
    outcome = ShipmentOutcome(
        accountability_state=state,
        follow_up_candidate=follow_up,
        supervisor_escalation_candidate=escalation,
        proactive_notification_draft=(
            {
                "text": draft.text,
                "commits_next_update_at": _format_instant(draft.commits_next_update_at),
                "requires_human_approval": True,
                "channel": draft.channel,
            }
            if draft is not None
            else None
        ),
    )
    # Validate before constructing the next ledger so invalid output can never
    # masquerade as an accepted state transition.
    outcome.as_contract()
    high_watermark = max(
        (value for value in (ledger.event_high_watermark, event.event_time) if value is not None),
        default=event.event_time,
    )
    updated_ledger = ShipmentLedger(
        accountability_state=state,
        event_high_watermark=high_watermark,
        processed_events=(*ledger.processed_events, ProcessedShipmentEvent(event, outcome)),
        existing_ticket_id=ledger.existing_ticket_id,
    )
    return ShipmentTransition(ledger=updated_ledger, outcome=outcome, replayed=False)


def _open_obligation(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    obligation = state.get("open_obligation")
    if obligation is None:
        return None
    if not isinstance(obligation, Mapping):
        raise ValueError("open_obligation must be a mapping")
    return obligation


def _is_terminal(state: Mapping[str, Any], obligation: Mapping[str, Any]) -> bool:
    return (
        state.get("case_status") == "RESOLVED"
        or obligation.get("status") == "COMPLETED"
        or obligation.get("milestone") == "DELIVERED"
    )


def _require_legal_transition(milestone: str, event_type: ShipmentEventType) -> None:
    allowed = {
        "AWAITING_CARRIER_PICKUP": {
            ShipmentEventType.NOT_PICKED_UP,
            ShipmentEventType.PICKED_UP,
        },
        "IN_TRANSIT": {ShipmentEventType.DELIVERED},
    }
    if event_type in allowed.get(milestone, set()):
        return
    if event_type is ShipmentEventType.DELIVERED:
        raise ShipmentTransitionError("Shipment delivery requires IN_TRANSIT.")
    raise ShipmentTransitionError(
        f"{event_type.value} is not permitted from {milestone}."
    )


def _set_case_status(state: dict[str, Any], case_status: str) -> None:
    state["case_status"] = case_status
    state["accountable_side"] = "BRAND"
    state["consumer_input_required"] = False
    if case_status == "AT_RISK":
        state["experience_risk"] = "HIGH"
        if "SHIFT_FOLLOW_UP_TO_CONSUMER" not in state["prohibited_actions"]:
            state["prohibited_actions"].append("SHIFT_FOLLOW_UP_TO_CONSUMER")
    elif case_status == "RESOLVED":
        state["experience_risk"] = "LOW"
        state["prohibited_actions"] = [
            action
            for action in state["prohibited_actions"]
            if action != "CLOSE_BEFORE_RESOLUTION"
        ]
    else:
        state["experience_risk"] = "MEDIUM"


def _set_matching_commitment_status(state: dict[str, Any], status: str | None) -> None:
    if status is None:
        return
    for commitment in state["active_commitments"]:
        if commitment.get("promise_type") not in _FULFILLMENT_PROMISE_TYPES:
            continue
        if status == "AT_RISK" and commitment.get("status") == "COMPLETED":
            continue
        commitment["status"] = status


def _project_progress(
    *,
    state: Mapping[str, Any],
    status: str,
    milestone: str,
    event_time: datetime,
    next_check: datetime | None,
) -> ProgressProjection:
    previous = state.get("service_progress_receipt")
    receipt = previous if isinstance(previous, Mapping) else {}
    progress_status = {
        "ON_TRACK": ProgressStatus.ACTIVE,
        "AT_RISK": ProgressStatus.AT_RISK,
        "COMPLETED": ProgressStatus.COMPLETED,
    }[status]
    projection = project_progress(
        ProgressLedger(
            receipt_id=str(receipt.get("receipt_id") or f"{state['case_id']}:replacement"),
            status=progress_status,
            received_evidence=tuple(receipt.get("received_evidence", ())),
            brand_action=_brand_action(milestone, status),
            latest_update_at=event_time,
            next_check_at=next_check,
            recovery_if_missed=str(receipt.get("recovery_if_missed") or DEFAULT_RECOVERY),
        )
    )
    if projection.proactive_notification_draft is None:
        return projection

    committed_at = projection.proactive_notification_draft.commits_next_update_at
    customized_draft = NotificationDraft(
        text=_notification_text(milestone, status, committed_at),
        commits_next_update_at=committed_at,
    )
    customized = replace(projection, proactive_notification_draft=customized_draft)
    customized.validate()
    return customized


def _brand_action(milestone: str, status: str) -> str:
    if status == "COMPLETED":
        return "The replacement has been delivered."
    if status == "AT_RISK":
        return "The shipment handoff is being escalated."
    if milestone == "IN_TRANSIT":
        return "The replacement shipment has been picked up and is in transit."
    return "The brand is monitoring the replacement handoff."


def _notification_text(milestone: str, status: str, committed_at: datetime) -> str:
    instant = _format_instant(committed_at)
    if status == "AT_RISK":
        return f"The shipment handoff is being escalated; the next update will follow by {instant}."
    if milestone == "IN_TRANSIT":
        return f"The replacement shipment is in transit; the next update will follow by {instant}."
    return (
        "The brand is monitoring the replacement handoff; "
        f"the next update will follow by {instant}."
    )


def _follow_up_candidate(existing_ticket_id: str | None) -> dict[str, Any]:
    return {
        "task_type": "WAREHOUSE_FOLLOW_UP",
        "existing_ticket_id": existing_ticket_id,
        "priority": "HIGH",
        "summary": "Confirm the delayed shipment handoff.",
    }


def _supervisor_escalation_candidate() -> dict[str, Any]:
    return {
        "escalation_type": "PROMISE_OVERDUE",
        "priority": "HIGH",
        "summary": "Review the overdue fulfillment handoff.",
    }


def _next_check_after_event(*, current_value: str, event_time: datetime) -> datetime:
    current = _parse_instant(current_value)
    return current if current > event_time else event_time + POST_EVENT_CHECK_DELAY


def _parse_instant(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("state timestamps must be parseable RFC 3339 instants") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("state timestamps must be timezone-aware")
    return parsed


def _format_instant(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("shipment timestamps must be timezone-aware")
    return value.isoformat(timespec="seconds")


def _changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    tracked = (
        "case_status",
        "accountable_side",
        "active_commitments",
        "prohibited_actions",
        "open_obligation",
        "service_progress_receipt",
        "experience_risk",
    )
    return [field for field in tracked if before.get(field) != after.get(field)]
