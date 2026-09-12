"""Tests for pure BATCH-04 ports, injection seams, and trusted clocks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from covenia_b.domain.types import CandidateExtraction, RuntimeMetrics
from covenia_b.ports import DemoClock, ModulePorts, SystemClock
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
from covenia_b.ports.errors import ClockConfigurationError


class WorkbookDouble:
    source_name = "test.xlsx"

    def sheet_names(self) -> tuple[str, ...]:
        return ("Sheet1",)

    def read_rows(self, sheet_name: str) -> tuple[dict[str, object], ...]:
        assert sheet_name == "Sheet1"
        return ()


class CaseSourceDouble:
    def get_case(self, case_id: str) -> object:
        raise AssertionError(f"not called: {case_id}")


class ImageResolverDouble:
    def resolve(self, evidence: object) -> object:
        raise AssertionError(f"not called: {evidence}")


class ModelProviderDouble:
    async def extract(self, model_input: object) -> CandidateExtraction:
        raise AssertionError(f"not called: {model_input}")


class ExtractionStoreDouble:
    def get(self, *, case_id: str, cache_key: str) -> None:
        return None

    def put(self, *, cache_key: str, candidate: CandidateExtraction) -> None:
        raise AssertionError(f"not called: {cache_key}, {candidate}")


class LedgerRepositoryDouble:
    def load(self, case_id: str) -> None:
        return None

    def save(self, snapshot: object, *, expected_version: int | None) -> object:
        raise AssertionError(f"not called: {snapshot}, {expected_version}")


class MetricsSinkDouble:
    def record(self, *, endpoint: str, metrics: RuntimeMetrics) -> None:
        raise AssertionError(f"not called: {endpoint}, {metrics}")


def test_port_protocols_are_structural_and_module_ports_are_explicit() -> None:
    workbook = WorkbookDouble()
    case_source = CaseSourceDouble()
    image_resolver = ImageResolverDouble()
    model_provider = ModelProviderDouble()
    extraction_store = ExtractionStoreDouble()
    ledger_repository = LedgerRepositoryDouble()
    metrics_sink = MetricsSinkDouble()
    clock = DemoClock(datetime(2030, 1, 1, tzinfo=timezone.utc))

    assert isinstance(workbook, Workbook)
    assert isinstance(case_source, CaseSource)
    assert isinstance(image_resolver, ImageResolver)
    assert isinstance(model_provider, ModelProvider)
    assert isinstance(extraction_store, ExtractionStore)
    assert isinstance(ledger_repository, LedgerRepository)
    assert isinstance(metrics_sink, MetricsSink)
    assert isinstance(clock, Clock)

    ports = ModulePorts(
        workbook=workbook,
        case_source=case_source,
        image_resolver=image_resolver,
        model_provider=model_provider,
        extraction_store=extraction_store,
        ledger_repository=ledger_repository,
        metrics_sink=metrics_sink,
        clock=clock,
    )
    assert ports.clock.now_rfc3339() == "2030-01-01T00:00:00Z"


def test_system_clock_is_timezone_aware_and_demo_clock_preserves_injected_offset() -> None:
    system_now = SystemClock().now()
    assert system_now.tzinfo is not None
    assert system_now.utcoffset() == timedelta(0)

    fixed = datetime(2030, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    demo = DemoClock(fixed)
    assert demo.now() is fixed
    assert demo.now_rfc3339() == "2030-01-01T08:00:00+08:00"


def test_demo_clock_refuses_naive_instants() -> None:
    with pytest.raises(ClockConfigurationError, match="timezone-aware"):
        DemoClock(datetime(2030, 1, 1))
