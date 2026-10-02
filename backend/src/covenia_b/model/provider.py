"""Provider-side transport contracts and safe, provider-specific failures.

The frozen :class:`~covenia_b.ports.contracts.ModelProvider` port intentionally
returns only a candidate extraction.  This module adds an optional richer result
for callers that need exact provider usage and auditable transport metadata; it
does not add business evidence, responsibility, or rule decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from covenia_b.domain.types import CandidateExtraction
from covenia_b.observability import LOCKED_MODEL_ID, ProviderUsage
from covenia_b.ports.errors import ModelOutputInvalid, ModelUnavailable


class UsageStatus(StrEnum):
    """Whether token usage came from a complete provider response."""

    EXACT = "EXACT"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class ProviderRunMetadata:
    """Safe request-scoped facts suitable for a later governance record.

    Raw prompts, image bytes, authorization headers, endpoint URLs, and model
    output are deliberately absent.  Hashes bind this record to the exact wire
    payload without turning the adapter into a business evidence store.
    """

    run_id: str
    deployment_id: str
    model_id: str
    model_revision: str
    prompt_version: str
    provider_request_id: str | None
    status_code: int
    request_sha256: str
    response_sha256: str
    image_sha256s: tuple[str, ...]
    request_bytes: int
    response_bytes: int
    duration_ms: int
    usage_status: UsageStatus
    usage: ProviderUsage | None

    def to_audit_payload(self) -> dict[str, object]:
        """Return only redacted, verifiable metadata."""

        return {
            "run_id": self.run_id,
            "deployment_id": self.deployment_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "prompt_version": self.prompt_version,
            "provider_request_id": self.provider_request_id,
            "status_code": self.status_code,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "image_sha256s": list(self.image_sha256s),
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "duration_ms": self.duration_ms,
            "usage_status": self.usage_status.value,
            "usage": (
                None
                if self.usage is None
                else {
                    "input_tokens": self.usage.input_tokens,
                    "output_tokens": self.usage.output_tokens,
                }
            ),
        }


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Candidate output plus in-memory raw output and safe run metadata."""

    candidate: CandidateExtraction
    raw_output: str
    metadata: ProviderRunMetadata


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """One bounded HTTP request passed to an async transport."""

    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Raw HTTP response returned by a transport or protocol double."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class AsyncHttpTransport(Protocol):
    """Cancellation-aware seam used by the real transport and test doubles."""

    async def send(self, request: HttpRequest) -> HttpResponse: ...


class TransportTimeout(TimeoutError):
    """The transport exhausted its assigned request budget."""


class TransportDisconnected(ConnectionError):
    """The connection ended before a complete response was received."""


class TransportProtocolError(ValueError):
    """The remote peer returned malformed or unbounded HTTP framing."""


class ModelAuthenticationError(ModelUnavailable):
    """The configured service rejected authentication."""

    code = "AUTHENTICATION_FAILED"
    retryable = False


class ModelRateLimitError(ModelUnavailable):
    """The configured service reported a rate limit."""

    code = "RATE_LIMITED"
    retryable = True

    def __init__(self, *, retry_after_seconds: int | None) -> None:
        super().__init__("model provider rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class ModelRequestTimeout(ModelUnavailable):
    """The total provider budget expired, including queue wait time."""

    code = "TIMEOUT"
    retryable = True


class ModelConnectionError(ModelUnavailable):
    """The configured service disconnected or could not be reached."""

    code = "CONNECTION_FAILED"
    retryable = True


class ModelRequestCancelled(ModelUnavailable):
    """An explicit caller cancellation token stopped the request."""

    code = "CANCELLED"
    retryable = False


class ModelRequestRejected(ModelUnavailable):
    """A bounded adapter precondition or provider request was rejected."""

    code = "REQUEST_REJECTED"
    retryable = False


class ModelProviderHttpError(ModelUnavailable):
    """A non-special provider HTTP status was returned."""

    code = "PROVIDER_HTTP_ERROR"

    def __init__(self, *, status_code: int, retryable: bool) -> None:
        super().__init__(f"model provider returned HTTP status {status_code}")
        self.status_code = status_code
        self.retryable = retryable


class ModelIdentityMismatch(ModelOutputInvalid):
    """The response did not prove the exact locked model and revision."""

    code = "MODEL_IDENTITY_MISMATCH"
    retryable = False


class ModelResponseInvalid(ModelOutputInvalid):
    """The response could not be parsed into the candidate-only contract."""

    code = "MODEL_RESPONSE_INVALID"
    retryable = False


__all__ = [
    "LOCKED_MODEL_ID",
    "AsyncHttpTransport",
    "HttpRequest",
    "HttpResponse",
    "ModelAuthenticationError",
    "ModelConnectionError",
    "ModelIdentityMismatch",
    "ModelProviderHttpError",
    "ModelRateLimitError",
    "ModelRequestCancelled",
    "ModelRequestRejected",
    "ModelRequestTimeout",
    "ModelResponseInvalid",
    "ProviderResult",
    "ProviderRunMetadata",
    "TransportDisconnected",
    "TransportProtocolError",
    "TransportTimeout",
    "UsageStatus",
]
