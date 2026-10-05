"""Independent BATCH-20 behavioral probe; does not import implementation tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from covenia_b.cache import (
    CacheFallbackReason,
    CacheFallbackUnavailable,
    CacheVersionSet,
    CachingExtractionProvider,
    InMemoryCacheGovernanceSink,
)
from covenia_b.domain.types import (
    CandidateExtraction,
    ModelMetadata,
    ResolvedImage,
    SanitizedModelInput,
    SourceTrace,
)
from covenia_b.ports.errors import ModelUnavailable


class Store:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}
        self.get_count = 0
        self.put_count = 0

    def get(self, *, case_id: str, cache_key: str) -> object | None:
        self.get_count += 1
        return self.values.get((case_id, cache_key))

    def put(self, *, cache_key: str, candidate: CandidateExtraction) -> None:
        self.put_count += 1
        self.values[(candidate.case_id, cache_key)] = candidate


class Provider:
    def __init__(self, *outcomes: CandidateExtraction | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction:
        del model_input
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def input_value() -> SanitizedModelInput:
    return SanitizedModelInput(
        case_id="case-probe-001",
        redacted_text=(
            "order_id=order-probe-001\n"
            "[message_id=agent-probe-001 timestamp=2026-10-05T08:00:00Z "
            "speaker=AGENT] Delivery update within 48 hours."
        ),
        images=(
            ResolvedImage(
                evidence_id="image-probe-001",
                media_type="image/png",
                content_sha256="c" * 64,
                byte_length=64,
            ),
        ),
        source_ids=("order-probe-001", "agent-probe-001", "image-probe-001"),
    )


def candidate(model_input: SanitizedModelInput, *, run_id: str = "origin-probe-run") -> CandidateExtraction:
    return CandidateExtraction(
        case_id=model_input.case_id,
        model_metadata=ModelMetadata(
            model_id="qwen3-vl-plus",
            model_revision="rev-1",
            prompt_version="prompt-1",
            run_id=run_id,
            cached_result=False,
        ),
        observations=("Box corner is visibly dented.",),
        source_trace=(
            SourceTrace(field="observations[0]", source_type="IMAGE", source_id="image-probe-001"),
            SourceTrace(
                field="candidate_promise_texts[0]",
                source_type="CHAT",
                source_id="agent-probe-001",
            ),
        ),
        candidate_promise_texts=("Delivery update within 48 hours.",),
    )


def versions(**changes: str) -> CacheVersionSet:
    values = {
        "model_id": "qwen3-vl-plus",
        "model_revision": "rev-1",
        "prompt_version": "prompt-1",
        "schema_version": "schema-1",
        "policy_version": "policy-1",
    }
    values.update(changes)
    return CacheVersionSet(**values)


def provider(*, upstream: Provider, store: Store, sink: InMemoryCacheGovernanceSink, version_set: CacheVersionSet | None = None, mode: str = "TEST_DOUBLE") -> CachingExtractionProvider:
    return CachingExtractionProvider(
        upstream=upstream,
        store=store,
        versions=version_set or versions(),
        provider_mode=mode,
        cache_enabled=True,
        governance_sink=None if mode == "LIVE" else sink,
    )


def expect_miss(instance: CachingExtractionProvider, value: SanitizedModelInput, scope: str) -> str:
    try:
        asyncio.run(instance.extract_for_request(value, request_id="request-probe-miss", scope=scope))
    except CacheFallbackUnavailable as error:
        return error.reason.value
    raise AssertionError("expected explicit cache fallback failure")


def main() -> None:
    value = input_value()
    seed = candidate(value)
    store = Store()
    sink = InMemoryCacheGovernanceSink()
    normal = provider(upstream=Provider(seed, ModelUnavailable("offline")), store=store, sink=sink)
    direct = asyncio.run(normal.extract_for_request(value, request_id="request-probe-seed", scope="NORMAL"))
    fallback = asyncio.run(normal.extract_for_request(value, request_id="request-probe-fallback", scope="NORMAL"))
    event_json = json.dumps(sink.events[0].to_redacted_dict(), sort_keys=True)

    misses: dict[str, str] = {}
    changes = {
        "safe_text": replace(value, redacted_text="[agent message] Delivery update within 72 hours."),
        "image_hash": replace(value, images=(replace(value.images[0], content_sha256="d" * 64),)),
        "source_ids": replace(value, source_ids=(*value.source_ids, "ticket-probe-001")),
    }
    for name, changed in changes.items():
        misses[name] = expect_miss(
            provider(upstream=Provider(ModelUnavailable("offline")), store=store, sink=InMemoryCacheGovernanceSink()),
            changed,
            "NORMAL",
        )
    misses["scope"] = expect_miss(
        provider(upstream=Provider(ModelUnavailable("offline")), store=store, sink=InMemoryCacheGovernanceSink()),
        value,
        "CHALLENGE",
    )
    for field in ("model_revision", "prompt_version", "schema_version", "policy_version"):
        misses[field] = expect_miss(
            provider(
                upstream=Provider(ModelUnavailable("offline")),
                store=store,
                sink=InMemoryCacheGovernanceSink(),
                version_set=versions(**{field: "changed-2"}),
            ),
            value,
            "NORMAL",
        )

    key = normal.cache_key_for(value, scope="NORMAL")
    store.values[(value.case_id, key)] = replace(seed, candidate_only=False)
    corrupt = expect_miss(
        provider(upstream=Provider(ModelUnavailable("offline")), store=store, sink=InMemoryCacheGovernanceSink()),
        value,
        "NORMAL",
    )
    pii_store = Store()
    pii = replace(seed, observations=("phone 13800138000",))
    asyncio.run(provider(upstream=Provider(pii), store=pii_store, sink=InMemoryCacheGovernanceSink()).extract_for_request(value, request_id="request-probe-pii", scope="NORMAL"))

    live_store = Store()
    live = provider(upstream=Provider(ModelUnavailable("offline")), store=live_store, sink=InMemoryCacheGovernanceSink(), mode="LIVE")
    try:
        asyncio.run(live.extract_for_request(value, request_id="request-probe-live", scope="NORMAL"))
    except ModelUnavailable:
        live_upstream_error = True
    else:
        live_upstream_error = False

    assert direct.model_metadata.cached_result is False
    assert fallback.model_metadata.cached_result is True
    assert fallback.model_metadata.run_id == "origin-probe-run"
    assert normal._upstream.calls == 2
    assert all(reason == CacheFallbackReason.CACHE_MISS.value for reason in misses.values())
    assert corrupt == CacheFallbackReason.CACHE_CORRUPT.value
    assert pii_store.put_count == 0
    assert live.cache_enabled is False and live_store.get_count == 0 and live_store.put_count == 0 and live_upstream_error
    assert value.redacted_text not in event_json
    assert "agent-probe-001" not in event_json
    assert "Delivery update" not in event_json
    print(json.dumps({
        "result": "PASS",
        "direct_cached_result": direct.model_metadata.cached_result,
        "fallback_cached_result": fallback.model_metadata.cached_result,
        "fallback_origin_run_id_preserved": fallback.model_metadata.run_id == "origin-probe-run",
        "upstream_calls": normal._upstream.calls,
        "invalidation_reasons": misses,
        "corrupt_cache_reason": corrupt,
        "pii_candidate_cache_writes": pii_store.put_count,
        "live_cache_enabled": live.cache_enabled,
        "live_store_reads": live_store.get_count,
        "live_store_writes": live_store.put_count,
        "event_contains_raw_text": value.redacted_text in event_json,
        "event_contains_source_id": "agent-probe-001" in event_json,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
