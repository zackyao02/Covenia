"""HTTP adapter for the read-only authoritative evaluate service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from covenia_b.api.base import ApiError
from covenia_b.domain.types import EvaluateActionRequest
from covenia_b.domain.validation import ContractValidationError
from covenia_b.rules import ProhibitedActionError
from covenia_b.services.evaluate import EvaluateService, EvaluateServiceError


def create_evaluate_router(service: EvaluateService) -> APIRouter:
    """Create an explicitly wired router; application composition remains external."""

    router = APIRouter()

    @router.post("/evaluate")
    async def evaluate_action(request: Request, body: dict[str, Any]) -> JSONResponse:
        request_id = request.state.request_id
        try:
            parsed = EvaluateActionRequest.from_contract(body)
            execution = service.evaluate_with_trace(parsed, request_id=request_id)
            return JSONResponse(
                status_code=200,
                content={
                    "data": execution.result.to_contract(),
                    "error": None,
                    "request_id": request_id,
                },
            )
        except ContractValidationError as error:
            raise ApiError(
                code="SCHEMA_INVALID",
                message="request does not match the frozen schema",
                status_code=422,
            ) from error
        except ProhibitedActionError as error:
            raise ApiError(
                code=error.code, message=str(error), status_code=error.http_status
            ) from error
        except EvaluateServiceError as error:
            raise ApiError(
                code=error.code,
                message=str(error),
                status_code=503 if error.retryable else 422,
                retryable=error.retryable,
            ) from error

    return router
