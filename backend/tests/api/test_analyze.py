"""ASGI transport tests for the unregistered analysis router."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from covenia_b.api.analyze import RESPONSE_SCHEMA_NAME, create_analyze_router
from covenia_b.api.base import REQUEST_ID_HEADER, install_api_seams
from covenia_b.domain.types import AnalyzeCaseRequest
from covenia_b.domain.validation import ContractValidationError, validate_contract_payload
from covenia_b.services.analyze import AnalysisModelOutputError, AnalysisModelUnavailable

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ANALYZE_VECTOR_PATH = _REPO_ROOT / "tests" / "contract-vectors" / "analyze.json"
_LOCKED_SUCCESS_VECTOR_ID = "analyze-live-success"

# Deliberately outside analyze-case-response.schema.json: the regression payload
# for an invalid service projection at the HTTP boundary.
INVALID_RESPONSE_PAYLOAD: dict[str, Any] = {"transport_double": True}


def _locked_success_payload() -> dict[str, Any]:
    """Return the locked BATCH-03 success data for ``POST /api/cases/analyze``."""

    vectors = json.loads(_ANALYZE_VECTOR_PATH.read_text(encoding="utf-8"))["vectors"]
    vector = next(item for item in vectors if item["id"] == _LOCKED_SUCCESS_VECTOR_ID)
    return vector["response"]["data"]


class _ContractResponse:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload

    def to_contract(self) -> dict[str, Any]:
        # A transport double: the HTTP boundary owns response-contract validation.
        return deepcopy(dict(self._payload))


class _ServiceDouble:
    def __init__(self, outcome: object, *, payload: Mapping[str, Any] | None = None) -> None:
        self.outcome = outcome
        self.payload = _locked_success_payload() if payload is None else payload
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
            return _ContractResponse(self.payload)

        return invoke()


def _client(service: _ServiceDouble, *, timeout: float = 20.0) -> TestClient:
    app = FastAPI()
    install_api_seams(app)
    app.include_router(create_analyze_router(service, timeout_seconds=timeout))
    return TestClient(app, raise_server_exceptions=False)


def test_case_id_only_is_forwarded_with_success_envelope_and_request_id() -> None:
    service = _ServiceDouble(outcome="ok")
    payload = _locked_success_payload()

    response = _client(service).post(
        "/api/cases/analyze",
        json={"case_id": "case-001"},
        headers={REQUEST_ID_HEADER: "6dfc4c88-a6f3-4211-bb8a-a1d4f23de939"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "data": payload,
        "error": None,
        "request_id": "6dfc4c88-a6f3-4211-bb8a-a1d4f23de939",
    }
    assert service.requests[0].case_input is None
    assert response.headers[REQUEST_ID_HEADER] == response.json()["request_id"]


def test_schema_invalid_service_response_becomes_safe_internal_error() -> None:
    """Regression: a service projection outside the frozen contract must not reach the client."""

    # Control: the boundary validator accepts the locked success payload and
    # rejects the invalid projection, so this test cannot pass vacuously.
    validate_contract_payload(RESPONSE_SCHEMA_NAME, _locked_success_payload())
    with pytest.raises(ContractValidationError):
        validate_contract_payload(RESPONSE_SCHEMA_NAME, INVALID_RESPONSE_PAYLOAD)

    service = _ServiceDouble(outcome="ok", payload=INVALID_RESPONSE_PAYLOAD)

    response = _client(service).post("/api/cases/analyze", json={"case_id": "case-001"})

    body = response.json()
    assert response.status_code == 500
    assert body["data"] is None
    assert body["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "analysis response could not be safely serialized",
        "retryable": False,
    }
    assert response.headers[REQUEST_ID_HEADER] == body["request_id"]
    assert service.requests[0].case_id == "case-001"
    assert "transport_double" not in response.text


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
