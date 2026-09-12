"""Pure module ports frozen for future BATCH consumers.

These interfaces deliberately contain no FastAPI, frontend, provider, database,
or business-rule implementation.  An adapter may raise only the documented
port errors; a later service owns mapping them to a public API envelope.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from covenia_b.domain.types import (
    CandidateExtraction,
    CaseInput,
    EvidenceImage,
    LedgerSnapshot,
    ResolvedImage,
    RuntimeMetrics,
    SanitizedModelInput,
)
from covenia_b.ports.errors import (
    CaseNotFound,
    ExtractionStoreUnavailable,
    ImageUnavailable,
    ImageUnreadable,
    LedgerConflict,
    LedgerUnavailable,
    MetricsUnavailable,
    ModelOutputInvalid,
    ModelUnavailable,
    WorkbookUnavailable,
)

WorkbookRow = Mapping[str, object]
EndpointName = Literal["analyze", "evaluate", "approve", "shipment"]


@runtime_checkable
class Workbook(Protocol):
    """Read-only workbook access for the importing batch.

    Implementations raise ``WorkbookUnavailable`` for access or parsing faults
    and return source rows without inventing business meaning.
    """

    @property
    def source_name(self) -> str: ...

    def sheet_names(self) -> Sequence[str]: ...

    def read_rows(self, sheet_name: str) -> Iterable[WorkbookRow]: ...


@runtime_checkable
class CaseSource(Protocol):
    """Return a schema-backed case input or raise ``CaseNotFound``."""

    def get_case(self, case_id: str) -> CaseInput: ...


@runtime_checkable
class ImageResolver(Protocol):
    """Resolve declared image metadata to a content-addressed internal handle."""

    def resolve(self, evidence: EvidenceImage) -> ResolvedImage: ...


@runtime_checkable
class ModelProvider(Protocol):
    """Produce an untrusted candidate extraction from sanitized input only."""

    async def extract(self, model_input: SanitizedModelInput) -> CandidateExtraction: ...


@runtime_checkable
class ExtractionStore(Protocol):
    """Persist only candidate extractions; it cannot write accountability facts."""

    def get(self, *, case_id: str, cache_key: str) -> CandidateExtraction | None: ...

    def put(self, *, cache_key: str, candidate: CandidateExtraction) -> None: ...


@runtime_checkable
class LedgerRepository(Protocol):
    """Load and atomically save internal snapshots using optimistic versions."""

    def load(self, case_id: str) -> LedgerSnapshot | None: ...

    def save(self, snapshot: LedgerSnapshot, *, expected_version: int | None) -> LedgerSnapshot: ...


@runtime_checkable
class MetricsSink(Protocol):
    """Record safe aggregate metrics without changing the core decision state."""

    def record(self, *, endpoint: EndpointName, metrics: RuntimeMetrics) -> None: ...


@runtime_checkable
class Clock(Protocol):
    """Return a trusted, timezone-aware server instant for service-owned time."""

    def now(self) -> datetime: ...


PORT_ERROR_RESPONSIBILITIES: dict[str, tuple[type[Exception], ...]] = {
    "Workbook": (WorkbookUnavailable,),
    "CaseSource": (CaseNotFound,),
    "ImageResolver": (ImageUnavailable, ImageUnreadable),
    "ModelProvider": (ModelUnavailable, ModelOutputInvalid),
    "ExtractionStore": (ExtractionStoreUnavailable,),
    "LedgerRepository": (LedgerConflict, LedgerUnavailable),
    "MetricsSink": (MetricsUnavailable,),
    "Clock": (),
}
