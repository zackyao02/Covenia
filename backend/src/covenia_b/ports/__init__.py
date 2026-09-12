"""Frozen dependency ports and trusted clock implementations owned by BATCH-04."""

from covenia_b.ports.clock import DemoClock, SystemClock
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
from covenia_b.ports.wiring import ModulePorts

__all__ = [
    "CaseSource",
    "Clock",
    "DemoClock",
    "ExtractionStore",
    "ImageResolver",
    "LedgerRepository",
    "MetricsSink",
    "ModelProvider",
    "ModulePorts",
    "SystemClock",
    "Workbook",
]
