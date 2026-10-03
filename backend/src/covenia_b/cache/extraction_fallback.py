"""Failure-only cache fallback for validated candidate extractions.

This module is intentionally a ``ModelProvider`` decorator.  It never caches
``AnalyzeCaseResponse`` or any accountability/decision projection, so the
analysis service still recalculates policy, time, human edits, and shipment
events for every request that consumes a fallback candidate.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from covenia_b.domain.types import CandidateExtraction, SanitizedModelInput
from covenia_b.model.extraction import CandidateSchemaError, validate_candidate_schema
from covenia_b.model.source_validation import SourceValidationError, validate_candidate_sources
from covenia_b.ports.contracts import ExtractionStore, ModelProvider
from covenia_b.ports.errors import ExtractionStoreUnavailable, ModelUnavailable
from covenia_b.privacy.sanitizer import redact_text

_CACHE_FORMAT_VERSION = "covenia-b-extraction-cache-v1"
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_MAX_SAFE_VALUE_LENGTH = 512
_MAX_SAFE_TEXT_LENGTH = 65536

CacheProviderMode = Literal["LIVE", "TEST_DOUBLE"]


class CacheFallbackReason(StrEnum):
    """Why a model failure could not safely use a cached candidate."""

    CACHE_MISS = "CACHE_MISS"
    CACHE_CORRUPT = "CACHE_CORRUPT"
    CACHE_STORE_UNAVAILABLE = "CACHE_STORE_UNAVAILABLE"
    GOVERNANCE_LOG_UNAVAILABLE = "GOVERNANCE_LOG_UNAVAILABLE"
    REQUEST_CONTEXT_MISSING = "REQUEST_CONTEXT_MISSING"
    UNSAFE_CACHE_INPUT = "UNSAFE_CACHE_INPUT"


class CacheFallbackUnavailable(ModelUnavailable):
    """A provider failure had no auditable, valid candidate fallback."""

    code = "EXTRACTION_CACHE_FALLBACK_UNAVAILABLE"

    def __init__(
        self,
        *,
        reason: CacheFallbackReason,
        upstream_failure: ModelUnavailable,
    ) -> None:
        super().__init__(
            "model extraction failed and no safe cached candidate was available "
            f"({reason.value})"
        )
        self.reason = reason
        self.upstream_failure_code = _safe_failure_code(upstream_failure)
        self.retryable = bool(getattr(upstream_failure, "retryable", True))


@dataclass(frozen=True, slots=True)
class CacheRequestContext:
    """Per-request audit binding; it is never included in the cache key."""

    request_id: str
    scope: str

    def __post_init__(self) -> None:
        _require_safe_value(self.request_id, field="request_id")
        _require_safe_value(self.scope, field="scope")


@dataclass(frozen=True, slots=True)
class CacheVersionSet:
    """Every behavior-affecting version that must invalidate an extraction."""

    model_id: str
    model_revision: str
    prompt_version: str
    schema_version: str
    policy_version: str

    def __post_init__(self) -> None:
        for field in (
            "model_id",
            "model_revision",
            "prompt_version",
            "schema_version",
            "policy_version",
        ):
            _require_safe_value(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class CacheFallbackEvent:
    """Redacted provenance emitted only when a cached candidate is returned."""

    request_id: str
    cached_extraction_run_id: str
    cache_key_sha256: str
    scope: str
    upstream_failure_code: str
    model_id: str
    model_revision: str
    prompt_version: str
    schema_version: str
    policy_version: str
    source_count: int
    image_count: int
    cached_result: Literal[True] = True

    def to_redacted_dict(self) -> dict[str, object]:
        """Return audit-safe metadata without text, source IDs, or image bytes."""

        return {
            "event": "EXTRACTION_CACHE_FALLBACK",
            "request_id": self.request_id,
            "cached_extraction_run_id": self.cached_extraction_run_id,
            "cache_key_sha256": self.cache_key_sha256,
            "scope": self.scope,
            "upstream_failure_code": self.upstream_failure_code,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "source_count": self.source_count,
            "image_count": self.image_count,
            "cached_result": self.cached_result,
        }


@runtime_checkable
class CacheGovernanceSink(Protocol):
    """Persist a redacted fallback relation before a cached result is served."""

    def record_cache_fallback(self, event: CacheFallbackEvent) -> None: ...


class InMemoryCacheGovernanceSink:
    """Small test double that retains only redacted fallback event objects."""

    def __init__(self) -> None:
        self._events: list[CacheFallbackEvent] = []

    @property
    def events(self) -> tuple[CacheFallbackEvent, ...]:
        return tuple(self._events)

    def record_cache_fallback(self, event: CacheFallbackEvent) -> None:
        self._events.append(event)


class _UnsafeCacheInput(ValueError):
    """No key may be derived from input that is not demonstrably safe."""


def build_extraction_cache_key(
    *,
    model_input: SanitizedModelInput,
    scope: str,
    versions: CacheVersionSet,
) -> str:
    """Hash a canonical safe input fingerprint without retaining raw text.

    The digest covers normalized sanitized text, the actual content hashes of
    resolved images, source scope/IDs, and every version that can change a
    candidate or its downstream interpretation.  The canonical payload exists
    only while this function computes its SHA-256 digest.
    """

    if not isinstance(model_input, SanitizedModelInput):
        raise _UnsafeCacheInput("cache input must be a SanitizedModelInput")
    if not isinstance(model_input.images, tuple) or not isinstance(model_input.source_ids, tuple):
        raise _UnsafeCacheInput("cache input collections are invalid")
    _require_safe_value(scope, field="scope")

    payload = {
        "format": _CACHE_FORMAT_VERSION,
        "case_id": _normalise_safe_value(model_input.case_id, field="case_id"),
        "safe_text": _normalise_safe_text(model_input.redacted_text),
        "images": _image_fingerprint(model_input),
        "scope": _normalise_safe_value(scope, field="scope"),
        "source_ids": [
            _normalise_safe_value(source_id, field="source_id")
            for source_id in model_input.source_ids
        ],
        "versions": {
            "model_id": _normalise_safe_value(versions.model_id, field="model_id"),
            "model_revision": _normalise_safe_value(
                versions.model_revision,
                field="model_revision",
            ),
            "prompt_version": _normalise_safe_value(
                versions.prompt_version,
                field="prompt_version",
            ),
            "schema_version": _normalise_safe_value(
                versions.schema_version,
                field="schema_version",
            ),
            "policy_version": _normalise_safe_value(
                versions.policy_version,
                field="policy_version",
            ),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CachingExtractionProvider:
    """Use a valid cached candidate only after an upstream model failure.

    A caller must bind a request context around each call that may use cache:

    ``with provider.request_context(request_id="req-1", scope="NORMAL")``.

    This keeps the cache key independent of the request ID while ensuring a
    served fallback records the current request alongside the original model
    extraction run ID.  ``LIVE`` mode always bypasses both cache reads and
    writes, even when ``cache_enabled`` is true.
    """

    def __init__(
        self,
        *,
        upstream: ModelProvider,
        store: ExtractionStore,
        versions: CacheVersionSet,
        provider_mode: CacheProviderMode = "TEST_DOUBLE",
        cache_enabled: bool = True,
        governance_sink: CacheGovernanceSink | None = None,
    ) -> None:
        if provider_mode not in {"LIVE", "TEST_DOUBLE"}:
            raise ValueError("provider_mode must be LIVE or TEST_DOUBLE")
        if not isinstance(cache_enabled, bool):
            raise ValueError("cache_enabled must be a bool")
        self._upstream = upstream
        self._store = store
        self._versions = versions
        self._provider_mode = provider_mode
        self._cache_enabled = cache_enabled and provider_mode != "LIVE"
        if self._cache_enabled and governance_sink is None:
            raise ValueError("a governance sink is required when cache fallback is enabled")
        self._governance_sink = governance_sink
        self._context: ContextVar[CacheRequestContext | None] = ContextVar(
            "covenia_b_cache_request_context",
            default=None,
        )

    @property
    def cache_enabled(self) -> bool:
        """Whether this provider can read or write a cache in its current mode."""

        return self._cache_enabled

    @contextmanager
    def request_context(self, *, request_id: str, scope: str) -> Iterator[CacheRequestContext]:
        """Bind the request relation required for safe fallback governance."""

        context = CacheRequestContext(request_id=request_id, scope=scope)
        token = self._context.set(context)
        try:
            yield context
        finally:
            self._context.reset(token)

    async def extract_for_request(
        self,
        model_input: SanitizedModelInput,
        *,
        request_id: str,
        scope: str,
    ) -> CandidateExtraction:
        """Convenience entry point for callers outside an existing context."""

        with self.request_context(request_id=request_id, scope=scope):
            return await self.extract(model_input)

    def cache_key_for(self, model_input: SanitizedModelInput, *, scope: str) -> str:
        """Expose the safe digest for an ExtractionStore adapter or a test."""

        return build_extraction_cache_key(
            model_input=model_input,
            scope=scope,
            versions=self._versions,
        )

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction:
        """Call upstream first; cache is strictly a model-failure fallback."""

        context = self._context.get()
        cache_key, blocked_reason = self._cache_key_or_reason(
            model_input=model_input,
            context=context,
        )
        try:
            candidate = await self._upstream.extract(model_input)
        except ModelUnavailable as upstream_failure:
            return self._fallback_after_model_failure(
                model_input=model_input,
                context=context,
                cache_key=cache_key,
                blocked_reason=blocked_reason,
                upstream_failure=upstream_failure,
            )

        if cache_key is not None and self._is_cacheable_candidate(candidate, model_input):
            try:
                # Do not retain a mutable provider-owned object in an adapter.
                self._store.put(cache_key=cache_key, candidate=copy.deepcopy(candidate))
            except ExtractionStoreUnavailable:
                # A healthy live extraction must not fail because optional DR
                # persistence is unavailable.  The next model failure reports
                # an explicit cache-store fallback failure instead.
                pass
        return candidate

    def _cache_key_or_reason(
        self,
        *,
        model_input: SanitizedModelInput,
        context: CacheRequestContext | None,
    ) -> tuple[str | None, CacheFallbackReason | None]:
        if not self._cache_enabled:
            return None, None
        if context is None:
            return None, CacheFallbackReason.REQUEST_CONTEXT_MISSING
        try:
            return self.cache_key_for(model_input, scope=context.scope), None
        except _UnsafeCacheInput:
            return None, CacheFallbackReason.UNSAFE_CACHE_INPUT

    def _fallback_after_model_failure(
        self,
        *,
        model_input: SanitizedModelInput,
        context: CacheRequestContext | None,
        cache_key: str | None,
        blocked_reason: CacheFallbackReason | None,
        upstream_failure: ModelUnavailable,
    ) -> CandidateExtraction:
        if not self._cache_enabled:
            raise upstream_failure
        if blocked_reason is not None or context is None or cache_key is None:
            raise CacheFallbackUnavailable(
                reason=blocked_reason or CacheFallbackReason.REQUEST_CONTEXT_MISSING,
                upstream_failure=upstream_failure,
            ) from None
        try:
            cached = self._store.get(case_id=model_input.case_id, cache_key=cache_key)
        except ExtractionStoreUnavailable:
            raise CacheFallbackUnavailable(
                reason=CacheFallbackReason.CACHE_STORE_UNAVAILABLE,
                upstream_failure=upstream_failure,
            ) from None
        if cached is None:
            raise CacheFallbackUnavailable(
                reason=CacheFallbackReason.CACHE_MISS,
                upstream_failure=upstream_failure,
            ) from None
        if not self._is_cacheable_candidate(cached, model_input):
            raise CacheFallbackUnavailable(
                reason=CacheFallbackReason.CACHE_CORRUPT,
                upstream_failure=upstream_failure,
            ) from None

        fallback = _mark_cached_result(copy.deepcopy(cached))
        event = CacheFallbackEvent(
            request_id=context.request_id,
            cached_extraction_run_id=fallback.model_metadata.run_id,
            cache_key_sha256=cache_key,
            scope=context.scope,
            upstream_failure_code=_safe_failure_code(upstream_failure),
            model_id=self._versions.model_id,
            model_revision=self._versions.model_revision,
            prompt_version=self._versions.prompt_version,
            schema_version=self._versions.schema_version,
            policy_version=self._versions.policy_version,
            source_count=len(model_input.source_ids),
            image_count=len(model_input.images),
        )
        try:
            if self._governance_sink is None:
                raise RuntimeError("cache governance sink is missing")
            self._governance_sink.record_cache_fallback(event)
        except Exception:
            raise CacheFallbackUnavailable(
                reason=CacheFallbackReason.GOVERNANCE_LOG_UNAVAILABLE,
                upstream_failure=upstream_failure,
            ) from None
        return fallback

    def _is_cacheable_candidate(
        self,
        candidate: object,
        model_input: SanitizedModelInput,
    ) -> bool:
        """Accept only a safe, current candidate—not a cached response/state."""

        try:
            validated = validate_candidate_schema(candidate, model_input)
            validate_candidate_sources(validated, model_input)
        except (CandidateSchemaError, SourceValidationError, ValueError, TypeError):
            return False
        metadata = validated.model_metadata
        if (
            metadata.model_id != self._versions.model_id
            or metadata.model_revision != self._versions.model_revision
            or metadata.prompt_version != self._versions.prompt_version
            or metadata.cached_result
        ):
            return False
        return _candidate_contains_no_detectable_pii(validated)


def _mark_cached_result(candidate: CandidateExtraction) -> CandidateExtraction:
    """Retain the origin run ID while explicitly marking this request as fallback."""

    metadata = candidate.model_metadata.model_copy(update={"cached_result": True})
    return replace(candidate, model_metadata=metadata)


def _candidate_contains_no_detectable_pii(candidate: CandidateExtraction) -> bool:
    values = [
        candidate.case_id,
        candidate.model_metadata.run_id,
        *candidate.observations,
        *candidate.candidate_promise_texts,
    ]
    values.extend(
        value
        for trace in candidate.source_trace
        for value in (trace.field, trace.source_type, trace.source_id)
    )
    try:
        return all(
            isinstance(value, str)
            and bool(value.strip())
            and redact_text(value).pii_masked_count == 0
            for value in values
        )
    except (TypeError, ValueError):
        return False


def _image_fingerprint(model_input: SanitizedModelInput) -> list[dict[str, object]]:
    images: list[dict[str, object]] = []
    for image in model_input.images:
        content_sha256 = getattr(image, "content_sha256", None)
        if not isinstance(content_sha256, str):
            raise _UnsafeCacheInput("resolved image content hash is invalid")
        content_sha256 = content_sha256.lower()
        if not _SHA256_HEX.fullmatch(content_sha256):
            raise _UnsafeCacheInput("resolved image must provide a SHA-256 content hash")
        byte_length = getattr(image, "byte_length", None)
        if (
            not isinstance(byte_length, int)
            or isinstance(byte_length, bool)
            or byte_length < 0
        ):
            raise _UnsafeCacheInput("resolved image byte length is invalid")
        images.append(
            {
                "evidence_id": _normalise_safe_value(
                    getattr(image, "evidence_id", None),
                    field="image_evidence_id",
                ),
                "content_sha256": content_sha256,
                "media_type": _normalise_safe_value(
                    getattr(image, "media_type", None),
                    field="image_media_type",
                ),
                "byte_length": byte_length,
            }
        )
    return images


def _normalise_safe_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_SAFE_TEXT_LENGTH:
        raise _UnsafeCacheInput("safe text is missing or outside the cache bound")
    if redact_text(value).pii_masked_count:
        raise _UnsafeCacheInput("cache input contains detectable PII")
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _normalise_safe_value(value: object, *, field: str) -> str:
    _require_safe_value(value, field=field)
    assert isinstance(value, str)
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _require_safe_value(value: object, *, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_SAFE_VALUE_LENGTH
        or redact_text(value).pii_masked_count
    ):
        raise _UnsafeCacheInput(f"{field} is not a safe cache value")


def _safe_failure_code(error: ModelUnavailable) -> str:
    code = getattr(error, "code", type(error).__name__)
    if not isinstance(code, str) or not code.strip() or redact_text(code).pii_masked_count:
        return "MODEL_UNAVAILABLE"
    return _normalise_safe_value(code, field="upstream_failure_code")
