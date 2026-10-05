"""BATCH-19 orchestration tests for the authoritative analysis fact chain."""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from covenia_b.domain.types import (
    AnalyzeCaseRequest,
    AuditEntry,
    CandidateExtraction,
    CaseInput,
    LedgerSnapshot,
    ModelMetadata,
    SourceTrace,
)
from covenia_b.images import ManifestImageResolver
from covenia_b.ports.errors import CaseNotFound, MetricsUnavailable, ModelUnavailable
from covenia_b.services.analyze import (
    AnalysisInfrastructureError,
    AnalysisInputError,
    AnalysisModelOutputError,
    AnalysisModelUnavailable,
    AnalyzeService,
)
from covenia_b.services.fact_loader import FactLoader

PHONE_NUMBER = "13800138000"
AGENT_PROMISE = "补发单已创建，我们会在48小时内发出。"


class StaticCaseSource:
    def __init__(self, *cases: CaseInput) -> None:
        self.cases = {case.case_id: case for case in cases}
        self.calls: list[str] = []

    def get_case(self, case_id: str) -> CaseInput:
        self.calls.append(case_id)
        try:
            return self.cases[case_id]
        except KeyError as error:
            raise CaseNotFound(case_id) from error


class CapturingProvider:
    """A deliberately labelled test double; it never performs a live call."""

    def __init__(
        self,
        *,
        failure: Exception | None = None,
        invalid_source: bool = False,
        include_image_observation: bool = False,
    ) -> None:
        self.failure = failure
        self.invalid_source = invalid_source
        self.include_image_observation = include_image_observation
        self.inputs = []

    async def extract(self, model_input):  # type: ignore[no-untyped-def]
        self.inputs.append(model_input)
        if self.failure is not None:
            raise self.failure

        observations = (
            ("The submitted image appears to show outer-package damage.",)
            if self.include_image_observation
            else ()
        )
        source_trace = (
            (
                SourceTrace(
                    field="observations[0]",
                    source_type="IMAGE",
                    source_id="image-safe-001",
                ),
            )
            if self.include_image_observation
            else ()
        )
        candidate_promise_texts: tuple[str, ...] = ()
        if self.invalid_source:
            candidate_promise_texts = (AGENT_PROMISE,)
            source_trace = (
                *source_trace,
                SourceTrace(
                    field="candidate_promise_texts[0]",
                    source_type="CHAT",
                    source_id="consumer-safe-001",
                ),
            )
        return CandidateExtraction(
            case_id=model_input.case_id,
            model_metadata=ModelMetadata(
                model_id="qwen3-vl-plus",
                model_revision="batch-19-test-revision",
                prompt_version="batch-19-test-prompt",
                run_id=f"test-double-{len(self.inputs)}",
                cached_result=False,
            ),
            observations=observations,
            source_trace=source_trace,
            candidate_promise_texts=candidate_promise_texts,
        )


class MemoryLedger:
    def __init__(self, snapshot: LedgerSnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.load_calls: list[str] = []
        self.save_calls: list[tuple[LedgerSnapshot, int | None]] = []

    def load(self, case_id: str) -> LedgerSnapshot | None:
        self.load_calls.append(case_id)
        return self.snapshot

    def save(self, snapshot: LedgerSnapshot, *, expected_version: int | None) -> LedgerSnapshot:
        self.save_calls.append((snapshot, expected_version))
        expected = None if self.snapshot is None else self.snapshot.version
        assert expected_version == expected
        self.snapshot = replace(snapshot, version=1 if expected is None else expected + 1)
        return self.snapshot


class NoTouchLedger:
    def load(self, case_id: str) -> LedgerSnapshot | None:
        raise AssertionError(f"challenge analysis unexpectedly loaded {case_id}")

    def save(self, snapshot: LedgerSnapshot, *, expected_version: int | None) -> LedgerSnapshot:
        raise AssertionError("challenge analysis unexpectedly persisted a snapshot")


class RecordingMetrics:
    def __init__(self) -> None:
        self.records = []

    def record(self, *, endpoint: str, metrics) -> None:  # type: ignore[no-untyped-def]
        self.records.append((endpoint, metrics))


class UnavailableMetrics:
    def record(self, *, endpoint: str, metrics) -> None:  # type: ignore[no-untyped-def]
        del endpoint, metrics
        raise MetricsUnavailable("metrics backend unavailable")


class TamperedDetailResolver:
    def __init__(self, resolver: ManifestImageResolver) -> None:
        self._resolver = resolver

    def resolve_details(self, evidence):  # type: ignore[no-untyped-def]
        details = self._resolver.resolve_details(evidence)
        return replace(
            details,
            provider_image=replace(details.provider_image, content=b"mismatched-provider-bytes"),
        )


def test_normal_analysis_uses_real_image_binding_masks_pii_and_survives_empty_candidate(
    tmp_path: Path,
) -> None:
    case = _case_input()
    source = StaticCaseSource(case)
    provider = CapturingProvider()
    ledger = MemoryLedger()
    metrics = RecordingMetrics()
    service = _service(
        source=source,
        resolver=_manifest_resolver(tmp_path, case),
        provider=provider,
        ledger=ledger,
        metrics=metrics,
    )

    execution = asyncio.run(
        service.analyze_with_trace(
            AnalyzeCaseRequest(case_id=case.case_id),
            request_id="request-normal-001",
        )
    )

    assert execution.provider_mode == "TEST_DOUBLE"
    assert execution.provider_image_binding_verified is True
    assert execution.pii_masked_count >= 1
    assert execution.persisted is True
    assert execution.used_persisted_state is False
    assert execution.response.to_contract()["extracted_journey"]["case_id"] == case.case_id
    assert (
        execution.response.accountability_state.audit_trail[-1].request_id
        == "request-normal-001"
    )
    assert execution.response.accountability_state.open_obligation is not None
    assert (
        execution.response.accountability_state.open_obligation.milestone
        == "AWAITING_CARRIER_PICKUP"
    )
    assert execution.response.extracted_journey.promise_events[0].source_ids == ["agent-safe-001"]
    assert all(
        observation.readability == "UNKNOWN"
        for observation in execution.response.extracted_journey.image_observations
    )
    assert ledger.load_calls == [case.case_id]
    assert len(ledger.save_calls) == 1
    assert len(metrics.records) == 1
    assert metrics.records[0][0] == "analyze"

    assert len(provider.inputs) == 1
    provider_input = provider.inputs[0]
    assert PHONE_NUMBER not in provider_input.redacted_text
    assert "[PHONE_REDACTED]" in provider_input.redacted_text
    assert provider_input.images[0].evidence_id == "image-safe-001"
    assert provider_input.images[0].content_sha256 == _image_digest()
    assert PHONE_NUMBER not in json.dumps(execution.redacted_trace())


def test_same_and_changed_reruns_preserve_manual_progress_and_completed_state(
    tmp_path: Path,
) -> None:
    case = _case_input()
    source = StaticCaseSource(case)
    ledger = MemoryLedger()
    service = _service(
        source=source,
        resolver=_manifest_resolver(tmp_path, case),
        provider=CapturingProvider(),
        ledger=ledger,
    )

    first = asyncio.run(
        service.analyze_with_trace(
            AnalyzeCaseRequest(case_id=case.case_id), request_id="request-first-001"
        )
    )
    first_state = first.response.accountability_state
    assert first_state.open_obligation is not None
    assert ledger.snapshot is not None

    manual_obligation = first_state.open_obligation.model_copy(
        update={"milestone": "IN_TRANSIT"}
    )
    manual_audit = AuditEntry(
        at="2026-10-02T09:00:00+00:00",
        actor="WAREHOUSE",
        action="SHIPMENT_PICKED_UP",
        changed_fields=["open_obligation.milestone"],
        request_id="manual-event-001",
    )
    manual_state = first_state.model_copy(
        update={
            "open_obligation": manual_obligation,
            "audit_trail": [*first_state.audit_trail, manual_audit],
        }
    )
    ledger.snapshot = replace(ledger.snapshot, accountability_state=manual_state)

    same_input = asyncio.run(
        service.analyze_with_trace(
            AnalyzeCaseRequest(case_id=case.case_id), request_id="request-same-002"
        )
    )
    assert same_input.used_persisted_state is True
    assert same_input.response.accountability_state.open_obligation is not None
    assert same_input.response.accountability_state.open_obligation.milestone == "IN_TRANSIT"
    assert any(
        entry.request_id == "manual-event-001"
        for entry in same_input.response.accountability_state.audit_trail
    )

    changed = _case_input(agent_text="我们正在复核补发单状态。")
    source.cases[case.case_id] = changed
    changed_input = asyncio.run(
        service.analyze_with_trace(
            AnalyzeCaseRequest(case_id=case.case_id), request_id="request-changed-003"
        )
    )
    assert changed_input.response.accountability_state.open_obligation is not None
    assert changed_input.response.accountability_state.open_obligation.milestone == "IN_TRANSIT"

    assert ledger.snapshot is not None
    changed_state = changed_input.response.accountability_state
    assert changed_state.open_obligation is not None
    completed_obligation = changed_state.open_obligation.model_copy(
        update={"milestone": "DELIVERED", "status": "COMPLETED"}
    )
    completed_receipt = changed_state.service_progress_receipt.model_copy(
        update={"status": "COMPLETED"}
    )
    completed_state = changed_state.model_copy(
        update={
            "open_obligation": completed_obligation,
            "service_progress_receipt": completed_receipt,
        }
    )
    ledger.snapshot = replace(ledger.snapshot, accountability_state=completed_state)

    completed = asyncio.run(
        service.analyze_with_trace(
            AnalyzeCaseRequest(case_id=case.case_id), request_id="request-completed-004"
        )
    )
    assert completed.response.accountability_state.open_obligation is not None
    assert completed.response.accountability_state.open_obligation.milestone == "DELIVERED"
    assert completed.response.accountability_state.open_obligation.status == "COMPLETED"


def test_challenge_case_isolated_from_normal_ledger(tmp_path: Path) -> None:
    case = _case_input(case_id="case-challenge-001")
    service = _service(
        source=None,
        resolver=_manifest_resolver(tmp_path, case),
        provider=CapturingProvider(),
        ledger=NoTouchLedger(),
    )

    execution = asyncio.run(
        service.analyze_with_trace(
            AnalyzeCaseRequest(
                case_id=case.case_id,
                challenge_mode=True,
                case_input=case,
            ),
            request_id="request-challenge-001",
        )
    )

    assert execution.persisted is False
    assert execution.used_persisted_state is False
    assert execution.response.accountability_state.case_id == case.case_id


def test_unknown_case_has_stable_input_failure_semantics(tmp_path: Path) -> None:
    known_case = _case_input()
    provider = CapturingProvider()
    ledger = MemoryLedger()
    service = _service(
        source=StaticCaseSource(),
        resolver=_manifest_resolver(tmp_path, known_case),
        provider=provider,
        ledger=ledger,
    )

    with pytest.raises(AnalysisInputError) as raised:
        asyncio.run(
            service.analyze_with_trace(
                AnalyzeCaseRequest(case_id="case-missing-001"),
                request_id="request-missing-001",
            )
        )

    assert raised.value.code == "VALIDATION_ERROR"
    assert raised.value.retryable is False
    assert raised.value.request_id == "request-missing-001"
    assert provider.inputs == []
    assert ledger.load_calls == []
    assert ledger.save_calls == []


def test_model_failure_and_invalid_candidate_never_persist(tmp_path: Path) -> None:
    case = _case_input()
    unavailable_ledger = MemoryLedger()
    unavailable = _service(
        source=StaticCaseSource(case),
        resolver=_manifest_resolver(tmp_path / "unavailable", case),
        provider=CapturingProvider(failure=ModelUnavailable("offline")),
        ledger=unavailable_ledger,
    )

    with pytest.raises(AnalysisModelUnavailable) as unavailable_error:
        asyncio.run(
            unavailable.analyze_with_trace(
                AnalyzeCaseRequest(case_id=case.case_id), request_id="request-model-down-001"
            )
        )

    assert unavailable_error.value.code == "MODEL_UNAVAILABLE"
    assert unavailable_error.value.retryable is True
    assert unavailable_ledger.load_calls == []
    assert unavailable_ledger.save_calls == []

    invalid_ledger = MemoryLedger()
    invalid = _service(
        source=StaticCaseSource(case),
        resolver=_manifest_resolver(tmp_path / "invalid", case),
        provider=CapturingProvider(invalid_source=True),
        ledger=invalid_ledger,
    )

    with pytest.raises(AnalysisModelOutputError) as invalid_error:
        asyncio.run(
            invalid.analyze_with_trace(
                AnalyzeCaseRequest(case_id=case.case_id), request_id="request-invalid-model-001"
            )
        )

    assert invalid_error.value.code == "MODEL_OUTPUT_INVALID"
    assert invalid_error.value.retryable is False
    assert invalid_ledger.load_calls == []
    assert invalid_ledger.save_calls == []


def test_tampered_provider_image_and_metric_failure_stop_before_persistence(tmp_path: Path) -> None:
    case = _case_input()
    provider = CapturingProvider()
    ledger = MemoryLedger()
    resolver = _manifest_resolver(tmp_path / "tampered", case)
    service = _service(
        source=StaticCaseSource(case),
        resolver=TamperedDetailResolver(resolver),
        provider=provider,
        ledger=ledger,
    )

    with pytest.raises(AnalysisInputError):
        asyncio.run(
            service.analyze_with_trace(
                AnalyzeCaseRequest(case_id=case.case_id), request_id="request-tampered-001"
            )
        )

    assert provider.inputs == []
    assert ledger.load_calls == []
    assert ledger.save_calls == []

    metrics_ledger = MemoryLedger()
    metrics_service = _service(
        source=StaticCaseSource(case),
        resolver=_manifest_resolver(tmp_path / "metrics", case),
        provider=CapturingProvider(),
        ledger=metrics_ledger,
        metrics=UnavailableMetrics(),
    )

    with pytest.raises(AnalysisInfrastructureError) as metrics_error:
        asyncio.run(
            metrics_service.analyze_with_trace(
                AnalyzeCaseRequest(case_id=case.case_id), request_id="request-metrics-001"
            )
        )

    assert metrics_error.value.code == "INTERNAL_ERROR"
    assert metrics_error.value.retryable is True
    assert metrics_ledger.load_calls == [case.case_id]
    assert metrics_ledger.save_calls == []


def _service(
    *,
    source: StaticCaseSource | None,
    resolver,
    provider: CapturingProvider,
    ledger,
    metrics=None,
) -> AnalyzeService:
    return AnalyzeService(
        fact_loader=FactLoader(
            case_source=source,
            image_resolver=resolver,
            image_no_pii_declarations={"image-safe-001": True},
        ),
        provider=provider,
        ledger_repository=ledger,
        metrics_sink=metrics,
        provider_mode="TEST_DOUBLE",
        request_id_factory=lambda: "generated-request-id",
    )


def _case_input(
    *,
    case_id: str = "case-safe-001",
    agent_text: str = AGENT_PROMISE,
) -> CaseInput:
    return CaseInput.model_validate(
        {
            "case_id": case_id,
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-safe-001",
                "augmentation_notes": ["BATCH-19 isolated orchestration test"],
            },
            "evaluation_time": "2026-10-02T10:00:00+00:00",
            "conversation": [
                {
                    "message_id": "consumer-safe-001",
                    "timestamp": "2026-10-02T08:00:00+00:00",
                    "speaker": "CONSUMER",
                    "text": f"My parcel is damaged. Contact phone: {PHONE_NUMBER}.",
                    "source_kind": "COMPETITION_MOCK",
                },
                {
                    "message_id": "agent-safe-001",
                    "timestamp": "2026-10-02T08:15:00+00:00",
                    "speaker": "AGENT",
                    "text": agent_text,
                    "source_kind": "COMPETITION_MOCK",
                },
            ],
            "order": {
                "order_id": "order-safe-001",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "item-safe-001",
                        "sku_id": "sku-safe-001",
                        "product_name": "Safe Product",
                        "batch_code": None,
                        "item_role": "PRIMARY",
                    }
                ],
                "original_logistics_number": "logistics-safe-001",
            },
            "service_tickets": [
                {
                    "ticket_id": "ticket-safe-001",
                    "ticket_type": "REPLACEMENT",
                    "status": "OPEN",
                    "assignee_id": "warehouse-safe-001",
                    "executor_name": "Warehouse",
                    "replacement_logistics_number": None,
                    "created_at": "2026-10-02T08:10:00+00:00",
                    "completed_at": None,
                    "source_sheet": "service-ticket-test",
                }
            ],
            "evidence_images": [
                {
                    "evidence_id": "image-safe-001",
                    "file_name": "image-safe-001.png",
                    "submitted_at": "2026-10-02T08:05:00+00:00",
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": "consumer-safe-001",
                    "competition_reference_path": None,
                }
            ],
            "current_issue": {
                "fulfillment_item_id": "item-safe-001",
                "sku_id": "sku-safe-001",
                "issue_type": "PACKAGE_DAMAGE",
                "affected_component": "PUMP",
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )


def _manifest_resolver(tmp_path: Path, case: CaseInput) -> ManifestImageResolver:
    tmp_path.mkdir(parents=True, exist_ok=True)
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    content = _png_bytes()
    image_path = evidence_root / case.evidence_images[0].file_name
    image_path.write_bytes(content)
    manifest_path = tmp_path / "images-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "evidence_id": "image-safe-001",
                        "file_name": "image-safe-001.png",
                        "repo_target_path": "handoff/a/image-safe-001.png",
                        "source_message_id": "consumer-safe-001",
                        "source_kind": "TEAM_SYNTHETIC_RECREATION",
                        "competition_reference_path": None,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "bytes": len(content),
                        "mime": "image/png",
                        "dimensions": {"width": 1, "height": 1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return ManifestImageResolver.from_manifest_file(
        manifest_path=manifest_path,
        evidence_root=evidence_root,
    )


def _image_digest() -> str:
    return hashlib.sha256(_png_bytes()).hexdigest()


def _png_bytes() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(b"\x00\x00")
    ) + chunk(b"IEND", b"")
