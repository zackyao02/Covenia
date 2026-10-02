"""Validate that an untrusted candidate can be traced to safe input sources."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from covenia_b.domain.types import CandidateExtraction, SanitizedModelInput, SourceTrace

_MESSAGE_LINE = re.compile(
    r"^\[message_id=(?P<source_id>[^\s\]]+) "
    r"timestamp=(?P<timestamp>[^\s\]]+) "
    r"speaker=(?P<speaker>AGENT|CONSUMER)\]\s*(?P<text>.*)$"
)
_ORDER_LINE = re.compile(r"^order_id=(?P<source_id>[^\s]+)\s*$")
_FIELD_REFERENCE = re.compile(
    r"^(?P<collection>observations|candidate_promise_texts)\["
    r"(?P<index>0|[1-9][0-9]*)\]$"
)
_IMAGE_INSTRUCTION_LANGUAGE = re.compile(
    r"(?:\b(?:ignore|instruction|system\s+prompt|prompt\s+injection|activate|activation|"
    r"deadline|refund|compensation|approve|evidence\s+(?:is\s+)?valid)\b|"
    r"忽略|指令|提示词|证据有效|已核实|激活|截止|退款|赔偿|批准)",
    re.IGNORECASE,
)


class SourceValidationCode(StrEnum):
    """Stable, source-free reasons for candidate quarantine."""

    INVALID_MODEL_INPUT = "INVALID_MODEL_INPUT"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
    UNVERIFIED_SOURCE = "UNVERIFIED_SOURCE"
    SOURCE_TYPE_MISMATCH = "SOURCE_TYPE_MISMATCH"
    DUPLICATE_TRACE = "DUPLICATE_TRACE"
    INVALID_FIELD_REFERENCE = "INVALID_FIELD_REFERENCE"
    MISSING_FIELD_TRACE = "MISSING_FIELD_TRACE"
    PROMISE_NOT_AGENT_QUOTE = "PROMISE_NOT_AGENT_QUOTE"
    IMAGE_INSTRUCTION_TEXT = "IMAGE_INSTRUCTION_TEXT"


class SourceValidationError(ValueError):
    """A candidate referenced an absent, mismatched, or unsafe source."""

    def __init__(self, code: SourceValidationCode) -> None:
        super().__init__(f"candidate source validation failed: {code.value}")
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceValidationSummary:
    """Safe counters retained after a candidate has passed provenance checks."""

    trusted_source_count: int
    traced_field_count: int
    agent_quote_count: int
    image_observation_count: int


@dataclass(frozen=True, slots=True)
class _TrustedSource:
    source_id: str
    source_type: str
    speaker: str | None = None
    redacted_text: str | None = None


def validate_candidate_sources(
    candidate: CandidateExtraction,
    model_input: SanitizedModelInput,
) -> SourceValidationSummary:
    """Require every candidate field to resolve to a trustworthy input source.

    This is intentionally stricter than the HTTP adapter's source-ID membership
    check. It reconstructs the BATCH-07 canonical redacted chat envelope so a
    promise may only quote a declared AGENT message. Source IDs with no safely
    typed source text remain unverified and therefore cannot prove a fact.
    """

    catalog, declared_source_ids = _build_catalog(model_input)
    traces_by_field: dict[str, list[tuple[SourceTrace, _TrustedSource]]] = defaultdict(list)
    seen_traces: set[tuple[str, str, str]] = set()

    for trace in candidate.source_trace:
        parsed_reference = _parse_field_reference(trace.field, candidate)
        if trace.source_id not in declared_source_ids:
            raise SourceValidationError(SourceValidationCode.UNKNOWN_SOURCE)
        trusted_source = catalog.get(trace.source_id)
        if trusted_source is None:
            raise SourceValidationError(SourceValidationCode.UNVERIFIED_SOURCE)
        if trace.source_type != trusted_source.source_type:
            raise SourceValidationError(SourceValidationCode.SOURCE_TYPE_MISMATCH)
        trace_key = (trace.field, trace.source_type, trace.source_id)
        if trace_key in seen_traces:
            raise SourceValidationError(SourceValidationCode.DUPLICATE_TRACE)
        seen_traces.add(trace_key)
        _validate_image_trace(parsed_reference, trusted_source, candidate)
        traces_by_field[trace.field].append((trace, trusted_source))

    expected_fields = {
        *(f"observations[{index}]" for index in range(len(candidate.observations))),
        *(
            f"candidate_promise_texts[{index}]"
            for index in range(len(candidate.candidate_promise_texts))
        ),
    }
    if set(traces_by_field) != expected_fields:
        raise SourceValidationError(SourceValidationCode.MISSING_FIELD_TRACE)

    image_observation_count = 0
    for index, observation in enumerate(candidate.observations):
        source_traces = traces_by_field[f"observations[{index}]"]
        if any(source.source_type == "IMAGE" for _, source in source_traces):
            image_observation_count += 1
            if _IMAGE_INSTRUCTION_LANGUAGE.search(observation):
                raise SourceValidationError(SourceValidationCode.IMAGE_INSTRUCTION_TEXT)

    for index, promise_text in enumerate(candidate.candidate_promise_texts):
        source_traces = traces_by_field[f"candidate_promise_texts[{index}]"]
        for _, source in source_traces:
            if (
                source.source_type != "CHAT"
                or source.speaker != "AGENT"
                or source.redacted_text is None
                or not _is_quote_in_source(promise_text, source.redacted_text)
            ):
                raise SourceValidationError(SourceValidationCode.PROMISE_NOT_AGENT_QUOTE)

    return SourceValidationSummary(
        trusted_source_count=len(catalog),
        traced_field_count=len(expected_fields),
        agent_quote_count=len(candidate.candidate_promise_texts),
        image_observation_count=image_observation_count,
    )


def _build_catalog(
    model_input: SanitizedModelInput,
) -> tuple[dict[str, _TrustedSource], frozenset[str]]:
    if (
        not isinstance(model_input, SanitizedModelInput)
        or not isinstance(model_input.case_id, str)
        or not model_input.case_id.strip()
        or not isinstance(model_input.redacted_text, str)
        or not model_input.redacted_text.strip()
        or not isinstance(model_input.source_ids, tuple)
        or not model_input.source_ids
        or any(
            not isinstance(source_id, str) or not source_id.strip()
            for source_id in model_input.source_ids
        )
        or len(set(model_input.source_ids)) != len(model_input.source_ids)
    ):
        raise SourceValidationError(SourceValidationCode.INVALID_MODEL_INPUT)

    declared_source_ids = frozenset(model_input.source_ids)
    catalog: dict[str, _TrustedSource] = {}

    for image in model_input.images:
        if image.evidence_id not in declared_source_ids:
            raise SourceValidationError(SourceValidationCode.INVALID_MODEL_INPUT)
        _put_source(
            catalog,
            _TrustedSource(source_id=image.evidence_id, source_type="IMAGE"),
        )

    for line in model_input.redacted_text.splitlines():
        message_match = _MESSAGE_LINE.fullmatch(line)
        if message_match is not None:
            source_id = message_match.group("source_id")
            if source_id not in declared_source_ids:
                raise SourceValidationError(SourceValidationCode.INVALID_MODEL_INPUT)
            _put_source(
                catalog,
                _TrustedSource(
                    source_id=source_id,
                    source_type="CHAT",
                    speaker=message_match.group("speaker"),
                    redacted_text=message_match.group("text"),
                ),
            )
            continue
        order_match = _ORDER_LINE.fullmatch(line)
        if order_match is not None:
            source_id = order_match.group("source_id")
            if source_id not in declared_source_ids:
                raise SourceValidationError(SourceValidationCode.INVALID_MODEL_INPUT)
            _put_source(
                catalog,
                _TrustedSource(source_id=source_id, source_type="ORDER"),
            )

    return catalog, declared_source_ids


def _put_source(catalog: dict[str, _TrustedSource], source: _TrustedSource) -> None:
    existing = catalog.get(source.source_id)
    if existing is not None and existing != source:
        raise SourceValidationError(SourceValidationCode.INVALID_MODEL_INPUT)
    catalog[source.source_id] = source


def _parse_field_reference(
    field: str,
    candidate: CandidateExtraction,
) -> tuple[str, int]:
    match = _FIELD_REFERENCE.fullmatch(field)
    if match is None:
        raise SourceValidationError(SourceValidationCode.INVALID_FIELD_REFERENCE)
    collection = match.group("collection")
    index = int(match.group("index"))
    collection_length = (
        len(candidate.observations)
        if collection == "observations"
        else len(candidate.candidate_promise_texts)
    )
    if index >= collection_length:
        raise SourceValidationError(SourceValidationCode.INVALID_FIELD_REFERENCE)
    return collection, index


def _validate_image_trace(
    parsed_reference: tuple[str, int],
    source: _TrustedSource,
    candidate: CandidateExtraction,
) -> None:
    if source.source_type != "IMAGE":
        return
    collection, index = parsed_reference
    if collection != "observations":
        raise SourceValidationError(SourceValidationCode.IMAGE_INSTRUCTION_TEXT)
    if _IMAGE_INSTRUCTION_LANGUAGE.search(candidate.observations[index]):
        raise SourceValidationError(SourceValidationCode.IMAGE_INSTRUCTION_TEXT)


def _is_quote_in_source(quote: str, source_text: str) -> bool:
    return _normalize_for_quote(quote) in _normalize_for_quote(source_text)


def _normalize_for_quote(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
