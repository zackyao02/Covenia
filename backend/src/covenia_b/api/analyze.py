"""HTTP transport adapter for the frozen case-analysis contract.

The router is deliberately a factory: application wiring owns the concrete
``AnalyzeService`` and this module neither creates a provider nor registers a
route on the shared application.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from covenia_b.api.base import REQUEST_ID_HEADER, normalize_request_id
from covenia_b.domain.types import AnalyzeCaseRequest, AnalyzeCaseResponse
from covenia_b.domain.validation import validate_contract_payload
from covenia_b.services.analyze import AnalysisServiceError

ANALYZE_PATH = "/api/cases/analyze"
DEFAULT_ANALYSIS_TIMEOUT_SECONDS = 20.0
RESPONSE_SCHEMA_NAME = "analyze-case-response.schema.json"


class AnalyzeCallable(Protocol):
    """The narrow service seam owned by the composition root."""

    def analyze(
        self,
        request: AnalyzeCaseRequest,
        *,
        request_id: str | None = None,
    ) -> Awaitable[AnalyzeCaseResponse]: ...


def create_analyze_router(
    analysis_service: AnalyzeCallable,
    *,
    timeout_seconds: float = DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
) -> APIRouter:
    """Create the unregistered POST adapter for a supplied analysis service."""

    if timeout_seconds <= 0 or timeout_seconds > DEFAULT_ANALYSIS_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be greater than zero and at most 20 seconds")

    router = APIRouter()

    @router.post(ANALYZE_PATH)
    async def analyze_case(request: Request) -> JSONResponse:
        request_id = _request_id(request)
        try:
            payload = await request.json()
            parsed = AnalyzeCaseRequest.model_validate(payload)
            parsed.to_contract()
        except (ValidationError, ValueError, TypeError):
            return _error_response(
                request_id=request_id,
                code="SCHEMA_INVALID",
                message="request does not satisfy the analyze-case contract",
                status_code=422,
                retryable=False,
            )

        try:
            result = await asyncio.wait_for(
                analysis_service.analyze(parsed, request_id=request_id),
                timeout=timeout_seconds,
            )
            # AnalyzeService validates this projection before returning, but the
            # service is a replaceable seam: re-validate the exact payload at the
            # HTTP boundary so no client can receive data outside the frozen
            # analyze-case-response contract.
            data = result.to_contract()
            validate_contract_payload(RESPONSE_SCHEMA_NAME, data)
        except TimeoutError:
            return _error_response(
                request_id=request_id,
                code="INTERNAL_ERROR",
                message="analysis did not complete within the configured time limit",
                status_code=504,
                retryable=True,
            )
        except AnalysisServiceError as error:
            return _error_response(
                request_id=error.request_id,
                code=error.code,
                message=error.args[0],
                status_code=_status_for_error(error.code),
                retryable=error.retryable,
            )
        except (TypeError, ValueError):
            # ContractValidationError subclasses ValueError, so a schema-invalid
            # service projection lands on this existing safe INTERNAL_ERROR
            # envelope instead of reaching the client as a 200 success.
            return _error_response(
                request_id=request_id,
                code="INTERNAL_ERROR",
                message="analysis response could not be safely serialized",
                status_code=500,
                retryable=False,
            )

        return _json_response(
            {"data": data, "error": None, "request_id": request_id},
            200,
            request_id,
        )

    return router


def _request_id(request: Request) -> str:
    """Reuse base middleware state when installed, otherwise stay standalone-safe."""

    return getattr(
        request.state,
        "request_id",
        normalize_request_id(request.headers.get(REQUEST_ID_HEADER)),
    )


def _status_for_error(code: str) -> int:
    return {
        "VALIDATION_ERROR": 422,
        "MODEL_UNAVAILABLE": 503,
        "MODEL_OUTPUT_INVALID": 502,
        "INTERNAL_ERROR": 500,
    }.get(code, 500)


def _error_response(
    *,
    request_id: str,
    code: str,
    message: str,
    status_code: int,
    retryable: bool,
) -> JSONResponse:
    return _json_response(
        {
            "data": None,
            "error": {"code": code, "message": message, "retryable": retryable},
            "request_id": request_id,
        },
        status_code,
        request_id,
    )


def _json_response(payload: dict[str, object], status_code: int, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={REQUEST_ID_HEADER: request_id},
    )
