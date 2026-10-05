"""ASGI transport tests for the unregistered analysis router."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from covenia_b.api.analyze import create_analyze_router
from covenia_b.api.base import REQUEST_ID_HEADER, install_api_seams
from covenia_b.domain.types import AnalyzeCaseRequest
from covenia_b.services.analyze import AnalysisModelOutputError, AnalysisModelUnavailable


class _ContractResponse:
    def to_contract(self) -> dict[str, Any]:
        # A transport double: response-contract validation remains service-owned.
        return {"transport_double": True}


class _ServiceDouble:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.requests: list[AnalyzeCaseRequest] = []
        self.request_ids: list[str | None] = []

    def analyze(
        self, request: AnalyzeCaseRequest, *, request_id: str | None = None
    ) -> Awaitable[_ContractResponse]:
        self.requests.append(request)
        self.request_ids.append(request_id)

        async def invoke() -> _ContractResponse:
            if isinstance(self.outcome, Exception):
                raise self.outcome
            if self.outcome == "wait":
                await asyncio.sleep(0.02)
            return _ContractResponse()

        return invoke()


def _client(service: _ServiceDouble, *, timeout: float = 20.0) -> TestClient:
    app = FastAPI()
    install_api_seams(app)
    app.include_router(create_analyze_router(service, timeout_seconds=timeout))
    return TestClient(app, raise_server_exceptions=False)


def test_case_id_only_is_forwarded_with_success_envelope_and_request_id() -> None:
    service = _ServiceDouble(outcome="ok")

    response = _client(service).post(
        "/api/cases/analyze",
        json={"case_id": "case-001"},
        headers={REQUEST_ID_HEADER: "6dfc4c88-a6f3-4211-bb8a-a1d4f23de939"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": {"transport_double": True},
        "error": None,
        "request_id": "6dfc4c88-a6f3-4211-bb8a-a1d4f23de939",
    }
    assert service.requests[0].case_input is None
    assert response.headers[REQUEST_ID_HEADER] == response.json()["request_id"]


def test_schema_negative_cases_are_enveloped_before_service_execution() -> None:
    service = _ServiceDouble(outcome="ok")
    client = _client(service)

    for payload in ({}, {"case_id": "case-001", "unexpected": True}, {"case_id": 7}):
        response = client.post("/api/cases/analyze", json=payload)
        assert response.status_code == 422
        assert response.json()["data"] is None
        assert response.json()["error"]["code"] == "SCHEMA_INVALID"

    assert service.requests == []


def test_case_input_requires_explicit_challenge_mode() -> None:
    service = _ServiceDouble(outcome="ok")
    response = _client(service).post(
        "/api/cases/analyze", json={"case_id": "case-001", "case_input": {}}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEMA_INVALID"
    assert service.requests == []


def test_repeated_analysis_is_delegated_without_transport_state_override() -> None:
    service = _ServiceDouble(outcome="ok")
    client = _client(service)

    first = client.post("/api/cases/analyze", json={"case_id": "case-001"})
    second = client.post("/api/cases/analyze", json={"case_id": "case-001"})

    assert (first.status_code, second.status_code) == (200, 200)
    assert [request.case_id for request in service.requests] == ["case-001", "case-001"]
    assert all(request.case_input is None for request in service.requests)


def test_model_failures_have_safe_distinct_transport_results() -> None:
    unavailable = _client(
        _ServiceDouble(
            AnalysisModelUnavailable(
                "model provider is unavailable",
                request_id="model-request-001",
                runtime_metrics=_metrics(),
                retryable=True,
            )
        )
    ).post("/api/cases/analyze", json={"case_id": "case-001"})
    invalid = _client(
        _ServiceDouble(
            AnalysisModelOutputError(
                "model output could not be accepted",
                request_id="model-request-002",
                runtime_metrics=_metrics(),
                retryable=False,
            )
        )
    ).post("/api/cases/analyze", json={"case_id": "case-001"})

    assert (unavailable.status_code, unavailable.json()["error"]["code"]) == (
        503,
        "MODEL_UNAVAILABLE",
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (502, "MODEL_OUTPUT_INVALID")
    assert "secret" not in unavailable.text.lower()


def test_timeout_is_bounded_and_returns_retryable_envelope() -> None:
    response = _client(_ServiceDouble(outcome="wait"), timeout=0.001).post(
        "/api/cases/analyze", json={"case_id": "case-001"}
    )

    assert response.status_code == 504
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "analysis did not complete within the configured time limit",
        "retryable": True,
    }


def _metrics():
    from covenia_b.domain.types import RuntimeMetrics

    return RuntimeMetrics(
        input_tokens=0,
        output_tokens=0,
        inference_latency_ms=0,
        rule_substitution_count=0,
    )
