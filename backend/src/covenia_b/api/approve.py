"""HTTP adapter for the server-validated, idempotent approval service.

This module deliberately owns only HTTP parsing, frozen-envelope mapping, and
service injection.  Candidate validation, mutations, and idempotent response
storage remain in :mod:`covenia_b.services.approve`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from covenia_b.api.base import ApiError
from covenia_b.domain.types import ApproveResolutionRequest
from covenia_b.domain.validation import ContractValidationError
from covenia_b.services.approve import (
    ApprovalConflictError,
    ApprovalInfrastructureError,
    ApprovalInputError,
    ApprovalService,
    ApprovalServiceError,
)

_ROUTE_PATH = "/api/resolutions/approve"


def install_approve_router(app: FastAPI, *, approval_service: ApprovalService) -> None:
    """Register the approval route exactly once with its one injected service.

    Composition deliberately happens at the application boundary.  The adapter
    never creates a repository, clock, candidate, or approval decision itself.
    """

    installed = getattr(app.state, "approval_service", None)
    if installed is not None:
        if installed is not approval_service:
            raise RuntimeError("approve router already has a different service")
        return
    app.state.approval_service = approval_service
    app.include_router(create_approve_router(approval_service=approval_service))


def create_approve_router(*, approval_service: ApprovalService) -> APIRouter:
    """Create the frozen approval endpoint around one service instance."""

    router = APIRouter()

    @router.post(_ROUTE_PATH)
    async def approve_resolution(request: Request) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        payload = await _json_object(request, request_id=request_id)
        typed_request = _parse_request(payload, request_id=request_id)
        try:
            execution = approval_service.approve_with_trace(
                typed_request,
                request_id=request_id,
            )
        except ApprovalServiceError as error:
            raise _api_error_from_service(error) from error
        envelope = {
            "data": execution.response.to_contract(),
            "error": None,
            "request_id": execution.request_id,
        }
        return JSONResponse(status_code=execution.status_code, content=envelope)

    return router


async def _json_object(request: Request, *, request_id: str | None) -> Mapping[str, Any]:
    try:
        payload = await request.json()
    except (TypeError, ValueError) as error:
        raise ApiError(
            code="VALIDATION_ERROR",
            message="approval request must be a JSON object",
            status_code=400,
        ) from error
    if not isinstance(payload, Mapping):
        raise ApiError(
            code="VALIDATION_ERROR",
            message="approval request must be a JSON object",
            status_code=400,
        )
    return payload


def _parse_request(
    payload: Mapping[str, Any], *, request_id: str | None
) -> ApproveResolutionRequest:
    approver_id = payload.get("approver_id")
    if not isinstance(approver_id, str) or not approver_id.strip():
        raise ApiError(
            code="VALIDATION_ERROR",
            message="approver_id is required for approval",
            status_code=400,
        )
    try:
        return ApproveResolutionRequest.from_contract(dict(payload))
    except (ContractValidationError, ValidationError, TypeError, ValueError) as error:
        raise ApiError(
            code="VALIDATION_ERROR",
            message="approval request does not match the locked contract",
            status_code=400,
        ) from error


def _api_error_from_service(error: ApprovalServiceError) -> ApiError:
    if isinstance(error, ApprovalConflictError):
        return ApiError(code=error.code, message=str(error), status_code=409)
    if isinstance(error, ApprovalInputError):
        return ApiError(code=error.code, message=str(error), status_code=400)
    if isinstance(error, ApprovalInfrastructureError):
        return ApiError(
            code=error.code,
            message=str(error),
            status_code=503,
            retryable=error.retryable,
        )
    return ApiError(
        code=error.code,
        message="approval could not safely complete",
        status_code=500,
        retryable=error.retryable,
    )
