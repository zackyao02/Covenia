from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from covenia_b.domain.types import (
    CandidateExtraction,
    ModelMetadata,
    ResolvedImage,
    SanitizedModelInput,
    SourceTrace,
)
from covenia_b.model.extraction import (
    BoundedCandidateExtractor,
    CandidateQuarantineReason,
    ExtractionAttemptOutcome,
    QuarantinedModelOutput,
    build_candidate_model_input,
)
from covenia_b.model.provider import ModelIdentityMismatch, ModelResponseInvalid


class ScriptedProvider:
    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.calls: list[SanitizedModelInput] = []

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction:
        self.calls.append(model_input)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result  # type: ignore[return-value]


def test_valid_candidate_is_bound_to_safe_prompt_input_and_never_retries() -> None:
    source_input = _model_input()
    initial = ScriptedProvider(_valid_candidate(source_input))
    repair = ScriptedProvider(_valid_candidate(source_input))

    result = asyncio.run(
        BoundedCandidateExtractor(
            initial,
            repair,
            total_timeout_seconds=1,
        ).extract_with_validation(source_input)
    )

    assert [attempt.outcome for attempt in result.attempts] == [ExtractionAttemptOutcome.ACCEPTED]
    assert len(initial.calls) == 1
    assert repair.calls == []
    sent_text = initial.calls[0].redacted_text
    assert "case_id=case-safe-001" not in sent_text
    assert "current_issue_sku_id=sku-safe-001" not in sent_text
    assert "[trusted_source_ids]" in sent_text
    assert result.candidate.case_id == source_input.case_id
    assert result.candidate.candidate_only is True
    assert result.source_summary.agent_quote_count == 1


def test_schema_invalid_first_response_uses_exactly_one_repair_provider_call() -> None:
    source_input = _model_input()
    initial = ScriptedProvider(ModelResponseInvalid("malformed candidate"))
    repair = ScriptedProvider(_valid_candidate(source_input))

    result = asyncio.run(
        BoundedCandidateExtractor(
            initial,
            repair,
            total_timeout_seconds=1,
        ).extract_with_validation(source_input)
    )

    assert [attempt.outcome for attempt in result.attempts] == [
        ExtractionAttemptOutcome.SCHEMA_INVALID,
        ExtractionAttemptOutcome.ACCEPTED,
    ]
    assert len(initial.calls) == 1
    assert len(repair.calls) == 1
    assert repair.calls[0].redacted_text == initial.calls[0].redacted_text


def test_model_identity_failure_is_not_misclassified_as_schema_repairable() -> None:
    source_input = _model_input()
    initial = ScriptedProvider(ModelIdentityMismatch("unexpected model revision"))
    repair = ScriptedProvider(_valid_candidate(source_input))
    extractor = BoundedCandidateExtractor(initial, repair, total_timeout_seconds=1)

    with pytest.raises(ModelIdentityMismatch):
        asyncio.run(extractor.extract(source_input))

    assert len(initial.calls) == 1
    assert repair.calls == []


def test_two_schema_failures_are_quarantined_after_at_most_two_calls() -> None:
    source_input = _model_input()
    initial = ScriptedProvider(object())
    repair = ScriptedProvider(ModelResponseInvalid("still malformed"))

    extractor = BoundedCandidateExtractor(initial, repair, total_timeout_seconds=1)

    with pytest.raises(QuarantinedModelOutput) as raised:
        asyncio.run(extractor.extract_with_validation(source_input))

    assert raised.value.reason is CandidateQuarantineReason.SCHEMA_INVALID
    assert [attempt.outcome for attempt in raised.value.attempts] == [
        ExtractionAttemptOutcome.SCHEMA_INVALID,
        ExtractionAttemptOutcome.SCHEMA_INVALID,
    ]
    assert len(initial.calls) == 1
    assert len(repair.calls) == 1
    assert "malformed" not in str(raised.value)


def test_source_conflict_is_quarantined_without_a_repair_call() -> None:
    source_input = _model_input()
    consumer_promise = replace(
        _valid_candidate(source_input),
        source_trace=(
            SourceTrace(field="observations[0]", source_type="IMAGE", source_id="image-safe-001"),
            SourceTrace(
                field="candidate_promise_texts[0]",
                source_type="CHAT",
                source_id="consumer-safe-001",
            ),
        ),
    )
    initial = ScriptedProvider(consumer_promise)
    repair = ScriptedProvider(_valid_candidate(source_input))

    extractor = BoundedCandidateExtractor(initial, repair, total_timeout_seconds=1)

    with pytest.raises(QuarantinedModelOutput) as raised:
        asyncio.run(extractor.extract_with_validation(source_input))

    assert raised.value.reason is CandidateQuarantineReason.SOURCE_CONFLICT
    assert raised.value.code == "MODEL_OUTPUT_INVALID"
    assert [attempt.outcome for attempt in raised.value.attempts] == [
        ExtractionAttemptOutcome.SOURCE_CONFLICT
    ]
    assert len(initial.calls) == 1
    assert repair.calls == []


def test_candidate_prompt_input_keeps_only_sources_and_masked_text() -> None:
    source_input = _model_input()

    provider_input = build_candidate_model_input(source_input)

    assert provider_input.case_id == source_input.case_id
    assert "case_id=" not in provider_input.redacted_text
    assert "current_issue_sku_id=" not in provider_input.redacted_text
    assert "[PHONE_REDACTED]" in provider_input.redacted_text
    assert provider_input.images == source_input.images


def test_standard_extract_keeps_the_candidate_only_model_provider_port() -> None:
    source_input = _model_input()
    extractor = BoundedCandidateExtractor(
        ScriptedProvider(_valid_candidate(source_input)),
        ScriptedProvider(_valid_candidate(source_input)),
        total_timeout_seconds=1,
    )

    candidate = asyncio.run(extractor.extract(source_input))

    assert isinstance(candidate, CandidateExtraction)
    assert candidate.candidate_only is True


def _model_input() -> SanitizedModelInput:
    return SanitizedModelInput(
        case_id="case-safe-001",
        redacted_text="\n".join(
            (
                "case_id=case-safe-001",
                "order_id=order-safe-001",
                "current_issue_sku_id=sku-safe-001",
                "[message_id=agent-safe-001 timestamp=2026-10-02T09:00:00+08:00 speaker=AGENT] "
                "We will send a replacement within 48 hours if photo review confirms the damage.",
                "[message_id=consumer-safe-001 timestamp=2026-10-02T09:01:00+08:00 "
                "speaker=CONSUMER] "
                "I want a full refund. Contact me at [PHONE_REDACTED].",
            )
        ),
        images=(
            ResolvedImage(
                evidence_id="image-safe-001",
                media_type="image/png",
                content_sha256="0" * 64,
                byte_length=1,
            ),
        ),
        source_ids=("order-safe-001", "agent-safe-001", "consumer-safe-001", "image-safe-001"),
    )


def _valid_candidate(model_input: SanitizedModelInput) -> CandidateExtraction:
    return CandidateExtraction(
        case_id=model_input.case_id,
        model_metadata=ModelMetadata(
            model_id="qwen3-vl-plus",
            model_revision="revision-safe",
            prompt_version="candidate-extraction-v1",
            run_id="run-safe",
            cached_result=False,
        ),
        observations=("outer package appears visibly damaged",),
        source_trace=(
            SourceTrace(field="observations[0]", source_type="IMAGE", source_id="image-safe-001"),
            SourceTrace(
                field="candidate_promise_texts[0]",
                source_type="CHAT",
                source_id="agent-safe-001",
            ),
        ),
        candidate_promise_texts=(
            "We will send a replacement within 48 hours if photo review confirms the damage.",
        ),
    )
