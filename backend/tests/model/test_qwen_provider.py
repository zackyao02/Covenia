from __future__ import annotations

import asyncio
import base64
import hashlib
import itertools
import json
from collections.abc import Mapping

import pytest

from covenia_b.domain.types import ResolvedImage, SanitizedModelInput
from covenia_b.images import ProviderImageInput
from covenia_b.model.adapters.qwen_http import QwenHttpConfig, QwenHttpProvider
from covenia_b.model.provider import (
    LOCKED_MODEL_ID,
    HttpRequest,
    HttpResponse,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelIdentityMismatch,
    ModelRateLimitError,
    ModelRequestCancelled,
    ModelRequestRejected,
    ModelRequestTimeout,
    ModelResponseInvalid,
    TransportDisconnected,
    UsageStatus,
)
from covenia_b.ports.contracts import ModelProvider

MODEL_REVISION = "qwen2-vl-2b-rev-a1b2c3"
PROMPT_VERSION = "candidate-extraction-v1"
ENDPOINT = "https://qwen.internal.example/v1/chat/completions"
SECRET = "sk-test-secret-never-log"

# Two complete one-pixel PNG files.  The protocol assertions decode the exact
# data URLs and compare these real image bytes, rather than checking filenames.
PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42Y"
    "AAAAASUVORK5CYII="
)
PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z"
    "lLkAAAAASUVORK5CYII="
)


class ScriptedTransport:
    def __init__(self, outcome: HttpResponse | BaseException) -> None:
        self.outcome = outcome
        self.requests: list[HttpRequest] = []

    async def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class HangingTransport:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def send(self, request: HttpRequest) -> HttpResponse:
        del request
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


class GateTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def send(self, request: HttpRequest) -> HttpResponse:
        del request
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.response


class ConcurrencyTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.active = 0
        self.max_active = 0

    async def send(self, request: HttpRequest) -> HttpResponse:
        del request
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.02)
            return self.response
        finally:
            self.active -= 1


def test_multimodal_protocol_sends_chat_and_exact_image_bytes_and_parses_metadata() -> None:
    image_a = _image("img-a", PNG_A)
    image_b = _image("img-b", PNG_B)
    transport = ScriptedTransport(_success_response())
    provider = _provider(transport, images={"img-a": image_a[1], "img-b": image_b[1]})
    model_input = _model_input(
        case_id="DEMO_001",
        images=(image_a[0], image_b[0]),
        text="customer: [PHONE] package arrived damaged\nagent: please send photos",
    )

    result = asyncio.run(provider.extract_with_metadata(model_input))

    assert isinstance(provider, ModelProvider)
    assert result.candidate.case_id == "DEMO_001"
    assert result.candidate.candidate_only is True
    assert result.candidate.model_metadata.model_id == LOCKED_MODEL_ID
    assert result.candidate.model_metadata.model_revision == MODEL_REVISION
    assert result.candidate.observations == ("outer package appears damaged",)
    assert result.candidate.source_trace[0].source_id == "chat-1"
    assert result.raw_output == _candidate_output()

    request = transport.requests[0]
    payload = json.loads(request.body)
    assert payload["model"] == LOCKED_MODEL_ID
    assert payload["model_revision"] == MODEL_REVISION
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    user_parts = payload["messages"][1]["content"]
    assert user_parts[0] == {"type": "text", "text": model_input.redacted_text}
    assert [_decode_data_url(part["image_url"]["url"]) for part in user_parts[1:]] == [
        PNG_A,
        PNG_B,
    ]
    assert all(
        part["image_url"]["url"].startswith("data:image/png;base64,")
        for part in user_parts[1:]
    )
    assert b"DEMO_001" not in request.body

    metadata = result.metadata
    assert metadata.model_id == LOCKED_MODEL_ID
    assert metadata.model_revision == MODEL_REVISION
    assert metadata.prompt_version == PROMPT_VERSION
    assert metadata.provider_request_id == "provider-request-123"
    assert metadata.usage_status is UsageStatus.EXACT
    assert metadata.usage is not None
    assert (metadata.usage.input_tokens, metadata.usage.output_tokens) == (11, 7)
    assert metadata.image_sha256s == (
        hashlib.sha256(PNG_A).hexdigest(),
        hashlib.sha256(PNG_B).hexdigest(),
    )
    assert metadata.request_sha256 == hashlib.sha256(request.body).hexdigest()
    assert metadata.response_bytes == len(transport.outcome.body)
    audit_text = json.dumps(metadata.to_audit_payload(), sort_keys=True)
    assert SECRET not in audit_text
    assert ENDPOINT not in audit_text
    assert result.raw_output not in audit_text


def test_401_is_distinct_and_never_leaks_secret_or_provider_body() -> None:
    marker = "provider-body-secret-marker"
    transport = ScriptedTransport(
        HttpResponse(
            status_code=401,
            headers={"content-type": "application/json"},
            body=json.dumps({"detail": marker}).encode(),
        )
    )
    provider = _provider(transport)

    with pytest.raises(ModelAuthenticationError) as captured:
        asyncio.run(provider.extract(_model_input()))

    rendered = str(captured.value)
    assert captured.value.code == "AUTHENTICATION_FAILED"
    assert SECRET not in rendered
    assert marker not in rendered
    assert ENDPOINT not in rendered


def test_429_preserves_only_bounded_retry_after_metadata() -> None:
    transport = ScriptedTransport(
        HttpResponse(status_code=429, headers={"retry-after": "7"}, body=b"private body")
    )
    provider = _provider(transport)

    with pytest.raises(ModelRateLimitError) as captured:
        asyncio.run(provider.extract(_model_input()))

    assert captured.value.code == "RATE_LIMITED"
    assert captured.value.retry_after_seconds == 7
    assert "private body" not in str(captured.value)


def test_total_deadline_cancels_an_inflight_protocol_call() -> None:
    transport = HangingTransport()
    provider = _provider(transport)

    with pytest.raises(ModelRequestTimeout) as captured:
        asyncio.run(provider.extract(_model_input(), timeout_seconds=0.01))

    assert captured.value.code == "TIMEOUT"
    assert transport.cancelled is True


def test_explicit_cancellation_stops_an_inflight_protocol_call() -> None:
    async def scenario() -> None:
        transport = HangingTransport()
        provider = _provider(transport)
        cancellation = asyncio.Event()
        task = asyncio.create_task(provider.extract(_model_input(), cancellation=cancellation))
        await transport.started.wait()
        cancellation.set()
        with pytest.raises(ModelRequestCancelled) as captured:
            await task
        assert captured.value.code == "CANCELLED"
        assert transport.cancelled is True

    asyncio.run(scenario())


def test_disconnect_is_distinct_from_timeout_and_invalid_output() -> None:
    provider = _provider(ScriptedTransport(TransportDisconnected("socket closed")))

    with pytest.raises(ModelConnectionError) as captured:
        asyncio.run(provider.extract(_model_input()))

    assert captured.value.code == "CONNECTION_FAILED"
    assert "socket closed" not in str(captured.value)


def test_missing_usage_is_disclosed_without_estimation() -> None:
    provider = _provider(ScriptedTransport(_success_response(usage=None)))

    result = asyncio.run(provider.extract_with_metadata(_model_input()))

    assert result.metadata.usage_status is UsageStatus.MISSING
    assert result.metadata.usage is None
    assert result.metadata.to_audit_payload()["usage"] is None


def test_partial_usage_is_invalid_instead_of_fabricated() -> None:
    provider = _provider(
        ScriptedTransport(_success_response(usage={"prompt_tokens": 5}))
    )

    with pytest.raises(ModelResponseInvalid):
        asyncio.run(provider.extract(_model_input()))


def test_concurrency_limit_bounds_simultaneous_provider_calls() -> None:
    async def scenario() -> None:
        transport = ConcurrencyTransport(_success_response())
        provider = _provider(transport, max_concurrency=2)
        candidates = await asyncio.gather(
            *(
                provider.extract(_model_input(case_id=f"case-{index}"))
                for index in range(6)
            )
        )
        assert transport.max_active == 2
        assert [candidate.case_id for candidate in candidates] == [
            f"case-{index}" for index in range(6)
        ]

    asyncio.run(scenario())


def test_total_deadline_includes_waiting_for_a_concurrency_slot() -> None:
    async def scenario() -> None:
        transport = GateTransport(_success_response())
        provider = _provider(transport, max_concurrency=1)
        first = asyncio.create_task(provider.extract(_model_input(case_id="first")))
        await transport.started.wait()
        with pytest.raises(ModelRequestTimeout):
            await provider.extract(_model_input(case_id="queued"), timeout_seconds=0.01)
        assert transport.calls == 1
        transport.release.set()
        assert (await first).case_id == "first"

    asyncio.run(scenario())


def test_verified_image_limits_and_hashes_are_enforced_before_transport() -> None:
    handle, image = _image("img-a", PNG_A)
    transport = ScriptedTransport(_success_response())
    provider = _provider(
        transport,
        images={"img-a": image},
        max_image_bytes=8,
        max_total_image_bytes=8,
    )

    with pytest.raises(ModelRequestRejected):
        asyncio.run(provider.extract(_model_input(images=(handle,))))

    assert transport.requests == []


def test_response_must_prove_exact_model_id_and_revision() -> None:
    wrong_model = _success_response(model="another/model")
    missing_revision = _success_response(revision=None)

    for response in (wrong_model, missing_revision):
        provider = _provider(ScriptedTransport(response))
        with pytest.raises(ModelIdentityMismatch):
            asyncio.run(provider.extract(_model_input()))


def test_candidate_parser_rejects_server_owned_business_conclusions() -> None:
    forbidden = json.loads(_candidate_output())
    forbidden["responsibility"] = "BRAND"
    provider = _provider(
        ScriptedTransport(_success_response(candidate_payload=forbidden))
    )

    with pytest.raises(ModelResponseInvalid):
        asyncio.run(provider.extract(_model_input()))


def _provider(
    transport: object,
    *,
    images: Mapping[str, ProviderImageInput] | None = None,
    **config_overrides: object,
) -> QwenHttpProvider:
    image_map = {} if images is None else dict(images)
    counter = itertools.count(1)
    config_values: dict[str, object] = {
        "endpoint": ENDPOINT,
        "model_revision": MODEL_REVISION,
        "prompt_version": PROMPT_VERSION,
        "deployment_id": "protocol-double-deployment",
        "system_prompt": "Return candidate-only JSON using the supplied sanitized chat and images.",
        "api_key": SECRET,
    }
    config_values.update(config_overrides)
    return QwenHttpProvider(
        QwenHttpConfig(**config_values),
        image_loader=lambda handle: image_map[handle.evidence_id],
        transport=transport,
        run_id_factory=lambda: f"qwen-run-{next(counter)}",
    )


def _model_input(
    *,
    case_id: str = "case-neutral",
    images: tuple[ResolvedImage, ...] = (),
    text: str = "customer: the package is damaged",
) -> SanitizedModelInput:
    return SanitizedModelInput(
        case_id=case_id,
        redacted_text=text,
        images=images,
        source_ids=("chat-1",),
    )


def _image(
    evidence_id: str,
    content: bytes,
) -> tuple[ResolvedImage, ProviderImageInput]:
    digest = hashlib.sha256(content).hexdigest()
    image = ProviderImageInput(
        content=content,
        media_type="image/png",
        content_sha256=digest,
        byte_length=len(content),
        width=1,
        height=1,
    )
    handle = ResolvedImage(
        evidence_id=evidence_id,
        media_type=image.media_type,
        content_sha256=digest,
        byte_length=len(content),
    )
    return handle, image


def _candidate_output() -> str:
    return json.dumps(
        {
            "observations": ["outer package appears damaged"],
            "source_trace": [
                {"field": "observations[0]", "source_type": "CHAT", "source_id": "chat-1"}
            ],
            "candidate_promise_texts": ["please send photos"],
        },
        separators=(",", ":"),
    )


_DEFAULT_USAGE = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


def _success_response(
    *,
    candidate_payload: object | None = None,
    usage: Mapping[str, object] | None = _DEFAULT_USAGE,
    model: str = LOCKED_MODEL_ID,
    revision: str | None = MODEL_REVISION,
) -> HttpResponse:
    output = _candidate_output() if candidate_payload is None else json.dumps(candidate_payload)
    envelope: dict[str, object] = {
        "id": "provider-request-123",
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": output},
                "finish_reason": "stop",
            }
        ],
    }
    if revision is not None:
        envelope["model_revision"] = revision
    if usage is not None:
        envelope["usage"] = dict(usage)
    headers = {"content-type": "application/json"}
    if revision is not None:
        headers["x-model-revision"] = revision
    return HttpResponse(
        status_code=200,
        headers=headers,
        body=json.dumps(envelope, separators=(",", ":")).encode(),
    )


def _decode_data_url(value: str) -> bytes:
    prefix, encoded = value.split(",", 1)
    assert prefix == "data:image/png;base64"
    return base64.b64decode(encoded, validate=True)
