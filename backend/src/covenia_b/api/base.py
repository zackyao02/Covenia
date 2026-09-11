"""Transport-level seams shared by future API modules."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-Id"


class ApiError(Exception):
    """A neutral error envelope; business error codes belong to later batches."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 500,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable

    def as_payload(self, request_id: str) -> dict[str, object]:
        """Return the generic transport envelope without exposing configuration."""

        return {
            "data": None,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            },
            "request_id": request_id,
        }


def normalize_request_id(value: str | None) -> str:
    """Keep valid client UUIDs and generate a new UUID for absent or invalid input."""

    if value is not None:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return str(uuid4())


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    """Serialize an ``ApiError`` with the request ID assigned by middleware."""

    request_id = getattr(request.state, "request_id", normalize_request_id(None))
    return JSONResponse(status_code=error.status_code, content=error.as_payload(request_id))


def install_api_seams(app: FastAPI) -> None:
    """Install request-ID and exception seams without registering a business route."""

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.add_exception_handler(ApiError, api_error_handler)
