from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI

from covenia_b.api.approve import install_approve_router
from covenia_b.api.base import install_api_seams
from covenia_b.domain.types import (
    AccountabilityState,
    CompiledCommitment,
    CompiledCommitments,
    LedgerSnapshot,
)
from covenia_b.domain.validation import validate_contract_payload
from covenia_b.ports.clock import DemoClock
from covenia_b.ports.errors import LedgerUnavailable
from covenia_b.services.approve import ApprovalService
from covenia_b.storage import SQLiteLedgerRepository

CASE_ID = "CASE-HTTP-APPROVE-001"
ANALYZED_AT = "2030-01-01T10:00:00+00:00"
DEADLINE = "2030-01-01T12:00:00+00:00"
NEXT_CHECK = "2030-01-01T12:15:00+00:00"
APPROVED_AT = datetime(2030, 1, 1, 10, 2, tzinfo=UTC)


def _state() -> AccountabilityState:
    return AccountabilityState.model_validate(
        {
            "case_id": CASE_ID,
            "case_status": "READY_FOR_BRAND",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": "VALID",
            "current_scope": {
                "order_id": "ORDER-HTTP-001",
                "fulfillment_item_id": "ITEM-HTTP-001",
                "sku_id": "SKU-HTTP-001",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "active_commitments": [
                {
                    "promise_type": "REPLACEMENT_DISPATCH",
                    "raw_text": "A server-validated replacement commitment exists.",
                    "status": "ACTIVE",
                    "deadline": DEADLINE,
                    "source_ids": ["SOURCE-HTTP-001"],
                }
            ],
            "prohibited_actions": [],
            "experience_gap_diagnosis": {
                "consumer_expression": "A reliable update is needed.",
                "traceable_service_facts": [
                    {
                        "fact_type": "EVIDENCE_SUBMITTED",
                        "statement": "Server facts include current evidence.",
                        "source_ids": ["EVIDENCE-HTTP-001"],
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
                    "at": ANALYZED_AT,
                    "actor": "ANALYZE_SERVICE",
                    "action": "ANALYZED",
                    "changed_fields": ["accountability_state"],
                    "request_id": "analyze-http-001",
                }
            ],
        }
    )


def _service(tmp_path, *, approved_at: datetime = APPROVED_AT) -> ApprovalService:
    repository = SQLiteLedgerRepository(tmp_path / "approve-http.db")
    repository.save(
        LedgerSnapshot(
            case_id=CASE_ID,
            version=0,
            event_high_watermark=None,
            accountability_state=_state(),
            compiled_commitments=CompiledCommitments(
                commitments=(
                    CompiledCommitment(
                        source_promise_text="A server-validated replacement commitment exists.",
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
    return ApprovalService(repository=repository, clock=DemoClock(approved_at))


def _app(service: ApprovalService) -> FastAPI:
    app = FastAPI()
    install_api_seams(app)
    install_approve_router(app, approval_service=service)
    return app


def _payload(*, key: str = "approve-http-key-001") -> dict[str, Any]:
    return {
        "case_id": CASE_ID,
        "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT-HTTP-001",
        "idempotency_key": key,
        "human_edits": {"executor": "WAREHOUSE"},
    }


def _post(
    app: FastAPI, payload: object, *, request_id: str | None = None
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode() if payload is not None else b""
    headers = [(b"content-type", b"application/json")]
    if request_id is not None:
        headers.append((b"x-request-id", request_id.encode()))
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/resolutions/approve",
        "raw_path": b"/api/resolutions/approve",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    messages: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: Mapping[str, Any]) -> None:
        messages.append(dict(message))

    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return int(start["status"]), json.loads(response_body)


def _assert_error_envelope(status: int, body: dict[str, Any], *, code: str) -> None:
    assert status in {400, 409, 503}
    assert body["data"] is None
    assert body["error"]["code"] == code
    validate_contract_payload("api-envelope.schema.json", body)


def test_missing_approver_and_extra_human_edits_use_frozen_validation_envelope(tmp_path):
    app = _app(_service(tmp_path))
    missing = _payload()
    del missing["approver_id"]
    status, body = _post(app, missing)
    _assert_error_envelope(status, body, code="VALIDATION_ERROR")
    assert body["error"]["message"] == "approver_id is required for approval"

    invalid = _payload(key="approve-http-key-002")
    invalid["human_edits"] = {"refund": "FULL"}
    status, body = _post(app, invalid)
    _assert_error_envelope(status, body, code="VALIDATION_ERROR")


def test_expired_candidate_maps_to_validation_error_without_client_replanning(tmp_path):
    app = _app(_service(tmp_path, approved_at=datetime(2030, 1, 1, 12, 0, tzinfo=UTC)))
    status, body = _post(app, _payload())
    _assert_error_envelope(status, body, code="VALIDATION_ERROR")
    assert (
        body["error"]["message"]
        == "candidate_type is no longer valid for the current server state"
    )


def test_replay_preserves_first_envelope_and_audit_request_id_across_new_connection(tmp_path):
    app = _app(_service(tmp_path))
    first_id = str(uuid4())
    second_id = str(uuid4())
    first_status, first = _post(app, _payload(), request_id=first_id)
    replay_status, replay = _post(app, _payload(), request_id=second_id)

    assert first_status == replay_status == 200
    assert replay == first
    assert first["request_id"] == first_id
    assert first["data"]["audit_trail"][-1]["request_id"] == first_id
    validate_contract_payload("api-envelope.schema.json", first)


def test_idempotency_conflict_and_network_failure_never_become_approval_success(tmp_path):
    app = _app(_service(tmp_path))
    status, first = _post(app, _payload())
    assert status == 200 and first["error"] is None
    conflict = _payload()
    conflict["human_edits"] = {"executor": "LOGISTICS_PROVIDER"}
    status, body = _post(app, conflict)
    _assert_error_envelope(status, body, code="IDEMPOTENCY_CONFLICT")

    class UnavailableRepository:
        def execute(self, **kwargs):
            del kwargs
            raise LedgerUnavailable("network failed")

    unavailable = ApprovalService(
        repository=UnavailableRepository(), clock=DemoClock(APPROVED_AT)
    )
    status, body = _post(_app(unavailable), _payload(key="approve-http-key-003"))
    _assert_error_envelope(status, body, code="INTERNAL_ERROR")
    assert body["error"]["retryable"] is True
