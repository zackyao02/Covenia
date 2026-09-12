"""Round-trip checks for BATCH-04 public types and locked JSON Schema."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from covenia_b.domain.types import (
    AccountabilityState,
    AnalyzeCaseRequest,
    AnalyzeCaseResponse,
    ApiEnvelope,
    ApproveResolutionRequest,
    ApproveResolutionResponse,
    CaseInput,
    DecisionResult,
    EvaluateActionRequest,
    ExtractedJourney,
    PreparedAction,
    RuntimeMetrics,
    ShipmentEventRequest,
    ShipmentEventResponse,
)
from covenia_b.domain.validation import (
    ContractValidationError,
    load_contract_schemas,
    validation_messages,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VECTOR_DIRECTORY = REPO_ROOT / "tests" / "contract-vectors"


def vector_file(name: str) -> dict[str, Any]:
    return json.loads((VECTOR_DIRECTORY / name).read_text(encoding="utf-8"))


def minimal_case_input() -> dict[str, Any]:
    return {
        "case_id": "CASE-9007199254740993",
        "data_provenance": {
            "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
            "source_session_id": "9007199254740993",
            "augmentation_notes": [],
        },
        "evaluation_time": "2030-01-01T10:00:00+00:00",
        "conversation": [
            {
                "message_id": "9007199254740993",
                "timestamp": "2030-01-01T09:00:00+00:00",
                "speaker": "CONSUMER",
                "text": "Please check the package.",
                "source_kind": "COMPETITION_MOCK",
            }
        ],
        "order": {
            "order_id": "9007199254740993",
            "channel": "TIANCHI_MOCK_QIANNIU",
            "items": [
                {
                    "fulfillment_item_id": "9007199254740993",
                    "sku_id": "9007199254740993",
                    "product_name": "Product",
                    "item_role": "PRIMARY",
                }
            ],
            "original_logistics_number": "9007199254740993",
        },
        "service_tickets": [],
        "evidence_images": [
            {
                "evidence_id": "9007199254740993",
                "file_name": "evidence.png",
                "submitted_at": "2030-01-01T09:01:00+00:00",
                "declared_view_type": "PRODUCT_OVERVIEW",
                "source_kind": "TEAM_SYNTHETIC_RECREATION",
                "source_message_id": "9007199254740993",
            }
        ],
        "current_issue": {
            "fulfillment_item_id": "9007199254740993",
            "sku_id": "9007199254740993",
            "issue_type": "PACKAGE_DAMAGE",
        },
        "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
    }


def test_every_locked_schema_has_a_public_validation_entry_point() -> None:
    public_models = {
        ApiEnvelope,
        RuntimeMetrics,
        CaseInput,
        AccountabilityState,
        ExtractedJourney,
        PreparedAction,
        DecisionResult,
        EvaluateActionRequest,
        AnalyzeCaseRequest,
        AnalyzeCaseResponse,
        ApproveResolutionRequest,
        ApproveResolutionResponse,
        ShipmentEventRequest,
        ShipmentEventResponse,
    }

    assert {model.SCHEMA_NAME for model in public_models} == set(load_contract_schemas())


def test_case_input_round_trips_through_its_schema_without_id_precision_loss() -> None:
    payload = minimal_case_input()

    parsed = CaseInput.from_contract(payload)
    serialized = json.loads(json.dumps(parsed.to_contract()))

    assert serialized == payload
    assert isinstance(serialized["order"]["order_id"], str)
    assert serialized["order"]["order_id"] == "9007199254740993"


def test_long_numeric_identifiers_reject_numbers_and_preserve_strings() -> None:
    payload = {
        "case_id": "CASE-9007199254740993",
        "event_id": "9007199254740993",
        "event_type": "SHIPMENT_PICKED_UP",
        "event_time": "2030-01-01T10:00:00+00:00",
        "idempotency_key": "shipment-key-9007199254740993",
    }

    parsed = ShipmentEventRequest.from_contract(payload)
    assert parsed.to_contract()["event_id"] == "9007199254740993"

    non_string_id = deepcopy(payload)
    non_string_id["event_id"] = 9007199254740993
    with pytest.raises(ContractValidationError):
        ShipmentEventRequest.from_contract(non_string_id)


@pytest.mark.parametrize(
    "timestamp",
    (
        "2030-01-01T11:00:00Z",
        "2030-01-01t11:00:00.123456789z",
        "2032-02-29T11:00:00-00:00",
        "1990-12-31T23:59:60Z",
    ),
)
def test_schema_legal_rfc3339_timestamps_round_trip(timestamp: str) -> None:
    payload = {
        "case_id": "CASE-TIME-001",
        "event_id": "EVENT-TIME-001",
        "event_type": "SHIPMENT_PICKED_UP",
        "event_time": timestamp,
        "idempotency_key": "shipment-time-key",
    }

    assert ShipmentEventRequest.from_contract(payload).to_contract()["event_time"] == timestamp


@pytest.mark.parametrize(
    "timestamp",
    (
        "2030-01-01T11:00:00",
        "2030-01-01 11:00:00+00:00",
        "2030-01-01T11:00+00:00",
        "2030-W01-1T11:00:00+00:00",
        "2030-01-01T11:00:00,5+00:00",
        "2030-01-01T11:00:00+00:00:30",
        "2030-01-01T11:00:00+05:30.5",
    ),
)
def test_schema_illegal_rfc3339_timestamps_are_rejected(timestamp: str) -> None:
    payload = {
        "case_id": "CASE-TIME-002",
        "event_id": "EVENT-TIME-002",
        "event_type": "SHIPMENT_PICKED_UP",
        "event_time": timestamp,
        "idempotency_key": "shipment-time-key",
    }

    assert validation_messages("shipment-event-request.schema.json", payload)
    with pytest.raises(ContractValidationError):
        ShipmentEventRequest.from_contract(payload)


@pytest.mark.parametrize("file_name", ("analyze.json", "evaluate.json", "approve.json", "shipment.json"))
def test_contract_vectors_parse_and_serialize_in_both_directions(file_name: str) -> None:
    vectors = vector_file(file_name)["vectors"]
    request_models = {
        "analyze.json": AnalyzeCaseRequest,
        "evaluate.json": EvaluateActionRequest,
        "approve.json": ApproveResolutionRequest,
        "shipment.json": ShipmentEventRequest,
    }
    response_models = {
        "analyze.json": AnalyzeCaseResponse,
        "evaluate.json": DecisionResult,
        "approve.json": ApproveResolutionResponse,
        "shipment.json": ShipmentEventResponse,
    }
    request_schema = vector_file(file_name)["request_schema"]

    for vector in vectors:
        request = vector["request"]
        if vector["expected"]["request_schema_valid"]:
            parsed_request = request_models[file_name].from_contract(request)
            assert parsed_request.to_contract() == request
        else:
            assert validation_messages(request_schema, request)
            with pytest.raises((ContractValidationError, ValidationError)):
                request_models[file_name].from_contract(request)

        response = vector["response"]
        if response["data"] is None:
            envelope = ApiEnvelope[dict[str, Any]].from_contract(response)
            assert envelope.to_contract() == response
            continue

        parsed_response = response_models[file_name].from_contract(response["data"])
        assert parsed_response.to_contract() == response["data"]
        envelope = ApiEnvelope[response_models[file_name]].from_contract(response)
        assert envelope.to_contract() == response


def test_analyze_case_input_requires_explicit_challenge_mode() -> None:
    payload = {"case_id": "CASE-INPUT-001", "case_input": minimal_case_input()}

    with pytest.raises(ContractValidationError):
        AnalyzeCaseRequest.from_contract(payload)

    enabled_payload = {**payload, "challenge_mode": True}
    assert AnalyzeCaseRequest.from_contract(enabled_payload).to_contract() == enabled_payload


def test_enabled_challenge_overrides_are_strict_but_disabled_payload_is_compatible() -> None:
    baseline = {
        "case_id": "CASE-CHALLENGE-001",
        "prepared_action": {
            "action_id": "ACTION-CHALLENGE-001",
            "action_type": "CHECK_REPLACEMENT_PROGRESS",
            "requires_human_approval": False,
        },
        "challenge_overrides": {"unexpected": ["kept", "ignored"]},
    }
    assert EvaluateActionRequest.from_contract(baseline).to_contract() == baseline

    enabled = {**baseline, "challenge_mode": True}
    with pytest.raises(ContractValidationError):
        EvaluateActionRequest.from_contract(enabled)
