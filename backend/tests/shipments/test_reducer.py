from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from covenia_b.shipments import (
    ShipmentEvent,
    ShipmentEventType,
    ShipmentIdempotencyConflict,
    ShipmentLedger,
    ShipmentTransitionError,
    reduce_shipment_event,
)

CASE_ID = "CASE-SHIPMENT-25"
DEADLINE = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
INITIAL_NEXT_CHECK = datetime(2030, 1, 1, 10, 5, tzinfo=UTC)


def instant(hour: int, minute: int = 0) -> datetime:
    return datetime(2030, 1, 1, hour, minute, tzinfo=UTC)


def rendered(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def make_state(*, with_obligation: bool = True) -> dict[str, object]:
    obligation = (
        {
            "obligation_type": "REPLACEMENT_FULFILLMENT",
            "status": "ON_TRACK",
            "accountable_side": "BRAND",
            "executor": "WAREHOUSE",
            "deadline": rendered(DEADLINE),
            "next_check_at": rendered(INITIAL_NEXT_CHECK),
            "milestone": "AWAITING_CARRIER_PICKUP",
            "resolution_condition": "REPLACEMENT_DELIVERED",
        }
        if with_obligation
        else None
    )
    return {
        "case_id": CASE_ID,
        "case_status": "IN_FULFILLMENT" if with_obligation else "READY_FOR_BRAND",
        "consumer_input_required": False,
        "accountable_side": "BRAND",
        "evidence_status": "VALID",
        "current_scope": {
            "order_id": "ORDER-SHIPMENT-25",
            "fulfillment_item_id": "ITEM-SHIPMENT-25",
            "sku_id": "SKU-SHIPMENT-25",
            "issue_type": "PACKAGE_DAMAGE",
        },
        "active_commitments": (
            [
                {
                    "promise_type": "REPLACEMENT_FULFILLMENT",
                    "raw_text": "A replacement will be dispatched.",
                    "status": "ACTIVE",
                    "deadline": rendered(DEADLINE),
                    "source_ids": ["SOURCE-SHIPMENT-25"],
                }
            ]
            if with_obligation
            else []
        ),
        "prohibited_actions": ["SHIFT_FOLLOW_UP_TO_CONSUMER", "CLOSE_BEFORE_RESOLUTION"],
        "experience_gap_diagnosis": {
            "consumer_expression": "A promised progress update is pending.",
            "traceable_service_facts": [
                {
                    "fact_type": "PROMISE_ACTIVE",
                    "statement": "The replacement handoff is pending.",
                    "source_ids": ["SOURCE-SHIPMENT-25"],
                }
            ],
            "deterioration_cause": "Replacement fulfillment is pending.",
            "latent_need": "A traceable service update.",
            "responsibility_judgment": {
                "consumer_input_complete": True,
                "accountable_side": "BRAND",
            },
            "action_impacts": ["START_PROACTIVE_UPDATE"],
            "reply_strategy": "Provide a pending approval notification draft.",
        },
        "open_obligation": obligation,
        "service_progress_receipt": (
            {
                "receipt_id": "RECEIPT-SHIPMENT-25",
                "status": "ACTIVE",
                "received_evidence": ["Service facts"],
                "brand_action": "The brand is monitoring the replacement handoff.",
                "latest_update_at": rendered(instant(9)),
                "next_update_by": rendered(INITIAL_NEXT_CHECK),
                "consumer_action_required": False,
                "recovery_if_missed": "The brand will provide another update.",
            }
            if with_obligation
            else None
        ),
        "experience_risk": "MEDIUM" if with_obligation else "LOW",
        "audit_trail": [],
    }


def make_ledger(
    *,
    with_obligation: bool = True,
    existing_ticket_id: str | None = None,
) -> ShipmentLedger:
    return ShipmentLedger(
        accountability_state=make_state(with_obligation=with_obligation),
        existing_ticket_id=existing_ticket_id,
    )


def event(
    *,
    event_id: str,
    event_type: ShipmentEventType,
    event_time: datetime,
    request_id: str | None = None,
) -> ShipmentEvent:
    return ShipmentEvent(
        case_id=CASE_ID,
        event_id=event_id,
        event_type=event_type,
        event_time=event_time,
        request_id=request_id or f"REQ-{event_id}",
    )


def test_not_picked_up_before_deadline_stays_on_track_and_synchronizes_projections() -> None:
    result = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-NORMAL",
            event_type=ShipmentEventType.NOT_PICKED_UP,
            event_time=instant(9, 30),
        ),
    )

    payload = result.outcome.as_contract()
    state = payload["accountability_state"]
    assert result.replayed is False
    assert result.ledger.event_high_watermark == instant(9, 30)
    assert state["case_status"] == "IN_FULFILLMENT"
    assert state["open_obligation"]["status"] == "ON_TRACK"
    assert state["open_obligation"]["milestone"] == "AWAITING_CARRIER_PICKUP"
    assert state["open_obligation"]["next_check_at"] == rendered(INITIAL_NEXT_CHECK)
    assert state["active_commitments"][0]["status"] == "ACTIVE"
    assert state["service_progress_receipt"]["status"] == "ACTIVE"
    assert state["service_progress_receipt"]["next_update_by"] == rendered(INITIAL_NEXT_CHECK)
    assert payload["proactive_notification_draft"]["commits_next_update_at"] == rendered(
        INITIAL_NEXT_CHECK
    )
    assert rendered(INITIAL_NEXT_CHECK) in payload["proactive_notification_draft"]["text"]
    assert payload["follow_up_candidate"] is None
    assert payload["supervisor_escalation_candidate"] is None
    assert state["audit_trail"][-1]["action"] == "SHIPMENT_NOT_PICKED_UP"


def test_overdue_not_picked_up_escalates_and_replaces_an_elapsed_next_check() -> None:
    result = reduce_shipment_event(
        make_ledger(existing_ticket_id="TICKET-SHIPMENT-25"),
        event(
            event_id="EVENT-RISK",
            event_type=ShipmentEventType.NOT_PICKED_UP,
            event_time=instant(10, 30),
        ),
    )

    payload = result.outcome.as_contract()
    state = payload["accountability_state"]
    next_update = rendered(instant(11))
    assert state["case_status"] == "AT_RISK"
    assert state["experience_risk"] == "HIGH"
    assert state["open_obligation"]["status"] == "AT_RISK"
    assert state["open_obligation"]["next_check_at"] == next_update
    assert state["active_commitments"][0]["status"] == "AT_RISK"
    assert state["service_progress_receipt"]["status"] == "AT_RISK"
    assert state["service_progress_receipt"]["next_update_by"] == next_update
    assert payload["proactive_notification_draft"]["commits_next_update_at"] == next_update
    assert next_update in payload["proactive_notification_draft"]["text"]
    assert payload["follow_up_candidate"] == {
        "task_type": "WAREHOUSE_FOLLOW_UP",
        "existing_ticket_id": "TICKET-SHIPMENT-25",
        "priority": "HIGH",
        "summary": "Confirm the delayed shipment handoff.",
    }
    assert payload["supervisor_escalation_candidate"] == {
        "escalation_type": "PROMISE_OVERDUE",
        "priority": "HIGH",
        "summary": "Review the overdue fulfillment handoff.",
    }


def test_pickup_moves_to_in_transit_without_resolving_and_completes_dispatch_promise() -> None:
    result = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-PICKUP",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=instant(10, 30),
        ),
    )

    payload = result.outcome.as_contract()
    state = payload["accountability_state"]
    assert state["case_status"] == "IN_FULFILLMENT"
    assert state["case_status"] != "RESOLVED"
    assert state["open_obligation"]["milestone"] == "IN_TRANSIT"
    assert state["open_obligation"]["status"] == "ON_TRACK"
    assert state["open_obligation"]["executor"] == "LOGISTICS_PROVIDER"
    assert state["open_obligation"]["next_check_at"] == rendered(instant(11))
    assert state["active_commitments"][0]["status"] == "COMPLETED"
    assert state["service_progress_receipt"]["status"] == "ACTIVE"
    assert state["service_progress_receipt"]["next_update_by"] == rendered(instant(11))
    assert payload["follow_up_candidate"] is None
    assert payload["supervisor_escalation_candidate"] is None
    assert payload["proactive_notification_draft"] is not None


def test_delivered_only_from_in_transit_and_has_a_terminal_receipt() -> None:
    picked_up = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-PICKUP-FIRST",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=instant(9, 40),
        ),
    )
    delivered = reduce_shipment_event(
        picked_up.ledger,
        event(
            event_id="EVENT-DELIVERED",
            event_type=ShipmentEventType.DELIVERED,
            event_time=instant(10),
        ),
    )

    payload = delivered.outcome.as_contract()
    state = payload["accountability_state"]
    assert state["case_status"] == "RESOLVED"
    assert state["open_obligation"]["milestone"] == "DELIVERED"
    assert state["open_obligation"]["status"] == "COMPLETED"
    assert state["open_obligation"]["next_check_at"] == rendered(instant(10))
    assert state["active_commitments"][0]["status"] == "COMPLETED"
    assert state["service_progress_receipt"]["status"] == "COMPLETED"
    assert state["service_progress_receipt"]["next_update_by"] is None
    assert payload["proactive_notification_draft"] is None
    assert payload["follow_up_candidate"] is None
    assert payload["supervisor_escalation_candidate"] is None


def test_direct_delivery_is_rejected_without_state_or_audit_mutation() -> None:
    ledger = make_ledger()
    initial_state = deepcopy(ledger.accountability_state)

    with pytest.raises(ShipmentTransitionError, match="requires IN_TRANSIT"):
        reduce_shipment_event(
            ledger,
            event(
                event_id="EVENT-DIRECT-DELIVERY",
                event_type=ShipmentEventType.DELIVERED,
                event_time=instant(9, 30),
            ),
        )

    assert ledger.accountability_state == initial_state
    assert ledger.processed_events == ()
    assert ledger.event_high_watermark is None


def test_reverse_events_and_not_picked_after_in_transit_are_rejected_unchanged() -> None:
    picked_up = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-TRANSIT",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=instant(9, 30),
        ),
    )
    before = deepcopy(picked_up.ledger.accountability_state)

    for invalid in (
        event(
            event_id="EVENT-TRANSIT-NOT-PICKED",
            event_type=ShipmentEventType.NOT_PICKED_UP,
            event_time=instant(9, 31),
        ),
        event(
            event_id="EVENT-TRANSIT-PICKED-AGAIN",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=instant(9, 32),
        ),
    ):
        with pytest.raises(ShipmentTransitionError):
            reduce_shipment_event(picked_up.ledger, invalid)
        assert picked_up.ledger.accountability_state == before
        assert len(picked_up.ledger.processed_events) == 1


def test_event_without_an_obligation_is_rejected_without_audit_mutation() -> None:
    ledger = make_ledger(with_obligation=False)
    initial_state = deepcopy(ledger.accountability_state)

    with pytest.raises(ShipmentTransitionError, match="requires an open replacement obligation"):
        reduce_shipment_event(
            ledger,
            event(
                event_id="EVENT-NO-OBLIGATION",
                event_type=ShipmentEventType.PICKED_UP,
                event_time=instant(9, 30),
            ),
        )

    assert ledger.accountability_state == initial_state
    assert ledger.processed_events == ()


def test_high_watermark_rejects_reverse_time_but_equal_time_legal_transition_is_accepted() -> None:
    normal = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-HIGH-WATER-NORMAL",
            event_type=ShipmentEventType.NOT_PICKED_UP,
            event_time=instant(9, 30),
        ),
    )
    before = deepcopy(normal.ledger.accountability_state)

    with pytest.raises(ShipmentTransitionError, match="earlier than event high-watermark"):
        reduce_shipment_event(
            normal.ledger,
            event(
                event_id="EVENT-HIGH-WATER-OLD",
                event_type=ShipmentEventType.PICKED_UP,
                event_time=instant(9, 29),
            ),
        )
    assert normal.ledger.accountability_state == before

    equal_time_pickup = reduce_shipment_event(
        normal.ledger,
        event(
            event_id="EVENT-HIGH-WATER-EQUAL",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=instant(9, 30),
        ),
    )
    assert equal_time_pickup.replayed is False
    assert equal_time_pickup.ledger.event_high_watermark == instant(9, 30)
    assert equal_time_pickup.outcome.as_contract()["accountability_state"]["open_obligation"][
        "milestone"
    ] == "IN_TRANSIT"


def test_exact_event_replay_survives_completion_without_another_audit_entry() -> None:
    picked_up = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-REPLAY-PICKUP",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=instant(9, 30),
        ),
    )
    original_delivery = event(
        event_id="EVENT-REPLAY-DELIVERED",
        event_type=ShipmentEventType.DELIVERED,
        event_time=instant(9, 45),
        request_id="REQ-ORIGINAL-DELIVERY",
    )
    delivered = reduce_shipment_event(picked_up.ledger, original_delivery)
    replay = reduce_shipment_event(
        delivered.ledger,
        event(
            event_id="EVENT-REPLAY-DELIVERED",
            event_type=ShipmentEventType.DELIVERED,
            event_time=instant(9, 45),
            request_id="REQ-REPLAY-DELIVERY",
        ),
    )

    assert replay.replayed is True
    assert replay.ledger == delivered.ledger
    assert replay.outcome == delivered.outcome
    assert len(replay.ledger.accountability_state["audit_trail"]) == 2

    with pytest.raises(ShipmentTransitionError, match="Completed shipment"):
        reduce_shipment_event(
            delivered.ledger,
            event(
                event_id="EVENT-AFTER-COMPLETION",
                event_type=ShipmentEventType.PICKED_UP,
                event_time=instant(10),
            ),
        )
    assert len(delivered.ledger.accountability_state["audit_trail"]) == 2


@pytest.mark.parametrize(
    ("event_type", "event_time", "expected_case_status"),
    (
        (ShipmentEventType.NOT_PICKED_UP, instant(9, 30), "IN_FULFILLMENT"),
        (ShipmentEventType.NOT_PICKED_UP, instant(10, 30), "AT_RISK"),
    ),
)
def test_normal_and_risk_branches_each_replay_their_first_outcome(
    event_type: ShipmentEventType,
    event_time: datetime,
    expected_case_status: str,
) -> None:
    original = event(
        event_id=f"EVENT-BRANCH-{expected_case_status}",
        event_type=event_type,
        event_time=event_time,
        request_id=f"REQ-BRANCH-{expected_case_status}-FIRST",
    )
    accepted = reduce_shipment_event(make_ledger(), original)
    replay = reduce_shipment_event(
        accepted.ledger,
        event(
            event_id=original.event_id,
            event_type=event_type,
            event_time=event_time,
            request_id=f"REQ-BRANCH-{expected_case_status}-REPLAY",
        ),
    )

    accepted_state = accepted.outcome.as_contract()["accountability_state"]
    assert accepted_state["case_status"] == expected_case_status
    assert replay.replayed is True
    assert replay.outcome == accepted.outcome
    assert len(replay.ledger.accountability_state["audit_trail"]) == 1


def test_same_event_id_with_different_content_is_an_idempotency_conflict() -> None:
    accepted = reduce_shipment_event(
        make_ledger(),
        event(
            event_id="EVENT-CONFLICT",
            event_type=ShipmentEventType.NOT_PICKED_UP,
            event_time=instant(9, 30),
        ),
    )
    before = deepcopy(accepted.ledger.accountability_state)

    with pytest.raises(ShipmentIdempotencyConflict, match="different event content") as error:
        reduce_shipment_event(
            accepted.ledger,
            event(
                event_id="EVENT-CONFLICT",
                event_type=ShipmentEventType.PICKED_UP,
                event_time=instant(9, 31),
            ),
        )

    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert accepted.ledger.accountability_state == before
    assert len(accepted.ledger.processed_events) == 1


def test_shipment_event_requires_an_aware_event_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        event(
            event_id="EVENT-NAIVE",
            event_type=ShipmentEventType.PICKED_UP,
            event_time=datetime(2030, 1, 1, 9, 30),
        )
