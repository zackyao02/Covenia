"""Behavioral tests for BATCH-09 runtime metrics and redacted audit records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from covenia_b.domain.types import RuntimeMetrics
from covenia_b.observability import (
    LOCKED_MODEL_ID,
    CacheStatus,
    GovernanceContext,
    GovernanceLogWriteError,
    InMemoryGovernanceSink,
    InputSourceKind,
    JsonlGovernanceSink,
    MeasurementConfigurationError,
    ModelIdentity,
    ProviderUsage,
    RuntimeMetricsCollector,
    SafeInputSource,
)
from covenia_b.ports.contracts import MetricsSink


class StepClock:
    def __init__(self, *values: int) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


class ExactTokenizerDouble:
    model_id = LOCKED_MODEL_ID
    model_revision = "rev-2026-09-13"

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FailingGovernanceSink:
    def write(self, record: object) -> None:
        raise OSError("simulated audit media failure")


def _model_context() -> GovernanceContext:
    return GovernanceContext(
        request_id="req-09-001",
        run_id="run-09-001",
        endpoint="analyze",
        input_sources=(
            SafeInputSource.from_identifier(
                phase="MODEL", kind=InputSourceKind.CHAT, identifier="message-opaque-001"
            ),
            SafeInputSource.from_identifier(
                phase="MODEL", kind=InputSourceKind.ORDER, identifier="order-opaque-001"
            ),
        ),
        pii_masked_count=2,
        image_hashes=("a" * 64,),
        model=ModelIdentity(
            model_id=LOCKED_MODEL_ID,
            model_revision="rev-2026-09-13",
            prompt_version="prompt-v3",
        ),
    )


def _fixed_wall_clock() -> datetime:
    return datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


def test_provider_usage_is_exact_and_an_attempt_cannot_be_counted_twice() -> None:
    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(
        sink,
        monotonic_ns=StepClock(10_000_000, 37_000_000, 40_000_000, 44_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(_model_context())

    metrics = session.begin_model_attempt(attempt_id="attempt-001").complete(
        provider_usage=ProviderUsage(input_tokens=11, output_tokens=7)
    )

    assert metrics.model_dump() == {
        "input_tokens": 11,
        "output_tokens": 7,
        "inference_latency_ms": 27,
        "rule_substitution_count": 0,
    }
    assert session.runtime_metrics == metrics
    assert sink.records[0]["metric_provenance"] == {
        "token_measurement_source": "PROVIDER_USAGE",
        "token_measurement_status": "AVAILABLE",
        "latency_measurement_source": "PERF_COUNTER",
    }
    attempt = session.begin_model_attempt(attempt_id="attempt-002")
    attempt.complete(provider_usage={"prompt_tokens": 3, "completion_tokens": 2})
    with pytest.raises(Exception, match="already"):
        attempt.complete(provider_usage=ProviderUsage(input_tokens=3, output_tokens=2))
    assert session.runtime_metrics.input_tokens == 14
    assert session.runtime_metrics.output_tokens == 9


def test_retry_and_cache_events_do_not_reimport_historical_token_usage() -> None:
    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(
        sink,
        monotonic_ns=StepClock(0, 10_000_000, 10_000_000, 30_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(_model_context())

    session.begin_model_attempt(attempt_id="retry-001").complete(
        provider_usage=ProviderUsage(input_tokens=5, output_tokens=1)
    )
    session.begin_model_attempt(attempt_id="retry-002").complete(
        provider_usage=ProviderUsage(input_tokens=7, output_tokens=2)
    )
    before_cache = session.runtime_metrics
    after_cache = session.record_cache_hit(event_id="cache-hit-001")

    assert before_cache.model_dump() == {
        "input_tokens": 12,
        "output_tokens": 3,
        "inference_latency_ms": 30,
        "rule_substitution_count": 0,
    }
    assert after_cache == before_cache
    assert sink.records[-1]["event_kind"] == "CACHE_HIT"
    assert sink.records[-1]["metrics"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "inference_latency_ms": 0,
        "rule_substitution_count": 0,
    }
    assert sink.records[-1]["cache"] == {"status": "HIT", "fallback_reason": None}


def test_missing_usage_never_fabricates_positive_tokens_and_is_disclosed() -> None:
    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(
        sink,
        monotonic_ns=StepClock(0, 5_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(_model_context())

    metrics = session.begin_model_attempt(attempt_id="missing-usage-001").complete(
        provider_usage={"total_tokens": 99}
    )

    assert metrics.model_dump() == {
        "input_tokens": 0,
        "output_tokens": 0,
        "inference_latency_ms": 5,
        "rule_substitution_count": 0,
    }
    assert sink.records[0]["metric_provenance"]["token_measurement_source"] == "MISSING"
    assert sink.records[0]["metric_provenance"]["token_measurement_status"] == "MISSING"


def test_same_revision_tokenizer_is_used_only_when_provider_usage_is_absent() -> None:
    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(
        sink,
        monotonic_ns=StepClock(0, 9_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(_model_context())

    metrics = session.begin_model_attempt(attempt_id="tokenizer-001").complete(
        tokenizer=ExactTokenizerDouble(),
        input_text="safe prompt words",
        output_text="safe output",
    )

    assert metrics.input_tokens == 3
    assert metrics.output_tokens == 2
    assert sink.records[0]["metric_provenance"]["token_measurement_source"] == "TOKENIZER_ACTUAL"


def test_mismatched_tokenizer_revision_is_rejected_before_audit_record_is_written() -> None:
    class MismatchedTokenizer(ExactTokenizerDouble):
        model_revision = "another-revision"

    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(
        sink,
        monotonic_ns=StepClock(0, 1_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(_model_context())

    with pytest.raises(MeasurementConfigurationError, match="match"):
        session.begin_model_attempt(attempt_id="tokenizer-bad-001").complete(
            tokenizer=MismatchedTokenizer(), input_text="safe", output_text="safe"
        )
    assert sink.records == []
    assert session.runtime_metrics == RuntimeMetrics(
        input_tokens=0,
        output_tokens=0,
        inference_latency_ms=0,
        rule_substitution_count=0,
    )


def test_pure_rule_evaluate_has_zero_model_metrics_and_one_frozen_substitution() -> None:
    context = GovernanceContext(
        request_id="req-09-rule-001",
        run_id="run-09-rule-001",
        endpoint="evaluate",
        input_sources=(
            SafeInputSource.from_identifier(
                phase="RULE", kind=InputSourceKind.RULE, identifier="rule-chain-v1"
            ),
        ),
        pii_masked_count=0,
    )
    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(sink, wall_clock=_fixed_wall_clock).start_request(context)

    metrics = session.record_rule_evaluation(event_id="rule-evaluation-001")

    assert metrics.model_dump() == {
        "input_tokens": 0,
        "output_tokens": 0,
        "inference_latency_ms": 0,
        "rule_substitution_count": 1,
    }
    assert sink.records[0]["event_kind"] == "RULE_EVALUATION"
    assert sink.records[0]["input_sources"][0]["phase"] == "RULE"


def test_cache_fallback_and_failed_attempt_are_explicitly_audited() -> None:
    sink = InMemoryGovernanceSink()
    session = RuntimeMetricsCollector(
        sink,
        monotonic_ns=StepClock(0, 21_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(_model_context())

    failed_attempt = session.begin_model_attempt(
        attempt_id="failed-provider-001", cache_status=CacheStatus.MISS
    )
    failed_attempt.fail(failure_reason="provider_unavailable")
    metrics = session.record_cache_fallback(
        event_id="cache-fallback-001", fallback_reason="provider_unavailable"
    )

    assert metrics.inference_latency_ms == 21
    assert [record["event_kind"] for record in sink.records] == [
        "MODEL_FAILURE",
        "CACHE_FALLBACK",
    ]
    assert sink.records[1]["cache"] == {
        "status": "FALLBACK",
        "fallback_reason": "provider_unavailable",
    }


def test_audit_write_failure_never_marks_metrics_as_success() -> None:
    context = GovernanceContext(
        request_id="req-09-fail-001",
        run_id="run-09-fail-001",
        endpoint="evaluate",
        input_sources=(
            SafeInputSource.from_identifier(
                phase="RULE", kind=InputSourceKind.RULE, identifier="rule-chain-v1"
            ),
        ),
        pii_masked_count=0,
    )
    collector = RuntimeMetricsCollector(FailingGovernanceSink(), wall_clock=_fixed_wall_clock)
    session = collector.start_request(context)

    with pytest.raises(GovernanceLogWriteError, match="audit log write failed"):
        session.record_rule_evaluation(event_id="audit-failure-001")

    assert session.runtime_metrics == RuntimeMetrics(
        input_tokens=0,
        output_tokens=0,
        inference_latency_ms=0,
        rule_substitution_count=0,
    )


def test_jsonl_record_does_not_retain_pii_secret_prompt_or_original_image(tmp_path: Path) -> None:
    raw_phone = "13800138000"
    raw_secret = "sk-live-example-not-a-real-key"
    raw_prompt = "full original prompt with identity and delivery address"
    raw_image = b"original-image-bytes-should-never-be-logged"
    raw_image_text = raw_image.decode("ascii")
    sink_path = tmp_path / "governance.jsonl"
    context = GovernanceContext(
        request_id="req-09-redacted-001",
        run_id="run-09-redacted-001",
        endpoint="analyze",
        input_sources=(
            SafeInputSource.from_identifier(
                phase="MODEL", kind=InputSourceKind.CHAT, identifier=raw_phone
            ),
        ),
        pii_masked_count=1,
        image_hashes=(sha256(raw_image).hexdigest(),),
        model=ModelIdentity(
            model_id=LOCKED_MODEL_ID,
            model_revision="rev-2026-09-13",
            prompt_version="prompt-v3",
        ),
    )
    session = RuntimeMetricsCollector(
        JsonlGovernanceSink(sink_path),
        monotonic_ns=StepClock(0, 1_000_000),
        wall_clock=_fixed_wall_clock,
    ).start_request(context)

    session.begin_model_attempt(attempt_id="redaction-probe-001").complete(
        tokenizer=ExactTokenizerDouble(),
        input_text=f"{raw_prompt} {raw_secret} {raw_phone}",
        output_text="safe output only",
    )

    payload = sink_path.read_text(encoding="utf-8")
    parsed = json.loads(payload)
    for forbidden_value in (raw_phone, raw_secret, raw_prompt, raw_image_text):
        assert forbidden_value not in payload
    assert parsed["image_hashes"] == [sha256(raw_image).hexdigest()]
    assert parsed["pii_masked_count"] == 1
    assert "prompt_version" in parsed["model"]


def test_request_session_is_a_frozen_metrics_sink_with_one_safe_port_record() -> None:
    sink = InMemoryGovernanceSink()
    collector = RuntimeMetricsCollector(sink, wall_clock=_fixed_wall_clock)
    session = collector.start_request(_model_context())

    assert isinstance(session, MetricsSink)
    session.record(
        endpoint="analyze",
        metrics=RuntimeMetrics(
            input_tokens=0,
            output_tokens=0,
            inference_latency_ms=0,
            rule_substitution_count=0,
        ),
    )
    assert sink.records[0]["event_kind"] == "PORT_METRICS"
    assert sink.records[0]["metric_provenance"]["token_measurement_source"] == "PORT_SUPPLIED"
