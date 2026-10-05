"""Collect exact runtime metrics without retaining raw model inputs.

The four public ``RuntimeMetrics`` fields are intentionally small.  This
module retains the surrounding audit provenance in a separate structured
record: model and prompt versions, safe source references, PII hit counts,
cache state, and the way tokens were measured.  It never accepts image bytes
or a prompt as a log field.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns
from typing import Final, Literal, Protocol

from covenia_b.domain.types import RuntimeMetrics
from covenia_b.ports.errors import MetricsUnavailable

LOCKED_MODEL_ID: Final[str] = "qwen3-vl-plus"
_EndpointName = Literal["analyze", "evaluate", "approve", "shipment"]
_SourcePhase = Literal["MODEL", "RULE"]
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_SAFE_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_PHONE_ONLY = re.compile(r"^1[3-9]\d{9}$")


class GovernanceError(ValueError):
    """Base error for an invalid or unsafe observability operation."""


class MeasurementConfigurationError(GovernanceError):
    """Raised when an alleged exact measurement cannot be proven exact."""


class DuplicateGovernanceEventError(GovernanceError):
    """Raised when a retry attempts to count the same event identifier twice."""


class AttemptAlreadyFinishedError(GovernanceError):
    """Raised when one model attempt is completed or failed more than once."""


class GovernanceLogWriteError(MetricsUnavailable):
    """A governance audit record could not be durably accepted by its sink."""


class InputSourceKind(StrEnum):
    """Safe source classes that can be correlated without logging source text."""

    CHAT = "CHAT"
    IMAGE = "IMAGE"
    ORDER = "ORDER"
    TICKET = "TICKET"
    DATASET = "DATASET"
    RULE = "RULE"
    CACHE = "CACHE"
    SERVICE = "SERVICE"


class CacheStatus(StrEnum):
    """Whether the record is associated with a cache path."""

    MISS = "MISS"
    HIT = "HIT"
    FALLBACK = "FALLBACK"
    BYPASSED = "BYPASSED"


class _EventKind(StrEnum):
    MODEL_ATTEMPT = "MODEL_ATTEMPT"
    MODEL_FAILURE = "MODEL_FAILURE"
    CACHE_HIT = "CACHE_HIT"
    CACHE_FALLBACK = "CACHE_FALLBACK"
    RULE_EVALUATION = "RULE_EVALUATION"
    PORT_METRICS = "PORT_METRICS"


class _TokenMeasurementSource(StrEnum):
    PROVIDER_USAGE = "PROVIDER_USAGE"
    TOKENIZER_ACTUAL = "TOKENIZER_ACTUAL"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PORT_SUPPLIED = "PORT_SUPPLIED"


class _TokenMeasurementStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    DECLARED_BY_CALLER = "DECLARED_BY_CALLER"


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise MeasurementConfigurationError(f"{field_name} must be a non-negative integer")
    return value


def _require_safe_identifier(value: str, field_name: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value) or _PHONE_ONLY.fullmatch(value):
        raise GovernanceError(f"{field_name} must be an opaque, non-PII identifier")
    return value


def _require_safe_version(value: str, field_name: str) -> str:
    if not _SAFE_VERSION.fullmatch(value):
        raise GovernanceError(f"{field_name} must be a version label, not content")
    return value


def _zero_metrics() -> RuntimeMetrics:
    return RuntimeMetrics(
        input_tokens=0,
        output_tokens=0,
        inference_latency_ms=0,
        rule_substitution_count=0,
    )


def _add_metrics(left: RuntimeMetrics, right: RuntimeMetrics) -> RuntimeMetrics:
    return RuntimeMetrics(
        input_tokens=left.input_tokens + right.input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        inference_latency_ms=left.inference_latency_ms + right.inference_latency_ms,
        rule_substitution_count=left.rule_substitution_count + right.rule_substitution_count,
    )


@dataclass(frozen=True, slots=True)
class SafeInputSource:
    """A source kind plus a one-way reference digest, never a raw source value."""

    phase: _SourcePhase
    kind: InputSourceKind
    reference_sha256: str

    def __post_init__(self) -> None:
        if self.phase not in {"MODEL", "RULE"}:
            raise GovernanceError("input source phase must be MODEL or RULE")
        if not _SHA256_HEX.fullmatch(self.reference_sha256):
            raise GovernanceError("input source reference must be a lowercase SHA-256 digest")

    @classmethod
    def from_identifier(
        cls,
        *,
        phase: _SourcePhase,
        kind: InputSourceKind,
        identifier: str,
    ) -> SafeInputSource:
        """Hash a source reference immediately so the raw identifier is not retained."""

        if not isinstance(identifier, str) or not identifier:
            raise GovernanceError("source identifier must be a non-empty string")
        return cls(
            phase=phase,
            kind=kind,
            reference_sha256=sha256(identifier.encode("utf-8")).hexdigest(),
        )

    def to_payload(self) -> dict[str, str]:
        return {
            "phase": self.phase,
            "kind": self.kind.value,
            "reference_sha256": self.reference_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """The auditable model and prompt identity for a model-bound request."""

    model_id: str
    model_revision: str | None
    prompt_version: str

    def __post_init__(self) -> None:
        if self.model_id != LOCKED_MODEL_ID:
            raise GovernanceError("model_id must use the frozen model")
        if self.model_revision is not None:
            _require_safe_version(self.model_revision, "model_revision")
        _require_safe_version(self.prompt_version, "prompt_version")

    def to_payload(self) -> dict[str, str | None]:
        return {
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True, slots=True)
class GovernanceContext:
    """Safe, request-scoped metadata shared by all events in one operation."""

    request_id: str
    run_id: str
    endpoint: _EndpointName
    input_sources: tuple[SafeInputSource, ...]
    pii_masked_count: int
    image_hashes: tuple[str, ...] = ()
    model: ModelIdentity | None = None

    def __post_init__(self) -> None:
        _require_safe_identifier(self.request_id, "request_id")
        _require_safe_identifier(self.run_id, "run_id")
        if self.endpoint not in {"analyze", "evaluate", "approve", "shipment"}:
            raise GovernanceError("endpoint is not part of the frozen MetricsSink contract")
        if not self.input_sources:
            raise GovernanceError("at least one safe input source is required")
        if any(not isinstance(source, SafeInputSource) for source in self.input_sources):
            raise GovernanceError("input_sources must contain SafeInputSource values")
        _require_nonnegative_int(self.pii_masked_count, "pii_masked_count")
        if len(set(self.image_hashes)) != len(self.image_hashes):
            raise GovernanceError("image_hashes must not contain duplicate values")
        if any(not _SHA256_HEX.fullmatch(image_hash) for image_hash in self.image_hashes):
            raise GovernanceError("image_hashes must contain lowercase SHA-256 digests only")

    def to_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "endpoint": self.endpoint,
            "model": None if self.model is None else self.model.to_payload(),
            "input_sources": [source.to_payload() for source in self.input_sources],
            "image_hashes": list(self.image_hashes),
            "pii_masked_count": self.pii_masked_count,
        }


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """Exact input/output values emitted by a provider, without a guessed total."""

    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.input_tokens, "provider input_tokens")
        _require_nonnegative_int(self.output_tokens, "provider output_tokens")

    @classmethod
    def from_payload(cls, payload: Mapping[str, object] | None) -> ProviderUsage | None:
        """Normalize only complete, explicit provider input/output usage pairs.

        ``total_tokens`` alone is intentionally ignored: splitting it into input
        and output would fabricate metric values.
        """

        if payload is None:
            return None
        canonical = (payload.get("input_tokens"), payload.get("output_tokens"))
        openai_style = (payload.get("prompt_tokens"), payload.get("completion_tokens"))
        if canonical == (None, None) and openai_style == (None, None):
            return None
        pair = canonical if canonical != (None, None) else openai_style
        if pair[0] is None or pair[1] is None:
            raise MeasurementConfigurationError(
                "provider usage must include both input and output tokens"
            )
        return cls(input_tokens=pair[0], output_tokens=pair[1])


class ExactTokenCounter(Protocol):
    """A tokenizer explicitly bound to the same immutable model revision."""

    model_id: str
    model_revision: str

    def count_tokens(self, text: str) -> int:
        """Return a real count for ``text`` under this tokenizer revision."""


@dataclass(frozen=True, slots=True)
class _TokenMeasurement:
    input_tokens: int
    output_tokens: int
    source: _TokenMeasurementSource
    status: _TokenMeasurementStatus

    def to_metrics(self, *, latency_ms: int) -> RuntimeMetrics:
        return RuntimeMetrics(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            inference_latency_ms=latency_ms,
            rule_substitution_count=0,
        )


@dataclass(frozen=True, slots=True)
class _GovernanceRecord:
    event_id: str
    event_kind: _EventKind
    context: GovernanceContext
    metrics: RuntimeMetrics
    request_totals: RuntimeMetrics
    token_source: _TokenMeasurementSource
    token_status: _TokenMeasurementStatus
    latency_source: str
    cache_status: CacheStatus
    fallback_reason: str | None
    failure_reason: str | None
    emitted_at: datetime

    def to_payload(self) -> dict[str, object]:
        payload = self.context.to_payload()
        payload.update(
            {
                "schema_version": "1.0",
                "event_id": self.event_id,
                "event_kind": self.event_kind.value,
                "emitted_at": self.emitted_at.isoformat().replace("+00:00", "Z"),
                "metrics": self.metrics.model_dump(mode="json"),
                "request_totals": self.request_totals.model_dump(mode="json"),
                "metric_provenance": {
                    "token_measurement_source": self.token_source.value,
                    "token_measurement_status": self.token_status.value,
                    "latency_measurement_source": self.latency_source,
                },
                "cache": {
                    "status": self.cache_status.value,
                    "fallback_reason": self.fallback_reason,
                },
                "failure_reason": self.failure_reason,
            }
        )
        return payload


class GovernanceLogSink(Protocol):
    """A sink that either accepts a complete safe audit record or raises."""

    def write(self, record: _GovernanceRecord) -> None:
        """Persist one record; returning normally means the record was accepted."""


class InMemoryGovernanceSink:
    """A deterministic sink for tests and local protocol doubles."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write(self, record: _GovernanceRecord) -> None:
        self.records.append(record.to_payload())


class JsonlGovernanceSink:
    """Append durable, line-delimited JSON governance records to one local file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, record: _GovernanceRecord) -> None:
        serialized = json.dumps(
            record.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise GovernanceLogWriteError("governance audit log write failed") from exc


class RuntimeMetricsCollector:
    """Create request-local sessions that accumulate only durably audited events."""

    def __init__(
        self,
        sink: GovernanceLogSink,
        *,
        monotonic_ns: Callable[[], int] = perf_counter_ns,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sink = sink
        self._monotonic_ns = monotonic_ns
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))

    def start_request(self, context: GovernanceContext) -> GovernanceSession:
        """Bind safe request metadata and return a structural ``MetricsSink``."""

        return GovernanceSession(
            context=context,
            sink=self._sink,
            monotonic_ns=self._monotonic_ns,
            wall_clock=self._wall_clock,
        )


class GovernanceSession:
    """A request-scoped collector and the concrete implementation of MetricsSink."""

    def __init__(
        self,
        *,
        context: GovernanceContext,
        sink: GovernanceLogSink,
        monotonic_ns: Callable[[], int],
        wall_clock: Callable[[], datetime],
    ) -> None:
        self.context = context
        self._sink = sink
        self._monotonic_ns = monotonic_ns
        self._wall_clock = wall_clock
        self._metrics = _zero_metrics()
        self._reserved_event_ids: set[str] = set()
        self._lock = threading.RLock()
        self._port_metrics_recorded = False

    @property
    def runtime_metrics(self) -> RuntimeMetrics:
        """Return this request's exact accumulated metrics after accepted writes."""

        with self._lock:
            return self._metrics

    def begin_model_attempt(
        self,
        *,
        attempt_id: str,
        cache_status: CacheStatus = CacheStatus.MISS,
    ) -> ModelAttempt:
        """Start timing a genuine provider attempt before the provider is invoked."""

        if self.context.endpoint == "evaluate":
            raise GovernanceError("pure-rule evaluate must use record_rule_evaluation")
        if self.context.model is None:
            raise GovernanceError("a model attempt requires an auditable ModelIdentity")
        if cache_status not in {CacheStatus.MISS, CacheStatus.BYPASSED}:
            raise GovernanceError("a live model attempt cannot be a cache hit or fallback")
        self._reserve_event_id(attempt_id)
        return ModelAttempt(
            session=self,
            attempt_id=attempt_id,
            started_ns=self._read_monotonic_ns(),
            cache_status=cache_status,
        )

    def record_cache_hit(self, *, event_id: str) -> RuntimeMetrics:
        """Record an explicit cache hit without importing historical token usage."""

        return self._record_non_model_event(
            event_id=event_id,
            event_kind=_EventKind.CACHE_HIT,
            metrics=_zero_metrics(),
            token_source=_TokenMeasurementSource.NOT_APPLICABLE,
            token_status=_TokenMeasurementStatus.NOT_APPLICABLE,
            latency_source="NOT_APPLICABLE_CACHE",
            cache_status=CacheStatus.HIT,
            fallback_reason=None,
            failure_reason=None,
        )

    def record_cache_fallback(self, *, event_id: str, fallback_reason: str) -> RuntimeMetrics:
        """Record a cache fallback reason without logging a provider exception string."""

        if not _SAFE_REASON.fullmatch(fallback_reason):
            raise GovernanceError("fallback_reason must be a safe lowercase reason code")
        return self._record_non_model_event(
            event_id=event_id,
            event_kind=_EventKind.CACHE_FALLBACK,
            metrics=_zero_metrics(),
            token_source=_TokenMeasurementSource.NOT_APPLICABLE,
            token_status=_TokenMeasurementStatus.NOT_APPLICABLE,
            latency_source="NOT_APPLICABLE_CACHE",
            cache_status=CacheStatus.FALLBACK,
            fallback_reason=fallback_reason,
            failure_reason=None,
        )

    def record_rule_evaluation(self, *, event_id: str) -> RuntimeMetrics:
        """Record the frozen one-per-evaluate rule substitution measurement."""

        if self.context.endpoint != "evaluate" or self.context.model is not None:
            raise GovernanceError("rule substitution is reserved for a pure-rule evaluate request")
        if not any(source.phase == "RULE" for source in self.context.input_sources):
            raise GovernanceError("pure-rule evaluate requires a safe RULE input source")
        metrics = RuntimeMetrics(
            input_tokens=0,
            output_tokens=0,
            inference_latency_ms=0,
            rule_substitution_count=1,
        )
        return self._record_non_model_event(
            event_id=event_id,
            event_kind=_EventKind.RULE_EVALUATION,
            metrics=metrics,
            token_source=_TokenMeasurementSource.NOT_APPLICABLE,
            token_status=_TokenMeasurementStatus.NOT_APPLICABLE,
            latency_source="NOT_APPLICABLE_RULE",
            cache_status=CacheStatus.BYPASSED,
            fallback_reason=None,
            failure_reason=None,
        )

    def record(self, *, endpoint: _EndpointName, metrics: RuntimeMetrics) -> None:
        """Implement the frozen MetricsSink shape for a premeasured service result.

        This compatibility seam accepts one complete metric object per request.
        Model callers should use ``begin_model_attempt`` so provenance is exact.
        """

        if endpoint != self.context.endpoint:
            raise GovernanceError("MetricsSink endpoint must match the bound request context")
        with self._lock:
            if self._port_metrics_recorded:
                raise DuplicateGovernanceEventError(
                    "premeasured port metrics were already recorded"
                )
            self._port_metrics_recorded = True
        try:
            self._record_non_model_event(
                event_id="port-metrics",
                event_kind=_EventKind.PORT_METRICS,
                metrics=metrics,
                token_source=_TokenMeasurementSource.PORT_SUPPLIED,
                token_status=_TokenMeasurementStatus.DECLARED_BY_CALLER,
                latency_source="PORT_SUPPLIED",
                cache_status=CacheStatus.BYPASSED,
                fallback_reason=None,
                failure_reason=None,
            )
        except Exception:
            with self._lock:
                self._port_metrics_recorded = False
            raise

    def _record_model_attempt(
        self,
        *,
        attempt_id: str,
        started_ns: int,
        cache_status: CacheStatus,
        provider_usage: ProviderUsage | Mapping[str, object] | None,
        tokenizer: ExactTokenCounter | None,
        input_text: str | None,
        output_text: str | None,
    ) -> RuntimeMetrics:
        measurement = self._resolve_token_measurement(
            provider_usage=provider_usage,
            tokenizer=tokenizer,
            input_text=input_text,
            output_text=output_text,
        )
        elapsed_ms = self._elapsed_ms(started_ns)
        metrics = measurement.to_metrics(latency_ms=elapsed_ms)
        self._commit_reserved_event(
            event_id=attempt_id,
            event_kind=_EventKind.MODEL_ATTEMPT,
            metrics=metrics,
            token_source=measurement.source,
            token_status=measurement.status,
            latency_source="PERF_COUNTER",
            cache_status=cache_status,
            fallback_reason=None,
            failure_reason=None,
        )
        return metrics

    def _record_model_failure(
        self,
        *,
        attempt_id: str,
        started_ns: int,
        cache_status: CacheStatus,
        failure_reason: str,
    ) -> RuntimeMetrics:
        if not _SAFE_REASON.fullmatch(failure_reason):
            raise GovernanceError("failure_reason must be a safe lowercase reason code")
        metrics = RuntimeMetrics(
            input_tokens=0,
            output_tokens=0,
            inference_latency_ms=self._elapsed_ms(started_ns),
            rule_substitution_count=0,
        )
        self._commit_reserved_event(
            event_id=attempt_id,
            event_kind=_EventKind.MODEL_FAILURE,
            metrics=metrics,
            token_source=_TokenMeasurementSource.MISSING,
            token_status=_TokenMeasurementStatus.MISSING,
            latency_source="PERF_COUNTER",
            cache_status=cache_status,
            fallback_reason=None,
            failure_reason=failure_reason,
        )
        return metrics

    def _resolve_token_measurement(
        self,
        *,
        provider_usage: ProviderUsage | Mapping[str, object] | None,
        tokenizer: ExactTokenCounter | None,
        input_text: str | None,
        output_text: str | None,
    ) -> _TokenMeasurement:
        if isinstance(provider_usage, ProviderUsage):
            usage = provider_usage
        elif provider_usage is None:
            usage = None
        else:
            usage = ProviderUsage.from_payload(provider_usage)
        if usage is not None:
            return _TokenMeasurement(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                source=_TokenMeasurementSource.PROVIDER_USAGE,
                status=_TokenMeasurementStatus.AVAILABLE,
            )
        if tokenizer is not None and input_text is not None and output_text is not None:
            model = self.context.model
            if model is None or model.model_revision is None:
                raise MeasurementConfigurationError(
                    "a same-version tokenizer requires an explicit model revision"
                )
            if (
                tokenizer.model_id != model.model_id
                or tokenizer.model_revision != model.model_revision
            ):
                raise MeasurementConfigurationError(
                    "tokenizer must match the model ID and revision exactly"
                )
            return _TokenMeasurement(
                input_tokens=_require_nonnegative_int(
                    tokenizer.count_tokens(input_text), "tokenizer input_tokens"
                ),
                output_tokens=_require_nonnegative_int(
                    tokenizer.count_tokens(output_text), "tokenizer output_tokens"
                ),
                source=_TokenMeasurementSource.TOKENIZER_ACTUAL,
                status=_TokenMeasurementStatus.AVAILABLE,
            )
        return _TokenMeasurement(
            input_tokens=0,
            output_tokens=0,
            source=_TokenMeasurementSource.MISSING,
            status=_TokenMeasurementStatus.MISSING,
        )

    def _record_non_model_event(
        self,
        *,
        event_id: str,
        event_kind: _EventKind,
        metrics: RuntimeMetrics,
        token_source: _TokenMeasurementSource,
        token_status: _TokenMeasurementStatus,
        latency_source: str,
        cache_status: CacheStatus,
        fallback_reason: str | None,
        failure_reason: str | None,
    ) -> RuntimeMetrics:
        self._reserve_event_id(event_id)
        try:
            self._commit_reserved_event(
                event_id=event_id,
                event_kind=event_kind,
                metrics=metrics,
                token_source=token_source,
                token_status=token_status,
                latency_source=latency_source,
                cache_status=cache_status,
                fallback_reason=fallback_reason,
                failure_reason=failure_reason,
            )
        except Exception:
            self._discard_reserved_event_id(event_id)
            raise
        return self.runtime_metrics

    def _commit_reserved_event(
        self,
        *,
        event_id: str,
        event_kind: _EventKind,
        metrics: RuntimeMetrics,
        token_source: _TokenMeasurementSource,
        token_status: _TokenMeasurementStatus,
        latency_source: str,
        cache_status: CacheStatus,
        fallback_reason: str | None,
        failure_reason: str | None,
    ) -> None:
        _require_safe_identifier(event_id, "event_id")
        with self._lock:
            if event_id not in self._reserved_event_ids:
                raise DuplicateGovernanceEventError("event_id was not reserved by this session")
            new_totals = _add_metrics(self._metrics, metrics)
            emitted_at = self._wall_clock()
            if emitted_at.tzinfo is None or emitted_at.utcoffset() is None:
                raise GovernanceError("wall_clock must return a timezone-aware instant")
            record = _GovernanceRecord(
                event_id=event_id,
                event_kind=event_kind,
                context=self.context,
                metrics=metrics,
                request_totals=new_totals,
                token_source=token_source,
                token_status=token_status,
                latency_source=latency_source,
                cache_status=cache_status,
                fallback_reason=fallback_reason,
                failure_reason=failure_reason,
                emitted_at=emitted_at.astimezone(UTC),
            )
            try:
                self._sink.write(record)
            except GovernanceLogWriteError:
                raise
            except Exception as exc:
                raise GovernanceLogWriteError("governance audit log write failed") from exc
            self._metrics = new_totals

    def _reserve_event_id(self, event_id: str) -> None:
        _require_safe_identifier(event_id, "event_id")
        with self._lock:
            if event_id in self._reserved_event_ids:
                raise DuplicateGovernanceEventError(
                    "event_id was already counted or is in progress"
                )
            self._reserved_event_ids.add(event_id)

    def _discard_reserved_event_id(self, event_id: str) -> None:
        with self._lock:
            self._reserved_event_ids.discard(event_id)

    def _read_monotonic_ns(self) -> int:
        return _require_nonnegative_int(self._monotonic_ns(), "monotonic timestamp")

    def _elapsed_ms(self, started_ns: int) -> int:
        elapsed_ns = self._read_monotonic_ns() - started_ns
        if elapsed_ns < 0:
            raise MeasurementConfigurationError("monotonic clock moved backwards")
        return elapsed_ns // 1_000_000


class ModelAttempt:
    """One timed provider invocation that can reach exactly one terminal state."""

    def __init__(
        self,
        *,
        session: GovernanceSession,
        attempt_id: str,
        started_ns: int,
        cache_status: CacheStatus,
    ) -> None:
        self._session = session
        self._attempt_id = attempt_id
        self._started_ns = started_ns
        self._cache_status = cache_status
        self._finished = False

    def complete(
        self,
        *,
        provider_usage: ProviderUsage | Mapping[str, object] | None = None,
        tokenizer: ExactTokenCounter | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
    ) -> RuntimeMetrics:
        """Finish a successful attempt using provider usage or an exact tokenizer."""

        if self._finished:
            raise AttemptAlreadyFinishedError("model attempt already has a terminal audit record")
        metrics = self._session._record_model_attempt(
            attempt_id=self._attempt_id,
            started_ns=self._started_ns,
            cache_status=self._cache_status,
            provider_usage=provider_usage,
            tokenizer=tokenizer,
            input_text=input_text,
            output_text=output_text,
        )
        self._finished = True
        return metrics

    def fail(self, *, failure_reason: str) -> RuntimeMetrics:
        """Finish an unsuccessful real provider attempt without fabricating token usage."""

        if self._finished:
            raise AttemptAlreadyFinishedError("model attempt already has a terminal audit record")
        metrics = self._session._record_model_failure(
            attempt_id=self._attempt_id,
            started_ns=self._started_ns,
            cache_status=self._cache_status,
            failure_reason=failure_reason,
        )
        self._finished = True
        return metrics
