from __future__ import annotations

import asyncio

from fastapi import Request

from covenia_b.api.base import ApiError, api_error_handler
from covenia_b.api.evaluate import create_evaluate_router
from covenia_b.domain.types import (
    AccountabilityState,
    CaseInput,
    CompiledCommitments,
    ExtractedJourney,
    LedgerSnapshot,
)
from covenia_b.services.evaluate import EvaluateService


class _Cases:
    def __init__(self, case):
        self.case = case

    def get_case(self, case_id):
        if case_id != self.case.case_id:
            raise ValueError("missing")
        return self.case


class _Journeys:
    def __init__(self, journey):
        self.journey = journey

    def get_journey(self, case_id):
        if case_id != self.journey.case_id:
            raise ValueError("missing")
        return self.journey


class _Ledger:
    def __init__(self, snapshot):
        self.snapshot, self.loads = snapshot, []

    def load(self, case_id):
        self.loads.append(case_id)
        return self.snapshot

    def save(self, snapshot, *, expected_version):
        raise AssertionError("evaluate must not persist")


def test_http_endpoint_uses_authoritative_facts_and_ignores_compatibility_fields():
    endpoint, ledger = _endpoint()
    body = _request("CHECK_REPLACEMENT_PROGRESS") | {
        "accountability_state": {"forged": True},
        "evidence_status": "MISMATCHED",
        "active_commitments": ["forged"],
        "prohibited_actions": ["CLOSE_BEFORE_RESOLUTION"],
        "current_scope": {"forged": True},
        "challenge_overrides": {"not": "inspected"},
    }
    response = asyncio.run(endpoint(_request_object(), body))
    assert response.status_code == 200
    payload = _body(response)
    assert payload["data"]["rule_id"] == "E0_NO_RULE_MATCHED"
    assert payload["data"]["decision"] == "ALLOW"
    assert payload["data"]["fact_trace"]["evidence_status"] == "VALID"
    assert (
        payload["data"]["resolution_path"]["task_prefill"]["task_type"]
        == "CHECK_REPLACEMENT_STATUS"
    )
    assert ledger.loads == ["case-evaluate-001"]


def test_challenge_is_opt_in_and_does_not_write_the_ledger():
    endpoint, ledger = _endpoint()
    override = {"image_observation_overrides": [{"evidence_id": "image-001", "readability": "LOW"}]}
    disabled = asyncio.run(
        endpoint(_request_object(), _request("ASK_EVIDENCE") | {"challenge_overrides": override})
    )
    assert _body(disabled)["data"]["rule_id"] == "E1"
    enabled = asyncio.run(
        endpoint(
            _request_object(),
            _request("ASK_EVIDENCE") | {"challenge_mode": True, "challenge_overrides": override},
        )
    )
    payload = _body(enabled)["data"]
    assert payload["challenge_mode"] is True
    assert payload["rule_id"] == "H1"
    assert payload["accountability_state"]["evidence_status"] == "NEED_HUMAN_REVIEW"
    assert ledger.snapshot.accountability_state.evidence_status == "VALID"


def test_p0_and_unanalysed_are_enveloped_http_errors():
    endpoint, _ = _endpoint()
    try:
        asyncio.run(endpoint(_request_object(), _request("CLOSE_CASE")))
    except ApiError as error:
        response = asyncio.run(api_error_handler(_request_object(), error))
        assert response.status_code == 400
        assert _body(response)["error"]["code"] == "P0_PROHIBITED_ACTION"
    else:
        raise AssertionError("P0 must be an HTTP error")
    endpoint, _ = _endpoint(snapshot=None)
    try:
        asyncio.run(endpoint(_request_object(), _request("CHECK_REPLACEMENT_PROGRESS")))
    except ApiError as error:
        response = asyncio.run(api_error_handler(_request_object(), error))
        assert response.status_code == 422
        assert _body(response)["error"]["code"] == "VALIDATION_ERROR"
    else:
        raise AssertionError("unanalysed case must be rejected")


def _endpoint(*, snapshot=Ellipsis):
    case = _case()
    journey = _journey(case)
    state = AccountabilityState.model_validate(
        {
            "case_id": case.case_id,
            "case_status": "READY_FOR_BRAND",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": "VALID",
            "current_scope": {
                "order_id": "order-001",
                "fulfillment_item_id": "item-001",
                "sku_id": "sku-001",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "active_commitments": [],
            "prohibited_actions": ["CLOSE_BEFORE_RESOLUTION"],
            "experience_gap_diagnosis": {
                "consumer_expression": "need progress",
                "traceable_service_facts": [
                    {
                        "fact_type": "EVIDENCE_SUBMITTED",
                        "statement": "image",
                        "source_ids": ["image-001"],
                    }
                ],
                "deterioration_cause": "waiting",
                "latent_need": "update",
                "responsibility_judgment": {
                    "consumer_input_complete": True,
                    "accountable_side": "BRAND",
                },
                "action_impacts": ["CHECK_EXISTING_FULFILLMENT"],
                "reply_strategy": "check",
            },
            "open_obligation": None,
            "service_progress_receipt": None,
            "experience_risk": "LOW",
            "audit_trail": [],
        }
    )
    default = LedgerSnapshot(
        case_id=case.case_id,
        version=1,
        event_high_watermark=None,
        accountability_state=state,
        compiled_commitments=CompiledCommitments(commitments=(), compiled_from_evidence=True),
    )
    ledger = _Ledger(default if snapshot is Ellipsis else snapshot)
    service = EvaluateService(
        case_source=_Cases(case),
        journey_source=_Journeys(journey),
        ledger_repository=ledger,
        request_id_factory=lambda: "evaluate-test-001",
    )
    return create_evaluate_router(service).routes[0].endpoint, ledger


def _request_object():
    request = Request({"type": "http", "method": "POST", "path": "/evaluate", "headers": []})
    request.state.request_id = "http-request-001"
    return request


def _body(response):
    import json

    return json.loads(response.body)


def _request(action_type):
    action = {
        "action_id": "action-001",
        "action_type": action_type,
        "requires_human_approval": False,
    }
    if action_type == "ASK_EVIDENCE":
        action["requested_scope"] = {
            "order_id": "order-001",
            "fulfillment_item_id": "item-001",
            "sku_id": "sku-001",
            "issue_type": "PACKAGE_DAMAGE",
        }
    return {"case_id": "case-evaluate-001", "prepared_action": action}


def _case():
    return CaseInput.model_validate(
        {
            "case_id": "case-evaluate-001",
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-001",
                "augmentation_notes": [],
            },
            "evaluation_time": "2026-10-05T10:00:00Z",
            "conversation": [
                {
                    "message_id": "message-001",
                    "timestamp": "2026-10-05T09:00:00Z",
                    "speaker": "CONSUMER",
                    "text": "package damaged",
                    "source_kind": "COMPETITION_MOCK",
                }
            ],
            "order": {
                "order_id": "order-001",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "item-001",
                        "sku_id": "sku-001",
                        "product_name": "product",
                        "batch_code": None,
                        "item_role": "PRIMARY",
                    }
                ],
                "original_logistics_number": "logistics-001",
            },
            "service_tickets": [],
            "evidence_images": [
                {
                    "evidence_id": "image-001",
                    "file_name": "image.png",
                    "submitted_at": "2026-10-05T09:01:00Z",
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": "message-001",
                    "competition_reference_path": None,
                }
            ],
            "current_issue": {
                "fulfillment_item_id": "item-001",
                "sku_id": "sku-001",
                "issue_type": "PACKAGE_DAMAGE",
                "affected_component": "PUMP",
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )


def _journey(case):
    return ExtractedJourney.model_validate(
        {
            "case_id": case.case_id,
            "completed_actions": {
                "issue_explained": True,
                "order_verified": True,
                "evidence_submitted": True,
            },
            "promise_events": [],
            "image_observations": [
                {
                    "evidence_id": "image-001",
                    "readability": "HIGH",
                    "product_identifiable": True,
                    "sku_match": "MATCH",
                    "product_role": "PRIMARY",
                    "issue_visible": True,
                    "affected_component": "PUMP",
                    "view_type": "ISSUE_DETAIL",
                    "coverage": ["PRODUCT_IDENTITY", "AFFECTED_COMPONENT", "DAMAGE_DETAIL"],
                    "integrity_concern": False,
                    "hygiene_risk_signal": "LOW",
                    "confidence": 1.0,
                }
            ],
            "extracted_scope": {
                "order_id": "order-001",
                "fulfillment_item_id": "item-001",
                "sku_id": "sku-001",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "journey_understanding": {
                "consumer_intent": "help",
                "experience_expression": "damage",
                "service_cause": "damage",
                "latent_need": "replacement",
                "cooperation_willingness": "STABLE",
                "action_impact": "review",
                "source_ids": ["message-001"],
            },
            "source_trace": [
                {"field": "image_observations[0]", "source_type": "IMAGE", "source_id": "image-001"}
            ],
            "model_metadata": {
                "model_id": "qwen3-vl-plus",
                "model_revision": "test",
                "prompt_version": "test",
                "run_id": "run-001",
                "cached_result": False,
            },
        }
    )
