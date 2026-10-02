"""Immutable inputs and outputs for the shipment transition reducer.

The reducer deliberately owns no HTTP, database, clock, or notification-send
side effect.  Its ledger is a complete in-memory value so callers can decide
when and how to persist the returned transition atomically.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from covenia_b.domain.validation import validate_contract_payload


class ShipmentEventType(StrEnum):
    """The closed shipment-event vocabulary frozen by the public contract."""

    PICKED_UP = "SHIPMENT_PICKED_UP"
    NOT_PICKED_UP = "SHIPMENT_NOT_PICKED_UP"
    DELIVERED = "SHIPMENT_DELIVERED"


class ShipmentTransitionError(ValueError):
    """A business-invalid shipment event that must not mutate the ledger."""

    code = "INVALID_EVENT_TRANSITION"
    status_code = 409
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ShipmentIdempotencyConflict(ShipmentTransitionError):
    """The same event identity was supplied with different immutable content."""

    code = "IDEMPOTENCY_CONFLICT"


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ShipmentEvent:
    """A validated shipment event plus trusted audit attribution.

    ``request_id`` is a server/request-middleware value rather than client
    shipment content, so it intentionally does not participate in event replay
    equivalence.  The HTTP layer will separately own idempotency-key handling.
    """

    case_id: str
    event_id: str
    event_type: ShipmentEventType
    event_time: datetime
    request_id: str
    actor: str = "LOGISTICS_PROVIDER"

    def __post_init__(self) -> None:
        for field, value in (
            ("case_id", self.case_id),
            ("event_id", self.event_id),
            ("request_id", self.request_id),
            ("actor", self.actor),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be blank")
        if not isinstance(self.event_type, ShipmentEventType):
            object.__setattr__(self, "event_type", ShipmentEventType(self.event_type))
        _require_aware(self.event_time, field="event_time")

    @property
    def fingerprint(self) -> tuple[str, datetime]:
        """Canonical event content used for event-identity replay checks."""

        return (self.event_type.value, self.event_time.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class ShipmentOutcome:
    """A contract-shaped pure result that a transport layer can persist verbatim.

    It intentionally keeps the accountability state as a mapping rather than
    the older Pydantic DTO: the locked wire schema permits a terminal
    ``next_update_by: null`` while the older DTO still declares that field as a
    non-null string.  ``as_contract`` remains the authoritative validation
    boundary for this reducer's public-shaped output.
    """

    accountability_state: Mapping[str, Any]
    follow_up_candidate: Mapping[str, Any] | None
    supervisor_escalation_candidate: Mapping[str, Any] | None
    proactive_notification_draft: Mapping[str, Any] | None

    def as_contract(self) -> dict[str, Any]:
        """Return a detached, schema-valid shipment-response payload."""

        payload: dict[str, Any] = {
            "accountability_state": deepcopy(dict(self.accountability_state)),
            "follow_up_candidate": (
                deepcopy(dict(self.follow_up_candidate))
                if self.follow_up_candidate is not None
                else None
            ),
            "supervisor_escalation_candidate": (
                deepcopy(dict(self.supervisor_escalation_candidate))
                if self.supervisor_escalation_candidate is not None
                else None
            ),
            "proactive_notification_draft": (
                deepcopy(dict(self.proactive_notification_draft))
                if self.proactive_notification_draft is not None
                else None
            ),
        }
        validate_contract_payload("shipment-event-response.schema.json", payload)
        return payload


@dataclass(frozen=True, slots=True)
class ProcessedShipmentEvent:
    """The first complete pure result for one event identity."""

    event: ShipmentEvent
    outcome: ShipmentOutcome


@dataclass(frozen=True, slots=True)
class ShipmentLedger:
    """State and optional event-history facts supplied by the caller.

    Storage can pass a high-watermark without retaining a local event list; a
    caller that supplies ``processed_events`` additionally gets exact pure
    event replay behavior.  The reducer never mutates either representation.
    """

    accountability_state: Mapping[str, Any]
    event_high_watermark: datetime | None = None
    processed_events: tuple[ProcessedShipmentEvent, ...] = ()
    existing_ticket_id: str | None = None

    def __post_init__(self) -> None:
        snapshot = deepcopy(dict(self.accountability_state))
        validate_contract_payload("accountability-state.schema.json", snapshot)
        object.__setattr__(self, "accountability_state", snapshot)

        if self.event_high_watermark is not None:
            _require_aware(self.event_high_watermark, field="event_high_watermark")
        if self.existing_ticket_id is not None and not self.existing_ticket_id.strip():
            raise ValueError("existing_ticket_id must not be blank")

        events = tuple(self.processed_events)
        object.__setattr__(self, "processed_events", events)
        seen_ids: set[str] = set()
        latest_recorded: datetime | None = None
        for record in events:
            if not isinstance(record, ProcessedShipmentEvent):
                raise TypeError("processed_events must contain ProcessedShipmentEvent values")
            if record.event.case_id != snapshot["case_id"]:
                raise ValueError("processed event case_id must match ledger state")
            if record.event.event_id in seen_ids:
                raise ValueError("processed event IDs must be unique")
            seen_ids.add(record.event.event_id)
            response_state = record.outcome.as_contract()["accountability_state"]
            if response_state["case_id"] != snapshot["case_id"]:
                raise ValueError("processed event outcome case_id must match ledger state")
            if latest_recorded is None or record.event.event_time > latest_recorded:
                latest_recorded = record.event.event_time

        if (
            latest_recorded is not None
            and self.event_high_watermark is not None
            and latest_recorded > self.event_high_watermark
        ):
            raise ValueError("event_high_watermark cannot precede a processed event")

    @property
    def case_id(self) -> str:
        return str(self.accountability_state["case_id"])


@dataclass(frozen=True, slots=True)
class ShipmentTransition:
    """A reducer result; ``replayed`` means no new state or audit mutation."""

    ledger: ShipmentLedger
    outcome: ShipmentOutcome
    replayed: bool
