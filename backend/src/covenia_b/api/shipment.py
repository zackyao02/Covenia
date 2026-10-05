"""HTTP adapter for the atomic, idempotent shipment event service.

This module owns HTTP parsing, the frozen-envelope mapping, and service
injection only.  The state machine, the idempotency decision, the audit append,
and the persisted first response remain in
:mod:`covenia_b.services.shipment`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from covenia_b.api.base import ApiError
from covenia_b.domain.types import ShipmentEventRequest
from covenia_b.domain.validation import ContractValidationError, validate_contract_payload
from covenia_b.services.shipment import (
    ShipmentEventRejected,
    ShipmentEventService,
    ShipmentIdempotencyConflictError,
    ShipmentInfrastructureError,
    ShipmentInputError,
    ShipmentServiceError,
)

_ROUTE_PATH = "/api/events/shipment"
_REQUEST_SCHEMA = "shipment-event-request.schema.json"


def install_shipment_router(app: FastAPI, *, shipment_service: ShipmentEventService) -> None:
    """Register the shipment route exactly once with its one injected service.

    Composition deliberately happens at the application boundary.  The adapter
    never creates a repository, a ledger, or an event decision itself.
    """

    installed = getattr(app.state, "shipment_service", None)
    if installed is not None:
        if installed is not shipment_service:
            raise RuntimeError("shipment router already has a different service")
        return
    app.state.shipment_service = shipment_service
    app.include_router(create_shipment_router(shipment_service=shipment_service))


def create_shipment_router(*, shipment_service: ShipmentEventService) -> APIRouter:
    """Create the frozen shipment endpoint around one service instance."""

    router = APIRouter()

    @router.post(_ROUTE_PATH)
    async def record_shipment_event(request: Request) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        payload = await _json_object(request)
        typed_request = _parse_request(payload)
        try:
            execution = shipment_service.record_event_with_trace(
                typed_request,
                request_id=request_id,
            )
        except ShipmentServiceError as error:
            raise _api_error_from_service(error) from error
        return JSONResponse(status_code=execution.status_code, content=execution.response)

    return router


async def _json_object(request: Request) -> Mapping[str, Any]:
    try:
        payload = await request.json()
    except (TypeError, ValueError) as error:
        raise ApiError(
            code="VALIDATION_ERROR",
            message="shipment event request must be a JSON object",
            status_code=400,
        ) from error
    if not isinstance(payload, Mapping):
        raise ApiError(
            code="VALIDATION_ERROR",
            message="shipment event request must be a JSON object",
            status_code=400,
        )
    return payload


def _parse_request(payload: Mapping[str, Any]) -> ShipmentEventRequest:
    try:
        validate_contract_payload(_REQUEST_SCHEMA, dict(payload))
    except ContractValidationError as error:
        raise ApiError(
            code="SCHEMA_INVALID",
            message=_schema_message(error),
            status_code=400,
        ) from error
    try:
        return ShipmentEventRequest.from_contract(dict(payload))
    except (ContractValidationError, ValidationError, TypeError, ValueError) as error:
        raise ApiError(
            code="SCHEMA_INVALID",
            message="shipment event request does not match the locked contract",
            status_code=400,
        ) from error


def _schema_message(error: ContractValidationError) -> str:
    # The frozen shipment contract vector publishes this message for a malformed
    # event_time, so the field-specific reason is derived from the failing path.
    if " at event_time: " in str(error):
        return "event_time must be a date-time with an offset."
    return "shipment event request does not match the locked contract"


def _api_error_from_service(error: ShipmentServiceError) -> ApiError:
    if isinstance(error, ShipmentIdempotencyConflictError):
        return ApiError(code=error.code, message=error.message, status_code=409)
    if isinstance(error, ShipmentEventRejected):
        return ApiError(code=error.code, message=error.message, status_code=409)
    if isinstance(error, ShipmentInputError):
        return ApiError(code=error.code, message=error.message, status_code=400)
    if isinstance(error, ShipmentInfrastructureError):
        return ApiError(
            code=error.code,
            message=error.message,
            status_code=503,
            retryable=error.retryable,
        )
    return ApiError(
        code=error.code,
        message="shipment event could not safely complete",
        status_code=500,
        retryable=error.retryable,
    )
