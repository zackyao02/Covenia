"""Bounded candidate extraction with one schema-repair attempt only."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from enum import StrEnum

from covenia_b.domain.types import (
    CandidateExtraction,
    ModelMetadata,
    SanitizedModelInput,
    SourceTrace,
)
from covenia_b.model.provider import ModelResponseInvalid
from covenia_b.model.source_validation import (
    SourceValidationError,
    SourceValidationSummary,
    validate_candidate_sources,
)
from covenia_b.ports.contracts import ModelProvider
from covenia_b.ports.errors import ModelOutputInvalid, ModelUnavailable

_MAX_CANDIDATE_ITEMS = 256
_MAX_CANDIDATE_TEXT_CHARS = 8192
_SERVER_BOUND_TEXT_PREFIXES = ("case_id=", "current_issue_sku_id=")


class ExtractionAttemptStage(StrEnum):
    INITIAL = "INITIAL"
    SCHEMA_REPAIR = "SCHEMA_REPAIR"


class ExtractionAttemptOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class CandidateQuarantineReason(StrEnum):
    SCHEMA_INVALID = "SCHEMA_INVALID"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class CandidateSchemaError(ValueError):
    """A provider result does not conform to the internal candidate contract."""


class CandidateExtractionBudgetExceeded(ModelUnavailable):
    """The initial extraction and possible repair share one wall-clock budget."""

    code = "TIME_BUDGET_EXHAUSTED"
    retryable = True


@dataclass(frozen=True, slots=True)
class ExtractionAttempt:
    attempt: int
    stage: ExtractionAttemptStage
    outcome: ExtractionAttemptOutcome


@dataclass(frozen=True, slots=True)
class ValidatedCandidateExtraction:
    """A candidate that passed structural and source validation, not a decision."""

    candidate: CandidateExtraction
    attempts: tuple[ExtractionAttempt, ...]
    source_summary: SourceValidationSummary


class QuarantinedModelOutput(ModelOutputInvalid):
    """Safe MODEL_OUTPUT_INVALID result; it intentionally exposes no raw output."""

    code = "MODEL_OUTPUT_INVALID"
    retryable = False

    def __init__(
        self,
        *,
        reason: CandidateQuarantineReason,
        attempts: tuple[ExtractionAttempt, ...],
    ) -> None:
        super().__init__("model output was quarantined")
        self.reason = reason
        self.attempts = attempts


class BoundedCandidateExtractor:
    """Run one extraction plus at most one separately prompted schema repair.

    ``initial_provider`` must use the candidate prompt and ``repair_provider``
    must use the schema-repair prompt. Both calls are enclosed in one timeout so
    retrying never doubles the caller's model wall-clock budget.
    """

    def __init__(
        self,
        initial_provider: ModelProvider,
        repair_provider: ModelProvider,
        *,
        total_timeout_seconds: float,
    ) -> None:
        if (
            not isinstance(total_timeout_seconds, int | float)
            or isinstance(total_timeout_seconds, bool)
            or not math.isfinite(total_timeout_seconds)
            or total_timeout_seconds <= 0
        ):
            raise ValueError("total_timeout_seconds must be a positive finite number")
        self._initial_provider = initial_provider
        self._repair_provider = repair_provider
        self._total_timeout_seconds = float(total_timeout_seconds)

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction:
        """Implement ModelProvider and return a source-validated candidate only."""

        return (await self.extract_with_validation(model_input)).candidate

    async def extract_with_validation(
        self,
        model_input: SanitizedModelInput,
    ) -> ValidatedCandidateExtraction:
        """Return the candidate plus safe attempt/source validation metadata."""

        provider_input = build_candidate_model_input(model_input)
        try:
            async with asyncio.timeout(self._total_timeout_seconds):
                return await self._extract_with_shared_budget(
                    source_model_input=model_input,
                    provider_input=provider_input,
                )
        except TimeoutError:
            raise CandidateExtractionBudgetExceeded(
                "candidate extraction exhausted its total timeout budget"
            ) from None

    async def _extract_with_shared_budget(
        self,
        *,
        source_model_input: SanitizedModelInput,
        provider_input: SanitizedModelInput,
    ) -> ValidatedCandidateExtraction:
        attempts: list[ExtractionAttempt] = []
        initial_candidate = await self._schema_candidate(
            self._initial_provider,
            provider_input,
        )
        if initial_candidate is None:
            attempts.append(
                ExtractionAttempt(
                    attempt=1,
                    stage=ExtractionAttemptStage.INITIAL,
                    outcome=ExtractionAttemptOutcome.SCHEMA_INVALID,
                )
            )
            repaired_candidate = await self._schema_candidate(
                self._repair_provider,
                provider_input,
            )
            if repaired_candidate is None:
                attempts.append(
                    ExtractionAttempt(
                        attempt=2,
                        stage=ExtractionAttemptStage.SCHEMA_REPAIR,
                        outcome=ExtractionAttemptOutcome.SCHEMA_INVALID,
                    )
                )
                raise QuarantinedModelOutput(
                    reason=CandidateQuarantineReason.SCHEMA_INVALID,
                    attempts=tuple(attempts),
                )
            return self._validate_sources_or_quarantine(
                candidate=repaired_candidate,
                source_model_input=source_model_input,
                attempts=attempts,
                stage=ExtractionAttemptStage.SCHEMA_REPAIR,
                attempt_number=2,
            )
        return self._validate_sources_or_quarantine(
            candidate=initial_candidate,
            source_model_input=source_model_input,
            attempts=attempts,
            stage=ExtractionAttemptStage.INITIAL,
            attempt_number=1,
        )

    async def _schema_candidate(
        self,
        provider: ModelProvider,
        provider_input: SanitizedModelInput,
    ) -> CandidateExtraction | None:
        try:
            candidate = await provider.extract(provider_input)
        except ModelOutputInvalid as error:
            if _is_schema_repairable(error):
                return None
            raise
        try:
            return validate_candidate_schema(candidate, provider_input)
        except CandidateSchemaError:
            return None

    def _validate_sources_or_quarantine(
        self,
        *,
        candidate: CandidateExtraction,
        source_model_input: SanitizedModelInput,
        attempts: list[ExtractionAttempt],
        stage: ExtractionAttemptStage,
        attempt_number: int,
    ) -> ValidatedCandidateExtraction:
        try:
            source_summary = validate_candidate_sources(candidate, source_model_input)
        except SourceValidationError:
            attempts.append(
                ExtractionAttempt(
                    attempt=attempt_number,
                    stage=stage,
                    outcome=ExtractionAttemptOutcome.SOURCE_CONFLICT,
                )
            )
            raise QuarantinedModelOutput(
                reason=CandidateQuarantineReason.SOURCE_CONFLICT,
                attempts=tuple(attempts),
            ) from None
        attempts.append(
            ExtractionAttempt(
                attempt=attempt_number,
                stage=stage,
                outcome=ExtractionAttemptOutcome.ACCEPTED,
            )
        )
        return ValidatedCandidateExtraction(
            candidate=candidate,
            attempts=tuple(attempts),
            source_summary=source_summary,
        )


def build_candidate_model_input(model_input: SanitizedModelInput) -> SanitizedModelInput:
    """Remove server-owned text fields before sending safe input to a provider.

    ``case_id`` stays only on the in-memory DTO so the adapter can bind its
    return value. The BATCH-10 HTTP request serializes ``redacted_text`` and
    verified image bytes, not this DTO's ``case_id`` field.
    """

    if (
        not isinstance(model_input, SanitizedModelInput)
        or not isinstance(model_input.redacted_text, str)
        or not model_input.redacted_text.strip()
        or not isinstance(model_input.source_ids, tuple)
        or not model_input.source_ids
        or any(
            not isinstance(source_id, str) or not source_id.strip()
            for source_id in model_input.source_ids
        )
    ):
        raise ValueError("candidate extraction requires a non-empty sanitized model input")

    retained_lines = [
        line
        for line in model_input.redacted_text.splitlines()
        if not line.startswith(_SERVER_BOUND_TEXT_PREFIXES)
    ]
    source_header = "[trusted_source_ids] " + json.dumps(
        list(model_input.source_ids),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    redacted_text = "\n".join((source_header, *retained_lines)).strip()
    return SanitizedModelInput(
        case_id=model_input.case_id,
        redacted_text=redacted_text,
        images=model_input.images,
        source_ids=model_input.source_ids,
    )


def validate_candidate_schema(
    candidate: object,
    model_input: SanitizedModelInput,
) -> CandidateExtraction:
    """Strictly validate the internal candidate DTO before any source check."""

    if not isinstance(candidate, CandidateExtraction):
        raise CandidateSchemaError("candidate must use the CandidateExtraction DTO")
    if candidate.case_id != model_input.case_id:
        raise CandidateSchemaError("candidate case binding is invalid")
    if candidate.candidate_only is not True:
        raise CandidateSchemaError("candidate-only marker is invalid")
    if not isinstance(candidate.model_metadata, ModelMetadata):
        raise CandidateSchemaError("candidate model metadata is invalid")
    _validate_text_tuple(candidate.observations)
    _validate_text_tuple(candidate.candidate_promise_texts)
    if (
        not isinstance(candidate.source_trace, tuple)
        or len(candidate.source_trace) > _MAX_CANDIDATE_ITEMS
    ):
        raise CandidateSchemaError("candidate source trace is invalid")
    if any(not isinstance(trace, SourceTrace) for trace in candidate.source_trace):
        raise CandidateSchemaError("candidate source trace is invalid")
    return candidate


def _validate_text_tuple(value: object) -> None:
    if not isinstance(value, tuple) or len(value) > _MAX_CANDIDATE_ITEMS:
        raise CandidateSchemaError("candidate text field is invalid")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or len(item) > _MAX_CANDIDATE_TEXT_CHARS
        for item in value
    ):
        raise CandidateSchemaError("candidate text field is invalid")


def _is_schema_repairable(error: ModelOutputInvalid) -> bool:
    """Retry malformed candidate structure, never model-identity failures."""

    return isinstance(error, ModelResponseInvalid) or type(error) is ModelOutputInvalid
