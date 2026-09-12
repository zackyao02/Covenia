"""Dependency-injection seam for independently composable future modules."""

from __future__ import annotations

from dataclasses import dataclass

from covenia_b.ports.contracts import (
    CaseSource,
    Clock,
    ExtractionStore,
    ImageResolver,
    LedgerRepository,
    MetricsSink,
    ModelProvider,
    Workbook,
)


@dataclass(frozen=True, slots=True)
class ModulePorts:
    """One explicit bundle of adapters; construction performs no I/O."""

    workbook: Workbook
    case_source: CaseSource
    image_resolver: ImageResolver
    model_provider: ModelProvider
    extraction_store: ExtractionStore
    ledger_repository: LedgerRepository
    metrics_sink: MetricsSink
    clock: Clock
