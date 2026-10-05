"""BATCH-20 tests for explicit, candidate-only extraction cache fallback."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

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
from covenia_b.ports.errors import ExtractionStoreUnavailable, ModelUnavailable


class MemoryExtractionStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], object] = {}
        self.get_calls: list[tuple[str, str]] = []
        self.put_calls: list[str] = []

    def get(self, *, case_id: str, cache_key: str) -> object | None:
        self.get_calls.append((case_id, cache_key))
        return self.values.get((case_id, cache_key))

    def put(self, *, cache_key: str, candidate: CandidateExtraction) -> None:
        self.put_calls.append(cache_key)
        self.values[(candidate.case_id, cache_key)] = candidate


class UnavailableExtractionStore(MemoryExtractionStore):
    def get(self, *, case_id: str, cache_key: str) -> object | None:
        del case_id, cache_key
        raise ExtractionStoreUnavailable("cache store is offline")


class ScriptedProvider:
    def __init__(self, *outcomes: CandidateExtraction | Exception) -> None:
        self._outcomes = list(outcomes)
        self.inputs: list[SanitizedModelInput] = []

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction:
        self.inputs.append(model_input)
        if not self._outcomes:
            raise AssertionError("provider was called more times than scripted")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FailingGovernanceSink:
    def record_cache_fallback(self, event: object) -> None:
        del event
        raise RuntimeError("audit write failed")


def test_model_failure_uses_valid_candidate_only_as_audited_fallback() -> None:
    model_input = _model_input()
    candidate = _candidate(model_input, run_id="origin-run-001")
    store = MemoryExtractionStore()
    governance = InMemoryCacheGovernanceSink()
    upstream = ScriptedProvider(candidate, ModelUnavailable("provider offline"))
    provider = _provider(upstream=upstream, store=store, governance=governance)

    with provider.request_context(request_id="request-live-001", scope="NORMAL"):
        direct = asyncio.run(provider.extract(model_input))
    with provider.request_context(request_id="request-fallback-002", scope="NORMAL"):
        fallback = asyncio.run(provider.extract(model_input))

    assert direct.model_metadata.cached_result is False
    assert fallback.model_metadata.cached_result is True
    assert fallback.model_metadata.run_id == "origin-run-001"
    assert len(upstream.inputs) == 2  # Cache is never a normal successful-path response.
    assert len(store.put_calls) == 1
    assert len(store.get_calls) == 1
    assert set(CandidateExtraction.__dataclass_fields__).isdisjoint(
        {"deadline", "accountability_state", "human_edits", "event_status"}
    )

    event = governance.events[0]
    assert event.request_id == "request-fallback-002"
    assert event.cached_extraction_run_id == "origin-run-001"
    assert event.cached_result is True
    rendered_event = json.dumps(event.to_redacted_dict(), sort_keys=True)
    assert "We will update" not in rendered_event
    assert "agent-safe-001" not in rendered_event


@pytest.mark.parametrize(
    ("change", "expected_scope"),
    [
        ("safe_text", "NORMAL"),
        ("image_hash", "NORMAL"),
        ("source_ids", "NORMAL"),
        ("scope", "CHALLENGE"),
        ("model_revision", "NORMAL"),
        ("prompt_version", "NORMAL"),
        ("schema_version", "NORMAL"),
        ("policy_version", "NORMAL"),
    ],
)
def test_input_scope_or_version_change_is_a_cache_miss(
    change: str,
    expected_scope: str,
) -> None:
    base_input = _model_input()
    base_versions = _versions()
    seed_candidate = _candidate(base_input)
    store = MemoryExtractionStore()
    seed = _provider(
        upstream=ScriptedProvider(seed_candidate),
        store=store,
        governance=InMemoryCacheGovernanceSink(),
        versions=base_versions,
    )
    with seed.request_context(request_id="request-seed-001", scope="NORMAL"):
        asyncio.run(seed.extract(base_input))

    changed_input = base_input
    changed_versions = base_versions
    if change == "safe_text":
        changed_input = replace(
            base_input,
            redacted_text=base_input.redacted_text.replace("48 hours", "72 hours"),
        )
    elif change == "image_hash":
        changed_input = replace(
            base_input,
            images=(replace(base_input.images[0], content_sha256="b" * 64),),
        )
    elif change == "source_ids":
        changed_input = replace(
            base_input,
            source_ids=(*base_input.source_ids, "ticket-safe-002"),
        )
    elif change != "scope":
        changed_versions = replace(base_versions, **{change: f"changed-{change}-v2"})

    fallback = _provider(
        upstream=ScriptedProvider(ModelUnavailable("provider offline")),
        store=store,
        governance=InMemoryCacheGovernanceSink(),
        versions=changed_versions,
    )
    with fallback.request_context(request_id="request-change-002", scope=expected_scope):
        with pytest.raises(CacheFallbackUnavailable) as raised:
            asyncio.run(fallback.extract(changed_input))

    assert raised.value.reason is CacheFallbackReason.CACHE_MISS
    assert len(store.get_calls) == 1


def test_corrupt_cached_candidate_is_not_a_hit() -> None:
    model_input = _model_input()
    candidate = _candidate(model_input)
    store = MemoryExtractionStore()
    governance = InMemoryCacheGovernanceSink()
    provider = _provider(
        upstream=ScriptedProvider(candidate, ModelUnavailable("provider offline")),
        store=store,
        governance=governance,
    )
    with provider.request_context(request_id="request-seed-001", scope="NORMAL"):
        asyncio.run(provider.extract(model_input))

    key = provider.cache_key_for(model_input, scope="NORMAL")
    store.values[(model_input.case_id, key)] = replace(candidate, candidate_only=False)
    with provider.request_context(request_id="request-corrupt-002", scope="NORMAL"):
        with pytest.raises(CacheFallbackUnavailable) as raised:
            asyncio.run(provider.extract(model_input))

    assert raised.value.reason is CacheFallbackReason.CACHE_CORRUPT
    assert governance.events == ()


@pytest.mark.parametrize("kind", ["invalid_source", "detectable_pii", "wrong_version"])
def test_only_schema_source_and_privacy_safe_candidates_are_cached(kind: str) -> None:
    model_input = _model_input()
    candidate = _candidate(model_input)
    if kind == "invalid_source":
        candidate = replace(
            candidate,
            source_trace=(
                SourceTrace(
                    field="observations[0]",
                    source_type="IMAGE",
                    source_id="untrusted-image-999",
                ),
                candidate.source_trace[1],
            ),
        )
    elif kind == "detectable_pii":
        candidate = replace(candidate, observations=("call 13800138000",))
    else:
        candidate = replace(
            candidate,
            model_metadata=candidate.model_metadata.model_copy(
                update={"model_revision": "untracked-revision"}
            ),
        )
    store = MemoryExtractionStore()
    provider = _provider(
        upstream=ScriptedProvider(candidate),
        store=store,
        governance=InMemoryCacheGovernanceSink(),
    )

    with provider.request_context(request_id="request-unsafe-001", scope="NORMAL"):
        returned = asyncio.run(provider.extract(model_input))

    assert returned is candidate
    assert store.values == {}


def test_cold_cache_model_failure_is_explicit() -> None:
    model_input = _model_input()
    provider = _provider(
        upstream=ScriptedProvider(ModelUnavailable("provider offline")),
        store=MemoryExtractionStore(),
        governance=InMemoryCacheGovernanceSink(),
    )

    with provider.request_context(request_id="request-cold-001", scope="NORMAL"):
        with pytest.raises(CacheFallbackUnavailable) as raised:
            asyncio.run(provider.extract(model_input))

    assert raised.value.reason is CacheFallbackReason.CACHE_MISS
    assert raised.value.code == "EXTRACTION_CACHE_FALLBACK_UNAVAILABLE"
    assert raised.value.upstream_failure_code == "ModelUnavailable"


def test_live_mode_forcibly_bypasses_cache_reads_writes_and_fallback() -> None:
    model_input = _model_input()
    store = MemoryExtractionStore()
    upstream = ScriptedProvider(ModelUnavailable("provider offline"))
    provider = CachingExtractionProvider(
        upstream=upstream,
        store=store,
        versions=_versions(),
        provider_mode="LIVE",
        cache_enabled=True,
    )

    assert provider.cache_enabled is False
    with provider.request_context(request_id="request-live-001", scope="NORMAL"):
        with pytest.raises(ModelUnavailable) as raised:
            asyncio.run(provider.extract(model_input))

    assert type(raised.value) is ModelUnavailable
    assert store.get_calls == []
    assert store.put_calls == []


def test_missing_audit_receipt_prevents_serving_a_cached_candidate() -> None:
    model_input = _model_input()
    candidate = _candidate(model_input)
    store = MemoryExtractionStore()
    provider = _provider(
        upstream=ScriptedProvider(candidate, ModelUnavailable("provider offline")),
        store=store,
        governance=FailingGovernanceSink(),
    )
    with provider.request_context(request_id="request-seed-001", scope="NORMAL"):
        asyncio.run(provider.extract(model_input))

    with provider.request_context(request_id="request-fallback-002", scope="NORMAL"):
        with pytest.raises(CacheFallbackUnavailable) as raised:
            asyncio.run(provider.extract(model_input))

    assert raised.value.reason is CacheFallbackReason.GOVERNANCE_LOG_UNAVAILABLE


def test_unsafe_input_or_store_outage_never_becomes_a_cache_hit() -> None:
    unsafe_input = replace(
        _model_input(),
        redacted_text="call 13800138000 for an update",
    )
    unsafe_provider = _provider(
        upstream=ScriptedProvider(ModelUnavailable("provider offline")),
        store=MemoryExtractionStore(),
        governance=InMemoryCacheGovernanceSink(),
    )
    with unsafe_provider.request_context(request_id="request-unsafe-001", scope="NORMAL"):
        with pytest.raises(CacheFallbackUnavailable) as unsafe_raised:
            asyncio.run(unsafe_provider.extract(unsafe_input))
    assert unsafe_raised.value.reason is CacheFallbackReason.UNSAFE_CACHE_INPUT

    invalid_image_input = replace(
        _model_input(),
        images=(replace(_model_input().images[0], content_sha256="not-a-content-hash"),),
    )
    invalid_image_provider = _provider(
        upstream=ScriptedProvider(ModelUnavailable("provider offline")),
        store=MemoryExtractionStore(),
        governance=InMemoryCacheGovernanceSink(),
    )
    with invalid_image_provider.request_context(request_id="request-image-001", scope="NORMAL"):
        with pytest.raises(CacheFallbackUnavailable) as image_raised:
            asyncio.run(invalid_image_provider.extract(invalid_image_input))
    assert image_raised.value.reason is CacheFallbackReason.UNSAFE_CACHE_INPUT

    unavailable_provider = _provider(
        upstream=ScriptedProvider(ModelUnavailable("provider offline")),
        store=UnavailableExtractionStore(),
        governance=InMemoryCacheGovernanceSink(),
    )
    with unavailable_provider.request_context(request_id="request-store-001", scope="NORMAL"):
        with pytest.raises(CacheFallbackUnavailable) as store_raised:
            asyncio.run(unavailable_provider.extract(_model_input()))
    assert store_raised.value.reason is CacheFallbackReason.CACHE_STORE_UNAVAILABLE


def _provider(
    *,
    upstream: ScriptedProvider,
    store: MemoryExtractionStore,
    governance,
    versions: CacheVersionSet | None = None,
) -> CachingExtractionProvider:
    return CachingExtractionProvider(
        upstream=upstream,
        store=store,
        versions=versions or _versions(),
        governance_sink=governance,
    )


def _versions() -> CacheVersionSet:
    return CacheVersionSet(
        model_id="qwen3-vl-plus",
        model_revision="revision-safe-v1",
        prompt_version="candidate-extraction-v1",
        schema_version="candidate-schema-v1",
        policy_version="commitment-policy-v1",
    )


def _model_input() -> SanitizedModelInput:
    return SanitizedModelInput(
        case_id="case-safe-001",
        redacted_text="\n".join(
            (
                "order_id=order-safe-001",
                "[message_id=agent-safe-001 timestamp=2026-10-04T08:00:00Z "
                "speaker=AGENT] We will update in 48 hours.",
            )
        ),
        images=(
            ResolvedImage(
                evidence_id="image-safe-001",
                media_type="image/png",
                content_sha256="a" * 64,
                byte_length=128,
            ),
        ),
        source_ids=("order-safe-001", "agent-safe-001", "image-safe-001"),
    )


def _candidate(
    model_input: SanitizedModelInput,
    *,
    run_id: str = "origin-run-001",
) -> CandidateExtraction:
    return CandidateExtraction(
        case_id=model_input.case_id,
        model_metadata=ModelMetadata(
            model_id="qwen3-vl-plus",
            model_revision="revision-safe-v1",
            prompt_version="candidate-extraction-v1",
            run_id=run_id,
            cached_result=False,
        ),
        observations=("Outer packaging appears damaged.",),
        source_trace=(
            SourceTrace(
                field="observations[0]",
                source_type="IMAGE",
                source_id="image-safe-001",
            ),
            SourceTrace(
                field="candidate_promise_texts[0]",
                source_type="CHAT",
                source_id="agent-safe-001",
            ),
        ),
        candidate_promise_texts=("We will update in 48 hours.",),
    )
