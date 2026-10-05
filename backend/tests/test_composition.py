"""Composition tests: one application root, four endpoints, honest blockers.

Every test drives the real ASGI application, the real BATCH-18 SQLite ledger,
and the four reviewed routers.  The model provider and the image resolver are
labelled test doubles only where a live Qwen deployment or A-line evidence root
would otherwise be required; the composition decisions themselves (routers,
repository, clock, metrics, cache policy, verified-journey seam, CORS, request
trace) are the production ones.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from covenia_b.api.base import REQUEST_ID_HEADER
from covenia_b.domain.types import (
    AccountabilityState,
    CandidateExtraction,
    CaseInput,
    CompiledCommitment,
    CompiledCommitments,
    LedgerSnapshot,
    ModelMetadata,
    ResolvedImage,
    SourceTrace,
)
from covenia_b.images import EvidenceProvenance, ProviderImageInput, ResolvedEvidence
from covenia_b.main import create_app
from covenia_b.ports.clock import DemoClock
from covenia_b.ports.errors import ModelUnavailable
from covenia_b.runtime import (
    EXPECTED_BUSINESS_ROUTES,
    RuntimeConfigurationError,
    RuntimeOverrides,
    build_runtime,
    compose_application,
    installed_route_inventory,
    verify_single_composition,
)
from covenia_b.settings import Settings

MESSAGE_LINE = re.compile(
    r"^\[message_id=(?P<source_id>[^\s\]]+) "
    r"timestamp=(?P<timestamp>[^\s\]]+) "
    r"speaker=(?P<speaker>AGENT|CONSUMER)\]\s*(?P<text>.*)$"
)

CASE_ID = "CASE-COMPOSITION-ANALYZE-001"
APPROVE_CASE_ID = "CASE-COMPOSITION-APPROVE-001"
CONSUMER_MESSAGE_ID = "MSG-COMPOSITION-CONSUMER"
AGENT_MESSAGE_ID = "MSG-COMPOSITION-AGENT"
EVIDENCE_ID = "IMG-COMPOSITION-001"
TICKET_ID = "TICKET-COMPOSITION-001"
PROMISE_TEXT = "补发单已创建，我们会在48小时内发出。"
IMAGE_BYTES = b"\xff\xd8\xff\xe0composition-probe"
IMAGE_SHA256 = hashlib.sha256(IMAGE_BYTES).hexdigest()
APPROVED_AT = datetime(2030, 1, 1, 10, 2, tzinfo=UTC)
DEADLINE = "2030-01-01T12:00:00+00:00"
NEXT_CHECK = "2030-01-01T12:15:00+00:00"
APPROVED_ORIGIN = "http://127.0.0.1:4173"


# --------------------------------------------------------------------------- #
# Labelled doubles and fixtures
# --------------------------------------------------------------------------- #


def _case_input() -> CaseInput:
    return CaseInput.model_validate(
        {
            "case_id": CASE_ID,
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-composition",
                "augmentation_notes": [],
            },
            "evaluation_time": "2030-01-01T10:00:00+00:00",
            "conversation": [
                {
                    "message_id": CONSUMER_MESSAGE_ID,
                    "timestamp": "2030-01-01T09:00:00+00:00",
                    "speaker": "CONSUMER",
                    "text": "The pump arrived cracked and I cannot use it.",
                    "source_kind": "COMPETITION_MOCK",
                },
                {
                    "message_id": AGENT_MESSAGE_ID,
                    "timestamp": "2030-01-01T09:05:00+00:00",
                    "speaker": "AGENT",
                    "text": PROMISE_TEXT,
                    "source_kind": "COMPETITION_MOCK",
                },
            ],
            "order": {
                "order_id": "ORDER-COMPOSITION-001",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "ITEM-COMPOSITION-001",
                        "sku_id": "SKU-COMPOSITION-001",
                        "product_name": "Demo serum",
                        "batch_code": None,
                        "item_role": "PRIMARY",
                    }
                ],
                "original_logistics_number": "LOGISTICS-COMPOSITION-001",
            },
            "service_tickets": [
                {
                    "ticket_id": TICKET_ID,
                    "ticket_type": "REPLACEMENT",
                    "status": "OPEN",
                    "assignee_id": "AGENT-COMPOSITION-001",
                    "executor_name": "WAREHOUSE",
                    "replacement_logistics_number": None,
                    "created_at": "2030-01-01T09:06:00+00:00",
                    "completed_at": None,
                    "source_sheet": "service_tickets",
                }
            ],
            "evidence_images": [
                {
                    "evidence_id": EVIDENCE_ID,
                    "file_name": "composition.jpg",
                    "submitted_at": "2030-01-01T09:01:00+00:00",
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": CONSUMER_MESSAGE_ID,
                    "competition_reference_path": None,
                }
            ],
            "current_issue": {
                "fulfillment_item_id": "ITEM-COMPOSITION-001",
                "sku_id": "SKU-COMPOSITION-001",
                "issue_type": "PACKAGE_DAMAGE",
                "affected_component": "PUMP",
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )


class StaticCaseSource:
    """Return one accepted case input; it never invents a case."""

    def __init__(self, case: CaseInput) -> None:
        self._case = case
        self.calls: list[str] = []

    def get_case(self, case_id: str) -> CaseInput:
        self.calls.append(case_id)
        if case_id != self._case.case_id:
            raise ValueError("the requested case is not registered in this test source")
        return self._case


class StubImageResolver:
    """A labelled image double that still returns provider-safe, bound bytes."""

    def __init__(self, case: CaseInput) -> None:
        self._evidence = case.evidence_images[0]

    def resolve(self, evidence: Any) -> ResolvedImage:
        return self.resolve_details(evidence).handle

    def resolve_details(self, evidence: Any) -> ResolvedEvidence:
        if getattr(evidence, "evidence_id", None) != self._evidence.evidence_id:
            raise ValueError("unregistered evidence")
        return ResolvedEvidence(
            handle=ResolvedImage(
                evidence_id=self._evidence.evidence_id,
                media_type="image/jpeg",
                content_sha256=IMAGE_SHA256,
                byte_length=len(IMAGE_BYTES),
            ),
            provider_image=ProviderImageInput(
                content=IMAGE_BYTES,
                media_type="image/jpeg",
                content_sha256=IMAGE_SHA256,
                byte_length=len(IMAGE_BYTES),
                width=8,
                height=8,
            ),
            provenance=EvidenceProvenance(
                evidence_id=self._evidence.evidence_id,
                source_message_id=self._evidence.source_message_id,
                source_kind=self._evidence.source_kind,
                competition_reference_path=self._evidence.competition_reference_path,
            ),
        )


class StubProvider:
    """A labelled candidate double: it quotes only the sanitized AGENT line."""

    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        self.calls = 0
        self.delay_seconds = delay_seconds

    async def extract(self, model_input: Any) -> CandidateExtraction:
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        images = tuple(model_input.images)
        observations = (
            ("The submitted image shows a cracked pump component.",) if images else ()
        )
        traces = (
            [
                SourceTrace(
                    field="observations[0]",
                    source_type="IMAGE",
                    source_id=images[0].evidence_id,
                )
            ]
            if images
            else []
        )
        promises: tuple[str, ...] = ()
        for line in model_input.redacted_text.splitlines():
            match = MESSAGE_LINE.fullmatch(line)
            if match is not None and match.group("speaker") == "AGENT":
                promises = (match.group("text"),)
                traces.append(
                    SourceTrace(
                        field="candidate_promise_texts[0]",
                        source_type="CHAT",
                        source_id=match.group("source_id"),
                    )
                )
                break
        return CandidateExtraction(
            case_id=model_input.case_id,
            model_metadata=ModelMetadata(
                model_id="Qwen/Qwen2-VL-2B-Instruct",
                model_revision="composition-test",
                prompt_version="candidate-extraction-v1",
                run_id=f"composition-double-{self.calls}",
                cached_result=False,
            ),
            observations=observations,
            source_trace=tuple(traces),
            candidate_promise_texts=promises,
        )


class UnavailableProvider:
    """A labelled double for an upstream model failure; it returns no candidate."""

    async def extract(self, model_input: Any) -> CandidateExtraction:
        del model_input
        raise ModelUnavailable("upstream model is unavailable")


@pytest.fixture
def accepted_image_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "images-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "ACCEPTED",
                "images": [{"evidence_id": EVIDENCE_ID, "no_pii_declaration": True}],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _settings(tmp_path: Path, manifest: Path) -> Settings:
    return Settings(
        sqlite_path=tmp_path / "ledger.sqlite3",
        request_log_path=tmp_path / "requests.jsonl",
        image_manifest_path=manifest,
    )


def _runtime(
    settings: Settings,
    *,
    provider: Any | None = None,
    case: CaseInput | None = None,
    **overrides: Any,
) -> Any:
    accepted = case or _case_input()
    return build_runtime(
        settings,
        overrides=RuntimeOverrides(
            case_source=StaticCaseSource(accepted),
            image_resolver=StubImageResolver(accepted),
            model_provider=provider if provider is not None else StubProvider(),
            clock=DemoClock(APPROVED_AT),
            provider_mode="TEST_DOUBLE",
            **overrides,
        ),
    )


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _seeded_state(case_id: str) -> AccountabilityState:
    return AccountabilityState.model_validate(
        {
            "case_id": case_id,
            "case_status": "READY_FOR_BRAND",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": "VALID",
            "current_scope": {
                "order_id": "ORDER-COMPOSITION-APPROVE",
                "fulfillment_item_id": "ITEM-COMPOSITION-APPROVE",
                "sku_id": "SKU-COMPOSITION-APPROVE",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "active_commitments": [
                {
                    "promise_type": "REPLACEMENT_DISPATCH",
                    "raw_text": PROMISE_TEXT,
                    "status": "ACTIVE",
                    "deadline": DEADLINE,
                    "source_ids": ["SOURCE-COMPOSITION-APPROVE"],
                }
            ],
            "prohibited_actions": [],
            "experience_gap_diagnosis": {
                "consumer_expression": "A reliable update is needed.",
                "traceable_service_facts": [
                    {
                        "fact_type": "EVIDENCE_SUBMITTED",
                        "statement": "Server facts include current evidence.",
                        "source_ids": ["EVIDENCE-COMPOSITION-APPROVE"],
                    }
                ],
                "deterioration_cause": "Fulfillment needs ownership.",
                "latent_need": "A reliable next update.",
                "responsibility_judgment": {
                    "consumer_input_complete": True,
                    "accountable_side": "BRAND",
                },
                "action_impacts": ["START_PROACTIVE_UPDATE"],
                "reply_strategy": "The brand will provide an update.",
            },
            "open_obligation": None,
            "service_progress_receipt": None,
            "experience_risk": "MEDIUM",
            "audit_trail": [
                {
                    "at": "2030-01-01T10:00:00+00:00",
                    "actor": "ANALYZE_SERVICE",
                    "action": "ANALYZED",
                    "changed_fields": ["accountability_state"],
                    "request_id": "analyze-seed-001",
                }
            ],
        }
    )


def _seed_approve_case(runtime: Any, case_id: str = APPROVE_CASE_ID) -> None:
    runtime.repository.save(
        LedgerSnapshot(
            case_id=case_id,
            version=0,
            event_high_watermark=None,
            accountability_state=_seeded_state(case_id),
            compiled_commitments=CompiledCommitments(
                commitments=(
                    CompiledCommitment(
                        source_promise_text=PROMISE_TEXT,
                        commitment_class="STANDARD_APPROVED",
                        activation_status="ACTIVE",
                        deadline=DEADLINE,
                        next_check_at=NEXT_CHECK,
                    ),
                ),
                compiled_from_evidence=True,
            ),
        ),
        expected_version=None,
    )


def _evaluate_body(action_type: str = "CHECK_REPLACEMENT_PROGRESS") -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "prepared_action": {
            "action_id": "ACTION-COMPOSITION-001",
            "action_type": action_type,
            "requires_human_approval": False,
        },
    }


# --------------------------------------------------------------------------- #
# Route inventory and documentation surface
# --------------------------------------------------------------------------- #


def test_mounted_application_exposes_exactly_the_four_business_post_routes(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    app = compose_application(settings, runtime=_runtime(settings))

    inventory = installed_route_inventory(app)
    mounted = [(entry["method"], entry["path"]) for entry in inventory]

    assert sorted(mounted) == sorted(EXPECTED_BUSINESS_ROUTES)
    assert len(inventory) == 4
    assert [path for method, path in mounted if method == "POST"] == [
        "/api/actions/evaluate",
        "/api/cases/analyze",
        "/api/events/shipment",
        "/api/resolutions/approve",
    ]
    assert "GET" not in {method for method, _ in mounted}
    assert verify_single_composition(app) == inventory


def test_documentation_and_schema_routes_are_closed_at_construction(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    app = compose_application(settings, runtime=_runtime(settings))
    client = _client(app)

    assert (app.docs_url, app.redoc_url, app.openapi_url) == (None, None, None)
    assert all(getattr(route, "path", None) != "/openapi.json" for route in app.routes)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_settings_only_allow_the_approved_browser_origins(tmp_path: Path) -> None:
    settings = Settings()
    assert settings.cors_origins == (
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://localhost:5173",
    )
    narrowed = Settings(allowed_origins="http://127.0.0.1:4173")
    assert narrowed.cors_origins == ("http://127.0.0.1:4173", "http://localhost:5173")
    assert Settings(listen_host="127.0.0.1").listen_host == "127.0.0.1"


def test_cors_preflight_allows_the_approved_origin_and_refuses_another(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    client = _client(compose_application(settings, runtime=_runtime(settings)))

    allowed = client.options(
        "/api/cases/analyze",
        headers={
            "Origin": APPROVED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == APPROVED_ORIGIN
    assert "POST" in allowed.headers["access-control-allow-methods"]

    refused = client.options(
        "/api/cases/analyze",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert refused.status_code == 400
    assert "access-control-allow-origin" not in refused.headers


def test_request_id_is_returned_logged_and_traceable(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    client = _client(compose_application(settings, runtime=_runtime(settings)))
    request_id = "6dfc4c88-a6f3-4211-bb8a-a1d4f23de939"

    response = client.post(
        "/api/cases/analyze",
        json={"case_id": CASE_ID, "unexpected": True},
        headers={REQUEST_ID_HEADER: request_id},
    )

    assert response.status_code == 422
    assert response.headers[REQUEST_ID_HEADER] == request_id
    assert response.json()["request_id"] == request_id

    lines = [
        json.loads(line)
        for line in settings.request_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [line["request_id"] for line in lines] == [request_id]
    assert lines[0]["path"] == "/api/cases/analyze"
    assert lines[0]["status"] == 422
    assert "unexpected" not in settings.request_log_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Composition behaviour through the real ledger
# --------------------------------------------------------------------------- #


def test_repeated_analyze_reuses_the_persisted_ledger_snapshot(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)
    client = _client(compose_application(settings, runtime=runtime))

    first = client.post("/api/cases/analyze", json={"case_id": CASE_ID})
    second = client.post("/api/cases/analyze", json={"case_id": CASE_ID})

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["data"]["extracted_journey"]["case_id"] == CASE_ID
    assert len(runtime.journeys) == 1

    snapshot = runtime.repository.load(CASE_ID)
    assert snapshot is not None
    assert snapshot.version == 2
    assert snapshot.accountability_state is not None
    audit_actions = [entry.action for entry in snapshot.accountability_state.audit_trail]
    assert audit_actions.count("ANALYZED") == 2


def test_four_endpoints_run_through_one_composed_application(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)
    _seed_approve_case(runtime)
    client = _client(compose_application(settings, runtime=runtime))

    analyzed = client.post("/api/cases/analyze", json={"case_id": CASE_ID})
    assert analyzed.status_code == 200
    analyzed_state = analyzed.json()["data"]["accountability_state"]
    assert analyzed_state["case_id"] == CASE_ID
    assert analyzed_state["audit_trail"][-1]["action"] == "ANALYZED"

    evaluated = client.post("/api/actions/evaluate", json=_evaluate_body())
    assert evaluated.status_code == 200
    evaluation = evaluated.json()["data"]
    assert evaluation["rule_id"] == "H1"
    assert evaluation["decision"] == "HUMAN_REVIEW"
    assert evaluation["runtime_metrics"]["rule_substitution_count"] == 0
    assert evaluation["accountability_state"]["case_id"] == CASE_ID

    approved = client.post(
        "/api/resolutions/approve",
        json={
            "case_id": APPROVE_CASE_ID,
            "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
            "approver_id": "AGENT-COMPOSITION-001",
            "idempotency_key": "composition-approve-key-001",
            "human_edits": {"executor": "WAREHOUSE"},
        },
    )
    assert approved.status_code == 200
    obligation = approved.json()["data"]["accountability_state"]["open_obligation"]
    assert obligation["milestone"] == "AWAITING_CARRIER_PICKUP"
    assert obligation["deadline"] == DEADLINE

    picked_up = client.post(
        "/api/events/shipment",
        json={
            "case_id": APPROVE_CASE_ID,
            "event_id": "EVENT-COMPOSITION-PICKUP",
            "event_type": "SHIPMENT_PICKED_UP",
            "event_time": "2030-01-01T12:20:00+00:00",
            "idempotency_key": "composition-shipment-key-001",
        },
    )
    assert picked_up.status_code == 200
    assert (
        picked_up.json()["data"]["accountability_state"]["open_obligation"]["milestone"]
        == "IN_TRANSIT"
    )

    delivered = client.post(
        "/api/events/shipment",
        json={
            "case_id": APPROVE_CASE_ID,
            "event_id": "EVENT-COMPOSITION-DELIVERED",
            "event_type": "SHIPMENT_DELIVERED",
            "event_time": "2030-01-01T13:00:00+00:00",
            "idempotency_key": "composition-shipment-key-002",
        },
    )
    assert delivered.status_code == 200
    final_state = delivered.json()["data"]["accountability_state"]
    assert final_state["open_obligation"]["milestone"] == "DELIVERED"
    assert final_state["case_status"] == "RESOLVED"

    metrics = runtime.metrics.snapshot()
    assert metrics["analyze"]["calls"] == 1
    assert metrics["evaluate"]["calls"] == 1
    assert "prompt" not in json.dumps(metrics)


def test_every_endpoint_envelopes_bad_input_before_any_service_call(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)
    client = _client(compose_application(settings, runtime=runtime))

    analyze = client.post("/api/cases/analyze", json={"case_id": 7})
    evaluate = client.post("/api/actions/evaluate", json={"case_id": CASE_ID})
    approve = client.post(
        "/api/resolutions/approve",
        json={"case_id": APPROVE_CASE_ID, "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT"},
    )
    shipment = client.post("/api/events/shipment", json={"case_id": APPROVE_CASE_ID})

    assert (analyze.status_code, evaluate.status_code) == (422, 422)
    assert analyze.json()["error"]["code"] == "SCHEMA_INVALID"
    assert evaluate.json()["error"]["code"] == "SCHEMA_INVALID"
    assert approve.status_code == 400
    assert approve.json()["error"]["code"] == "VALIDATION_ERROR"
    assert shipment.status_code == 400
    assert shipment.json()["error"]["code"] == "SCHEMA_INVALID"
    for response in (analyze, evaluate, approve, shipment):
        body = response.json()
        assert body["data"] is None
        assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert runtime.repository.load(CASE_ID) is None
    assert runtime.repository.load(APPROVE_CASE_ID) is None


def test_evaluate_refuses_an_unanalysed_case_instead_of_inventing_facts(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)
    client = _client(compose_application(settings, runtime=runtime))

    response = client.post("/api/actions/evaluate", json=_evaluate_body())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["data"] is None
    assert runtime.repository.load(CASE_ID) is None


def test_an_unregistered_model_deployment_is_a_blocker_not_a_substitute(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = build_runtime(
        settings,
        overrides=RuntimeOverrides(
            case_source=StaticCaseSource(_case_input()),
            image_resolver=StubImageResolver(_case_input()),
            clock=DemoClock(APPROVED_AT),
            provider_mode="TEST_DOUBLE",
        ),
    )
    client = _client(compose_application(settings, runtime=runtime))

    response = client.post("/api/cases/analyze", json={"case_id": CASE_ID})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "MODEL_UNAVAILABLE"
    assert body["error"]["retryable"] is True
    assert body["data"] is None
    # No fabricated state and no partial ledger write for an unavailable model.
    assert runtime.repository.load(CASE_ID) is None
    assert len(runtime.journeys) == 0
    assert any("model deployment is not registered" in notice for notice in runtime.notices)


def test_upstream_model_failure_never_becomes_a_candidate(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings, provider=UnavailableProvider())
    client = _client(compose_application(settings, runtime=runtime))

    response = client.post("/api/cases/analyze", json={"case_id": CASE_ID})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    assert runtime.repository.load(CASE_ID) is None


def test_analysis_timeout_is_bounded_by_the_composition_root(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(
        settings,
        provider=StubProvider(delay_seconds=0.5),
        analysis_timeout_seconds=0.01,
    )
    client = _client(compose_application(settings, runtime=runtime))

    response = client.post("/api/cases/analyze", json={"case_id": CASE_ID})

    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "analysis did not complete within the configured time limit",
        "retryable": True,
    }
    assert runtime.repository.load(CASE_ID) is None


def test_an_out_of_range_analysis_timeout_fails_composition(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings, analysis_timeout_seconds=25.0)

    with pytest.raises(RuntimeConfigurationError):
        compose_application(settings, runtime=runtime)


def test_evaluate_budget_exhaustion_is_a_retryable_envelope(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings, evaluate_budget_seconds=1e-9)
    client = _client(compose_application(settings, runtime=runtime))

    response = client.post("/api/actions/evaluate", json=_evaluate_body())

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["retryable"] is True
    assert body["data"] is None


def test_demo_clock_is_the_injected_server_clock(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)
    assert isinstance(runtime.clock, DemoClock)
    assert runtime.clock.now() == APPROVED_AT


# --------------------------------------------------------------------------- #
# Single composition guarantees
# --------------------------------------------------------------------------- #


def test_composition_is_idempotent_and_refuses_a_drifting_route_table(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)
    app = compose_application(settings, runtime=runtime)

    from covenia_b.runtime import _install_analyze_router, _install_evaluate_router

    before = installed_route_inventory(app)
    _install_analyze_router(app, runtime)
    _install_evaluate_router(app, runtime)
    assert installed_route_inventory(app) == before

    with pytest.raises(RuntimeConfigurationError):
        verify_single_composition(FastAPI())


def test_create_app_uses_the_composed_runtime_and_settings(
    tmp_path: Path, accepted_image_manifest: Path
) -> None:
    settings = _settings(tmp_path, accepted_image_manifest)
    runtime = _runtime(settings)

    app = create_app(settings, runtime=runtime)

    assert app.state.settings is settings
    assert app.state.runtime is runtime
    assert len(installed_route_inventory(app)) == 4
