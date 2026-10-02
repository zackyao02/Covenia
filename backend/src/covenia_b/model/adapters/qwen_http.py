"""Bounded OpenAI-compatible HTTP adapter for the frozen Qwen2-VL model.

The adapter serializes already-sanitized chat text and verified in-memory image
bytes.  It never dereferences browser URLs and never turns model output into
server-owned evidence, responsibility, activation, or rule conclusions.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import ssl
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urlsplit
from uuid import uuid4

from pydantic import ValidationError

from covenia_b.domain.types import (
    CandidateExtraction,
    ModelMetadata,
    ResolvedImage,
    SanitizedModelInput,
    SourceTrace,
)
from covenia_b.images import ProviderImageInput
from covenia_b.model.provider import (
    LOCKED_MODEL_ID,
    AsyncHttpTransport,
    HttpRequest,
    HttpResponse,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelIdentityMismatch,
    ModelProviderHttpError,
    ModelRateLimitError,
    ModelRequestCancelled,
    ModelRequestRejected,
    ModelRequestTimeout,
    ModelResponseInvalid,
    ProviderResult,
    ProviderRunMetadata,
    TransportDisconnected,
    TransportProtocolError,
    TransportTimeout,
    UsageStatus,
)
from covenia_b.observability import MeasurementConfigurationError, ProviderUsage

_SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}\Z")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_CANDIDATE_KEYS = frozenset({"observations", "source_trace", "candidate_promise_texts"})
_TRACE_KEYS = frozenset({"field", "source_type", "source_id"})
_MAX_CANDIDATE_ITEMS = 256
_MAX_CANDIDATE_TEXT_CHARS = 8192

ImagePayloadLoader = Callable[[ResolvedImage], ProviderImageInput]
MonotonicClock = Callable[[], float]
RunIdFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class QwenHttpConfig:
    """Immutable deployment identity and resource limits for one adapter."""

    endpoint: str
    model_revision: str
    prompt_version: str
    deployment_id: str
    system_prompt: str
    api_key: str | None = field(default=None, repr=False)
    model_id: str = LOCKED_MODEL_ID
    default_timeout_seconds: float = 30.0
    max_concurrency: int = 4
    max_images: int = 8
    max_image_bytes: int = 8 * 1024 * 1024
    max_total_image_bytes: int = 24 * 1024 * 1024
    max_image_dimension: int = 8192
    max_image_pixels: int = 32_000_000
    max_text_chars: int = 100_000
    max_request_bytes: int = 36 * 1024 * 1024
    max_response_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        _validate_endpoint(self.endpoint)
        if self.model_id != LOCKED_MODEL_ID:
            raise ValueError("model_id must use the frozen Qwen model")
        _require_safe_version(self.model_revision, "model_revision")
        _require_safe_version(self.prompt_version, "prompt_version")
        _require_safe_version(self.deployment_id, "deployment_id")
        if not isinstance(self.system_prompt, str) or not self.system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string")
        if len(self.system_prompt) > self.max_text_chars:
            raise ValueError("system_prompt exceeds max_text_chars")
        if self.api_key is not None and (
            not self.api_key
            or not self.api_key.isascii()
            or "\r" in self.api_key
            or "\n" in self.api_key
        ):
            raise ValueError("api_key must be a non-empty single-line ASCII value")
        _require_positive_finite(self.default_timeout_seconds, "default_timeout_seconds")
        for name in (
            "max_concurrency",
            "max_images",
            "max_image_bytes",
            "max_total_image_bytes",
            "max_image_dimension",
            "max_image_pixels",
            "max_text_chars",
            "max_request_bytes",
            "max_response_bytes",
        ):
            _require_positive_int(getattr(self, name), name)
        if self.max_total_image_bytes < self.max_image_bytes:
            raise ValueError("max_total_image_bytes must be at least max_image_bytes")


@dataclass(frozen=True, slots=True)
class _PreparedRequest:
    request: HttpRequest
    image_sha256s: tuple[str, ...]
    request_sha256: str


class QwenHttpProvider:
    """A frozen-model provider with optional rich transport metadata."""

    def __init__(
        self,
        config: QwenHttpConfig,
        *,
        image_loader: ImagePayloadLoader,
        transport: AsyncHttpTransport | None = None,
        monotonic: MonotonicClock = time.perf_counter,
        run_id_factory: RunIdFactory | None = None,
    ) -> None:
        self._config = config
        self._image_loader = image_loader
        self._transport = transport or AsyncHttp11Transport(
            max_response_bytes=config.max_response_bytes
        )
        self._monotonic = monotonic
        self._run_id_factory = run_id_factory or (lambda: f"qwen-{uuid4().hex}")
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    async def extract(
        self,
        model_input: SanitizedModelInput,
        *,
        timeout_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> CandidateExtraction:
        """Implement the frozen ModelProvider port and return candidate data only."""

        result = await self.extract_with_metadata(
            model_input,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
        return result.candidate

    async def extract_with_metadata(
        self,
        model_input: SanitizedModelInput,
        *,
        timeout_seconds: float | None = None,
        cancellation: asyncio.Event | None = None,
    ) -> ProviderResult:
        """Run one request under a total deadline, including concurrency queueing."""

        budget = (
            self._config.default_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        _require_positive_finite(budget, "timeout_seconds")
        if cancellation is not None and not isinstance(cancellation, asyncio.Event):
            raise TypeError("cancellation must be an asyncio.Event")

        started = self._monotonic()
        run_id = self._run_id_factory()
        if not isinstance(run_id, str) or not _SAFE_REQUEST_ID.fullmatch(run_id):
            raise ValueError("run_id_factory returned an unsafe identifier")

        try:
            async with asyncio.timeout(budget):
                return await self._with_explicit_cancellation(
                    self._execute(
                        model_input=model_input,
                        run_id=run_id,
                        budget=budget,
                        started=started,
                    ),
                    cancellation,
                )
        except TimeoutError:
            raise ModelRequestTimeout("model provider deadline exceeded") from None

    async def _execute(
        self,
        *,
        model_input: SanitizedModelInput,
        run_id: str,
        budget: float,
        started: float,
    ) -> ProviderResult:
        prepared = self._prepare_request(model_input, run_id=run_id, timeout_seconds=budget)
        try:
            async with self._semaphore:
                elapsed = max(0.0, self._monotonic() - started)
                remaining = budget - elapsed
                if remaining <= 0:
                    raise ModelRequestTimeout("model provider deadline exceeded")
                wire_request = HttpRequest(
                    url=prepared.request.url,
                    headers=prepared.request.headers,
                    body=prepared.request.body,
                    timeout_seconds=remaining,
                )
                response = await self._transport.send(wire_request)
        except ModelRequestTimeout:
            raise
        except (TransportTimeout, TimeoutError):
            raise ModelRequestTimeout("model provider deadline exceeded") from None
        except TransportProtocolError:
            raise ModelResponseInvalid("model provider returned invalid HTTP framing") from None
        except (TransportDisconnected, ConnectionError, OSError):
            raise ModelConnectionError("model provider connection failed") from None

        return self._parse_response(
            model_input=model_input,
            run_id=run_id,
            prepared=prepared,
            response=response,
            started=started,
        )

    async def _with_explicit_cancellation(
        self,
        operation_coro: Any,
        cancellation: asyncio.Event | None,
    ) -> ProviderResult:
        if cancellation is None:
            return await operation_coro
        if cancellation.is_set():
            operation_coro.close()
            raise ModelRequestCancelled("model provider request cancelled")

        operation = asyncio.create_task(operation_coro)
        cancellation_waiter = asyncio.create_task(cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                {operation, cancellation_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation in done:
                return await operation
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise ModelRequestCancelled("model provider request cancelled")
        finally:
            for task in (operation, cancellation_waiter):
                if not task.done():
                    task.cancel()
            await asyncio.gather(operation, cancellation_waiter, return_exceptions=True)

    def _prepare_request(
        self,
        model_input: SanitizedModelInput,
        *,
        run_id: str,
        timeout_seconds: float,
    ) -> _PreparedRequest:
        if not isinstance(model_input, SanitizedModelInput):
            raise ModelRequestRejected("provider requires SanitizedModelInput")
        if not isinstance(model_input.redacted_text, str) or not model_input.redacted_text.strip():
            raise ModelRequestRejected("sanitized chat text must be non-empty")
        if len(model_input.redacted_text) > self._config.max_text_chars:
            raise ModelRequestRejected("sanitized chat text exceeds the configured limit")
        if len(model_input.images) > self._config.max_images:
            raise ModelRequestRejected("image count exceeds the configured limit")

        content: list[dict[str, object]] = [
            {"type": "text", "text": model_input.redacted_text}
        ]
        image_hashes: list[str] = []
        total_image_bytes = 0
        for handle in model_input.images:
            provider_image = self._load_and_validate_image(handle)
            total_image_bytes += provider_image.byte_length
            if total_image_bytes > self._config.max_total_image_bytes:
                raise ModelRequestRejected("total image bytes exceed the configured limit")
            encoded = base64.b64encode(provider_image.content).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{provider_image.media_type};base64,{encoded}"
                    },
                }
            )
            image_hashes.append(provider_image.content_sha256)

        payload = {
            "model": self._config.model_id,
            "model_revision": self._config.model_revision,
            "messages": [
                {"role": "system", "content": self._config.system_prompt},
                {"role": "user", "content": content},
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
            "metadata": {
                "run_id": run_id,
                "prompt_version": self._config.prompt_version,
            },
        }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(body) > self._config.max_request_bytes:
            raise ModelRequestRejected("serialized request exceeds the configured limit")

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json; charset=utf-8",
            "X-Request-ID": run_id,
            "X-Model-ID": self._config.model_id,
            "X-Model-Revision": self._config.model_revision,
            "X-Prompt-Version": self._config.prompt_version,
        }
        if self._config.api_key is not None:
            headers["Authorization"] = f"Bearer {self._config.api_key}"
        return _PreparedRequest(
            request=HttpRequest(
                url=self._config.endpoint,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
            ),
            image_sha256s=tuple(image_hashes),
            request_sha256=hashlib.sha256(body).hexdigest(),
        )

    def _load_and_validate_image(self, handle: ResolvedImage) -> ProviderImageInput:
        if not isinstance(handle, ResolvedImage):
            raise ModelRequestRejected("image handle has an invalid type")
        try:
            image = self._image_loader(handle)
        except ModelRequestRejected:
            raise
        except Exception:
            raise ModelRequestRejected("verified image bytes are unavailable") from None
        if not isinstance(image, ProviderImageInput):
            raise ModelRequestRejected("image loader returned an invalid payload")
        if image.media_type not in _SUPPORTED_MEDIA_TYPES:
            raise ModelRequestRejected("image media type is unsupported")
        if image.media_type != handle.media_type:
            raise ModelRequestRejected("image media type does not match its verified handle")
        if image.byte_length != handle.byte_length or image.byte_length != len(image.content):
            raise ModelRequestRejected("image byte length does not match its verified handle")
        if image.byte_length > self._config.max_image_bytes:
            raise ModelRequestRejected("image bytes exceed the configured per-image limit")
        digest = hashlib.sha256(image.content).hexdigest()
        if digest != image.content_sha256 or digest != handle.content_sha256:
            raise ModelRequestRejected("image hash does not match its verified handle")
        if image.width <= 0 or image.height <= 0:
            raise ModelRequestRejected("image dimensions must be positive")
        if max(image.width, image.height) > self._config.max_image_dimension:
            raise ModelRequestRejected("image dimensions exceed the configured limit")
        if image.width * image.height > self._config.max_image_pixels:
            raise ModelRequestRejected("image pixels exceed the configured limit")
        return image

    def _parse_response(
        self,
        *,
        model_input: SanitizedModelInput,
        run_id: str,
        prepared: _PreparedRequest,
        response: HttpResponse,
        started: float,
    ) -> ProviderResult:
        headers = {str(name).lower(): str(value) for name, value in response.headers.items()}
        self._raise_for_status(response.status_code, headers)
        if len(response.body) > self._config.max_response_bytes:
            raise ModelResponseInvalid("model provider response exceeds the configured limit")
        content_type = headers.get("content-type")
        if content_type is not None and not content_type.lower().startswith("application/json"):
            raise ModelResponseInvalid("model provider response is not JSON")

        try:
            envelope = json.loads(response.body.decode("utf-8"))
            if not isinstance(envelope, dict):
                raise TypeError
            self._verify_identity(envelope, headers)
            raw_output = _extract_raw_output(envelope)
            candidate_payload = json.loads(raw_output)
            candidate = _parse_candidate(
                candidate_payload,
                model_input=model_input,
                run_id=run_id,
                model_revision=self._config.model_revision,
                prompt_version=self._config.prompt_version,
            )
            raw_usage = envelope.get("usage")
            if raw_usage is not None and not isinstance(raw_usage, Mapping):
                raise TypeError
            usage = ProviderUsage.from_payload(raw_usage)
            _validate_total_tokens(raw_usage, usage)
        except ModelIdentityMismatch:
            raise
        except ModelResponseInvalid:
            raise
        except (
            MeasurementConfigurationError,
            ValidationError,
            TypeError,
            ValueError,
            UnicodeError,
        ):
            raise ModelResponseInvalid(
                "model provider returned an invalid candidate response"
            ) from None

        provider_request_id = _safe_provider_request_id(
            headers.get("x-request-id") or envelope.get("id")
        )
        duration_ms = max(0, round((self._monotonic() - started) * 1000))
        metadata = ProviderRunMetadata(
            run_id=run_id,
            deployment_id=self._config.deployment_id,
            model_id=self._config.model_id,
            model_revision=self._config.model_revision,
            prompt_version=self._config.prompt_version,
            provider_request_id=provider_request_id,
            status_code=response.status_code,
            request_sha256=prepared.request_sha256,
            response_sha256=hashlib.sha256(response.body).hexdigest(),
            image_sha256s=prepared.image_sha256s,
            request_bytes=len(prepared.request.body),
            response_bytes=len(response.body),
            duration_ms=duration_ms,
            usage_status=UsageStatus.EXACT if usage is not None else UsageStatus.MISSING,
            usage=usage,
        )
        return ProviderResult(candidate=candidate, raw_output=raw_output, metadata=metadata)

    def _verify_identity(
        self,
        envelope: Mapping[str, object],
        headers: Mapping[str, str],
    ) -> None:
        if envelope.get("model") != self._config.model_id:
            raise ModelIdentityMismatch("provider model identity did not match the lock")
        revisions = [
            value
            for value in (envelope.get("model_revision"), headers.get("x-model-revision"))
            if value is not None
        ]
        if not revisions or any(value != self._config.model_revision for value in revisions):
            raise ModelIdentityMismatch("provider model revision did not match the lock")

    @staticmethod
    def _raise_for_status(status_code: int, headers: Mapping[str, str]) -> None:
        if status_code == 200:
            return
        if status_code in {401, 403}:
            raise ModelAuthenticationError("model provider authentication failed")
        if status_code == 429:
            raise ModelRateLimitError(
                retry_after_seconds=_parse_retry_after(headers.get("retry-after"))
            )
        if status_code in {408, 504}:
            raise ModelRequestTimeout("model provider deadline exceeded")
        if status_code == 413:
            raise ModelRequestRejected("model provider rejected the bounded request size")
        raise ModelProviderHttpError(status_code=status_code, retryable=status_code >= 500)


class AsyncHttp11Transport:
    """Small cancellation-aware HTTP/1.1 client with bounded response framing."""

    def __init__(self, *, max_response_bytes: int, max_header_bytes: int = 64 * 1024) -> None:
        _require_positive_int(max_response_bytes, "max_response_bytes")
        _require_positive_int(max_header_bytes, "max_header_bytes")
        self._max_response_bytes = max_response_bytes
        self._max_header_bytes = max_header_bytes

    async def send(self, request: HttpRequest) -> HttpResponse:
        parsed = _validate_endpoint(request.url)
        _require_positive_finite(request.timeout_seconds, "request.timeout_seconds")
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(request.timeout_seconds):
                ssl_context = ssl.create_default_context() if parsed.scheme == "https" else None
                reader, writer = await asyncio.open_connection(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    ssl=ssl_context,
                    server_hostname=parsed.hostname if ssl_context is not None else None,
                    limit=self._max_header_bytes,
                )
                writer.write(self._encode_request(parsed, request))
                await writer.drain()
                return await self._read_response(reader)
        except TimeoutError:
            raise TransportTimeout("HTTP transport deadline exceeded") from None
        except TransportProtocolError:
            raise
        except (OSError, EOFError, ssl.SSLError, asyncio.IncompleteReadError):
            raise TransportDisconnected("HTTP transport disconnected") from None
        finally:
            if writer is not None:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()

    def _encode_request(self, parsed: SplitResult, request: HttpRequest) -> bytes:
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        supplied = {name.lower() for name in request.headers}
        if supplied & {"host", "content-length", "connection"}:
            raise TransportProtocolError("reserved HTTP header was supplied")
        lines = [
            f"POST {path} HTTP/1.1",
            f"Host: {parsed.netloc}",
            f"Content-Length: {len(request.body)}",
            "Connection: close",
        ]
        for name, value in request.headers.items():
            if not _valid_header_name(name) or not _valid_header_value(value):
                raise TransportProtocolError("invalid HTTP request header")
            lines.append(f"{name}: {value}")
        try:
            head = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        except UnicodeEncodeError:
            raise TransportProtocolError("HTTP request headers must be ASCII") from None
        return head + request.body

    async def _read_response(self, reader: asyncio.StreamReader) -> HttpResponse:
        status_line = await self._readline(reader)
        try:
            protocol, status_text, _ = status_line.decode("iso-8859-1").rstrip("\r\n").split(
                " ", 2
            )
            status_code = int(status_text)
        except (UnicodeError, ValueError):
            raise TransportProtocolError("invalid HTTP status line") from None
        if protocol not in {"HTTP/1.0", "HTTP/1.1"} or not 100 <= status_code <= 599:
            raise TransportProtocolError("unsupported HTTP response status")

        headers: dict[str, str] = {}
        consumed = len(status_line)
        while True:
            line = await self._readline(reader)
            consumed += len(line)
            if consumed > self._max_header_bytes:
                raise TransportProtocolError("HTTP response headers exceed the limit")
            if line == b"\r\n":
                break
            try:
                name_bytes, value_bytes = line.rstrip(b"\r\n").split(b":", 1)
                name = name_bytes.decode("ascii").strip().lower()
                value = value_bytes.decode("iso-8859-1").strip()
            except (UnicodeError, ValueError):
                raise TransportProtocolError("invalid HTTP response header") from None
            if not _valid_header_name(name) or "\r" in value or "\n" in value:
                raise TransportProtocolError("invalid HTTP response header")
            headers[name] = f"{headers[name]}, {value}" if name in headers else value

        body = await self._read_body(reader, headers)
        return HttpResponse(status_code=status_code, headers=headers, body=body)

    async def _read_body(
        self,
        reader: asyncio.StreamReader,
        headers: Mapping[str, str],
    ) -> bytes:
        transfer_encoding = headers.get("transfer-encoding", "").lower()
        content_length = headers.get("content-length")
        if transfer_encoding and content_length is not None:
            raise TransportProtocolError("ambiguous HTTP response framing")
        if transfer_encoding:
            if transfer_encoding != "chunked":
                raise TransportProtocolError("unsupported HTTP transfer encoding")
            return await self._read_chunked(reader)
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                raise TransportProtocolError("invalid HTTP content length") from None
            if length < 0 or length > self._max_response_bytes:
                raise TransportProtocolError("HTTP response body exceeds the limit")
            return await reader.readexactly(length)

        chunks: list[bytes] = []
        total = 0
        while chunk := await reader.read(64 * 1024):
            total += len(chunk)
            if total > self._max_response_bytes:
                raise TransportProtocolError("HTTP response body exceeds the limit")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _read_chunked(self, reader: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            line = await self._readline(reader)
            try:
                size = int(line.split(b";", 1)[0].strip(), 16)
            except ValueError:
                raise TransportProtocolError("invalid HTTP chunk size") from None
            if size < 0 or total + size > self._max_response_bytes:
                raise TransportProtocolError("HTTP response body exceeds the limit")
            if size == 0:
                while await self._readline(reader) != b"\r\n":
                    pass
                return b"".join(chunks)
            chunk = await reader.readexactly(size)
            if await reader.readexactly(2) != b"\r\n":
                raise TransportProtocolError("invalid HTTP chunk terminator")
            chunks.append(chunk)
            total += size

    async def _readline(self, reader: asyncio.StreamReader) -> bytes:
        try:
            line = await reader.readline()
        except ValueError:
            raise TransportProtocolError("HTTP response line exceeds the limit") from None
        if not line or not line.endswith(b"\r\n"):
            raise TransportProtocolError("incomplete HTTP response line")
        return line


def _parse_candidate(
    payload: object,
    *,
    model_input: SanitizedModelInput,
    run_id: str,
    model_revision: str,
    prompt_version: str,
) -> CandidateExtraction:
    if not isinstance(payload, dict) or set(payload) != _CANDIDATE_KEYS:
        raise ModelResponseInvalid("candidate response contains missing or forbidden fields")
    observations = _strict_string_tuple(payload["observations"], field_name="observations")
    candidate_promises = _strict_string_tuple(
        payload["candidate_promise_texts"],
        field_name="candidate_promise_texts",
    )
    raw_traces = payload["source_trace"]
    if not isinstance(raw_traces, list) or len(raw_traces) > _MAX_CANDIDATE_ITEMS:
        raise ModelResponseInvalid("candidate source_trace is invalid")
    allowed_source_ids = set(model_input.source_ids)
    traces: list[SourceTrace] = []
    for raw_trace in raw_traces:
        if not isinstance(raw_trace, dict) or set(raw_trace) != _TRACE_KEYS:
            raise ModelResponseInvalid("candidate source_trace is invalid")
        if raw_trace.get("source_id") not in allowed_source_ids:
            raise ModelResponseInvalid("candidate source_trace used an unknown source")
        if any(
            not isinstance(raw_trace.get(name), str)
            or not raw_trace[name].strip()
            or len(raw_trace[name]) > _MAX_CANDIDATE_TEXT_CHARS
            for name in _TRACE_KEYS
        ):
            raise ModelResponseInvalid("candidate source_trace is invalid")
        traces.append(SourceTrace.model_validate(raw_trace))
    return CandidateExtraction(
        case_id=model_input.case_id,
        model_metadata=ModelMetadata(
            model_id=LOCKED_MODEL_ID,
            model_revision=model_revision,
            prompt_version=prompt_version,
            run_id=run_id,
            cached_result=False,
        ),
        observations=observations,
        source_trace=tuple(traces),
        candidate_promise_texts=candidate_promises,
    )


def _strict_string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_CANDIDATE_ITEMS:
        raise ModelResponseInvalid(f"candidate {field_name} is invalid")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or len(item) > _MAX_CANDIDATE_TEXT_CHARS
        for item in value
    ):
        raise ModelResponseInvalid(f"candidate {field_name} is invalid")
    return tuple(value)


def _extract_raw_output(envelope: Mapping[str, object]) -> str:
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ModelResponseInvalid("model provider response choices are invalid")
    choice = choices[0]
    if choice.get("finish_reason") not in {None, "stop"}:
        raise ModelResponseInvalid("model provider response did not finish cleanly")
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") not in {None, "assistant"}:
        raise ModelResponseInvalid("model provider response message is invalid")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ModelResponseInvalid("model provider response content is empty")
    return content


def _validate_total_tokens(
    raw_usage: Mapping[str, object] | None,
    usage: ProviderUsage | None,
) -> None:
    if raw_usage is None or usage is None or "total_tokens" not in raw_usage:
        return
    total = raw_usage["total_tokens"]
    if type(total) is not int or total != usage.input_tokens + usage.output_tokens:
        raise MeasurementConfigurationError("provider total_tokens is inconsistent")


def _safe_provider_request_id(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value) else None


def _parse_retry_after(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    return parsed if 0 <= parsed <= 86_400 else None


def _validate_endpoint(endpoint: str) -> SplitResult:
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("endpoint must be a non-empty URL")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("endpoint must be an HTTP(S) URL without credentials, query, or fragment")
    return parsed


def _require_safe_version(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_VERSION.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe, non-empty version identifier")


def _require_positive_finite(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a positive finite number")
    if not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")


def _require_positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _valid_header_name(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    token_chars = "!#$%&'*+-.^_`|~"
    return all(character.isalnum() or character in token_chars for character in value)


def _valid_header_value(value: object) -> bool:
    return isinstance(value, str) and value.isascii() and "\r" not in value and "\n" not in value


__all__ = ["AsyncHttp11Transport", "QwenHttpConfig", "QwenHttpProvider"]
