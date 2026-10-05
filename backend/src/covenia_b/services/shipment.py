"""Atomic execution of the shipment event state machine over the ledger.

The service is the only component that combines the pure shipment reducer with
durable persistence.  Idempotent request replay, ``event_id`` identity replay,
state-machine validation, the audit append, and the first response are all
resolved inside one serialized BATCH-18 transaction.  Nothing here contacts a
carrier, a warehouse system, or a notification channel: the returned
candidates and the notification draft are drafts for a human to approve.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from covenia_b.domain.types import (
    AccountabilityState,
    LedgerSnapshot,
    ShipmentEventRequest,
)
from covenia_b.domain.validation import ContractValidationError, validate_contract_payload
from covenia_b.ports.errors import LedgerConflict, LedgerUnavailable
from covenia_b.shipments import (
    ShipmentEvent,
    ShipmentEventType,
    ShipmentIdempotencyConflict,
    ShipmentLedger,
    ShipmentTransitionError,
    reduce_shipment_event,
)
from covenia_b.storage import (
    EventRecord,
    IdempotencyConflict,
    Mutation,
    StoredResponse,
    TransactionResult,
)
from covenia_b.storage.codec import StoredAccountabilityState

_LEDGER_CONFLICT_MESSAGE = (
    "Shipment event conflicts with the persisted ledger ordering or version."
)
_INFRASTRUCTURE_MESSAGE = "shipment transaction could not safely complete"
_LEDGER_MISSING_MESSAGE = "Shipment event requires an existing accountability ledger."
_REQUEST_SCHEMA = "shipment-event-request.schema.json"
_RESPONSE_SCHEMA = "shipment-event-response.schema.json"
_ENVELOPE_SCHEMA = "api-envelope.schema.json"


class ShipmentServiceError(RuntimeError):
    """Transport-neutral base error for the shipment HTTP endpoint."""

    code = "INTERNAL_ERROR"
    retryable = False

    def __init__(self, message: str, *, request_id: str) -> None:
        super().__init__(message)
        self.message = message
        self.request_id = request_id


class ShipmentInputError(ShipmentServiceError):
    """The submitted event uses the locked request type but an invalid value."""

    code = "VALIDATION_ERROR"


class ShipmentEventRejected(ShipmentServiceError):
    """The event is illegal for the currently locked server ledger."""

    code = "INVALID_EVENT_TRANSITION"


class ShipmentIdempotencyConflictError(ShipmentServiceError):
    """A request key or event identity was reused with different content."""

    code = "IDEMPOTENCY_CONFLICT"


class ShipmentInfrastructureError(ShipmentServiceError):
    """The ledger transaction could not safely complete."""

    retryable = True


class ShipmentTransactionRepository(Protocol):
    """The BATCH-18 atomic request/event replay boundary consumed by this service."""

    def execute(
        self,
        *,
        case_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, Any],
        mutate: Callable[[LedgerSnapshot | None], Mutation],
        event: EventRecord | None = None,
        expected_version: int | None = None,
    ) -> TransactionResult: ...


@dataclass(frozen=True, slots=True)
class ShipmentExecution:
    """The frozen envelope returned to the transport plus replay diagnostics."""

    response: dict[str, Any]
    data: Mapping[str, Any]
    request_id: str
    replayed: bool
    replay_source: str | None
    status_code: int


class ShipmentEventService:
    """Record one shipment event and persist its first complete response atomically."""

    def __init__(
        self,
        *,
        repository: ShipmentTransactionRepository,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._request_id_factory = request_id_factory or (lambda: f"shipment-{uuid4().hex}")

    def record_event(
        self,
        request: ShipmentEventRequest,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the schema-backed envelope for a future transport adapter."""

        return self.record_event_with_trace(request, request_id=request_id).response

    def record_event_with_trace(
        self,
        request: ShipmentEventRequest,
        *,
        request_id: str | None = None,
    ) -> ShipmentExecution:
        """Run one idempotent shipment event without trusting client-side state."""

        correlation_id = self._request_id(request_id)
        body = _normalized_request(request, request_id=correlation_id)
        event = _shipment_event(request, request_id=correlation_id)
        record = EventRecord(
            event_id=event.event_id,
            event_type=event.event_type.value,
            event_time=body["event_time"],
        )
        try:
            result = self._repository.execute(
                case_id=request.case_id,
                operation="shipment",
                idempotency_key=request.idempotency_key,
                request_body=body,
                mutate=lambda current: self._mutate(
                    current=current,
                    event=event,
                    request_id=correlation_id,
                ),
                event=record,
            )
        except ShipmentServiceError:
            raise
        except ShipmentIdempotencyConflict as error:
            raise ShipmentIdempotencyConflictError(str(error), request_id=correlation_id) from error
        except ShipmentTransitionError as error:
            raise ShipmentEventRejected(error.message, request_id=correlation_id) from error
        except IdempotencyConflict as error:
            raise ShipmentIdempotencyConflictError(
                _conflict_message(error),
                request_id=correlation_id,
            ) from error
        except LedgerConflict as error:
            raise ShipmentEventRejected(
                _LEDGER_CONFLICT_MESSAGE,
                request_id=correlation_id,
            ) from error
        except LedgerUnavailable as error:
            raise ShipmentInfrastructureError(
                _INFRASTRUCTURE_MESSAGE,
                request_id=correlation_id,
            ) from error

        envelope, data, persisted_request_id = _envelope_from_transaction(
            result,
            request_id=correlation_id,
        )
        return ShipmentExecution(
            response=envelope,
            data=data,
            request_id=persisted_request_id,
            replayed=result.replayed,
            replay_source=result.replay_source,
            status_code=result.response.status_code,
        )

    def _mutate(
        self,
        *,
        current: LedgerSnapshot | None,
        event: ShipmentEvent,
        request_id: str,
    ) -> Mutation:
        if current is None or current.accountability_state is None:
            raise ShipmentEventRejected(_LEDGER_MISSING_MESSAGE, request_id=request_id)
        state = current.accountability_state
        if current.case_id != event.case_id or state.case_id != event.case_id:
            raise ShipmentEventRejected(_LEDGER_MISSING_MESSAGE, request_id=request_id)

        transition = reduce_shipment_event(
            ShipmentLedger(
                accountability_state=state.to_contract(),
                event_high_watermark=_parse_persisted_instant(
                    current.event_high_watermark,
                    request_id=request_id,
                ),
                existing_ticket_id=_existing_ticket_id(state),
            ),
            event,
        )
        data = transition.outcome.as_contract()
        snapshot = LedgerSnapshot(
            case_id=current.case_id,
            version=current.version,
            event_high_watermark=_format_watermark(
                transition.ledger.event_high_watermark,
                request_id=request_id,
            ),
            accountability_state=_accountability_state(data, request_id=request_id),
            compiled_commitments=current.compiled_commitments,
        )
        return _mutation(snapshot, data=data, request_id=request_id)

    def _request_id(self, requested: str | None) -> str:
        value = self._request_id_factory() if requested is None else requested
        if not isinstance(value, str) or not value.strip():
            raise ValueError("request_id must be a non-empty string")
        return value


def _normalized_request(
    request: ShipmentEventRequest,
    *,
    request_id: str,
) -> dict[str, Any]:
    if not isinstance(request, ShipmentEventRequest):
        raise ShipmentInputError(
            "shipment event must use the locked request type",
            request_id=request_id,
        )
    try:
        body = request.to_contract()
    except (ContractValidationError, TypeError, ValueError) as error:
        raise ShipmentInputError(
            "shipment event request does not match the locked contract",
            request_id=request_id,
        ) from error
    try:
        validate_contract_payload(_REQUEST_SCHEMA, body)
    except ContractValidationError as error:
        raise ShipmentInputError(
            "shipment event request does not match the locked contract",
            request_id=request_id,
        ) from error
    return body


def _shipment_event(request: ShipmentEventRequest, *, request_id: str) -> ShipmentEvent:
    try:
        event_type = ShipmentEventType(request.event_type)
    except ValueError as error:
        raise ShipmentInputError(
            "event_type is outside the frozen shipment event vocabulary",
            request_id=request_id,
        ) from error
    try:
        return ShipmentEvent(
            case_id=request.case_id,
            event_id=request.event_id,
            event_type=event_type,
            event_time=_parse_request_instant(request.event_time, request_id=request_id),
            request_id=request_id,
        )
    except ValueError as error:
        raise ShipmentInputError(
            "shipment event fields are invalid",
            request_id=request_id,
        ) from error


def _parse_request_instant(value: str, *, request_id: str) -> datetime:
    parsed = _parse_instant(value)
    if parsed is None:
        raise ShipmentInputError(
            "event_time must be a date-time with an offset.",
            request_id=request_id,
        )
    return parsed


def _parse_persisted_instant(value: str | None, *, request_id: str) -> datetime | None:
    parsed = _parse_instant(value)
    if value is not None and parsed is None:
        raise ShipmentInfrastructureError(
            "persisted ledger watermark is not a valid instant",
            request_id=request_id,
        )
    return parsed


def _parse_instant(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _format_watermark(value: datetime | None, *, request_id: str) -> str:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ShipmentInfrastructureError(
            "shipment transition lost its event watermark",
            request_id=request_id,
        )
    return value.isoformat(timespec="seconds")


def _accountability_state(data: Mapping[str, Any], *, request_id: str) -> AccountabilityState:
    payload = data.get("accountability_state")
    if not isinstance(payload, Mapping):
        raise ShipmentInfrastructureError(
            "shipment response lost its accountability state",
            request_id=request_id,
        )
    receipt = payload.get("service_progress_receipt")
    # The frozen state schema permits a terminal ``next_update_by: null`` while the
    # older public DTO still declares a non-null field; the storage codec owns the
    # matching compatibility type, so the service reuses that exact rule.
    model = (
        StoredAccountabilityState
        if isinstance(receipt, Mapping) and receipt.get("next_update_by") is None
        else AccountabilityState
    )
    try:
        return model.from_contract(dict(payload))
    except (ContractValidationError, TypeError, ValueError) as error:
        raise ShipmentInfrastructureError(
            "shipment response state does not match the frozen contract",
            request_id=request_id,
        ) from error


def _existing_ticket_id(state: AccountabilityState) -> str | None:
    ticket_ids = sorted(
        {
            source_id
            for fact in state.experience_gap_diagnosis.traceable_service_facts
            if fact.fact_type == "TICKET_CREATED"
            for source_id in fact.source_ids
        }
    )
    return ticket_ids[0] if ticket_ids else None


def _mutation(snapshot: LedgerSnapshot, *, data: Mapping[str, Any], request_id: str) -> Mutation:
    payload = dict(data)
    try:
        validate_contract_payload(_RESPONSE_SCHEMA, payload)
    except ContractValidationError as error:
        raise ShipmentInfrastructureError(
            "shipment response did not satisfy the frozen contract",
            request_id=request_id,
        ) from error
    envelope: dict[str, Any] = {"data": payload, "error": None, "request_id": request_id}
    try:
        validate_contract_payload(_ENVELOPE_SCHEMA, envelope)
    except ContractValidationError as error:
        raise ShipmentInfrastructureError(
            "shipment envelope did not satisfy the frozen contract",
            request_id=request_id,
        ) from error
    return Mutation(
        snapshot=snapshot,
        response=StoredResponse(envelope, status_code=200, headers={"X-Request-Id": request_id}),
    )


def _envelope_from_transaction(
    result: TransactionResult,
    *,
    request_id: str,
) -> tuple[dict[str, Any], Mapping[str, Any], str]:
    body = result.response.body
    if not isinstance(body, Mapping) or body.get("error") is not None:
        raise ShipmentInfrastructureError(
            "stored shipment response is not a successful envelope",
            request_id=request_id,
        )
    data = body.get("data")
    persisted_request_id = body.get("request_id")
    if (
        not isinstance(data, Mapping)
        or not isinstance(persisted_request_id, str)
        or not persisted_request_id
    ):
        raise ShipmentInfrastructureError(
            "stored shipment response is incomplete",
            request_id=request_id,
        )
    try:
        validate_contract_payload(_RESPONSE_SCHEMA, dict(data))
        validate_contract_payload(_ENVELOPE_SCHEMA, dict(body))
    except ContractValidationError as error:
        raise ShipmentInfrastructureError(
            "stored shipment response does not match the frozen contract",
            request_id=request_id,
        ) from error
    return dict(body), data, persisted_request_id


def _conflict_message(error: IdempotencyConflict) -> str:
    # BATCH-18 raises one conflict type for two frozen causes; the event-identity
    # cause keeps the message published by the shipment contract vector.
    if "event identity" in str(error):
        return "event_id was already recorded with different event content."
    return "The idempotency key was already used with a different normalized body."
