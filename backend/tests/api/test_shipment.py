"""HTTP boundary tests for the atomic shipment event endpoint.

Every request runs through the real ASGI application, the real BATCH-18 SQLite
transaction, and the real BATCH-26 service.  No HTTP client, model, carrier,
warehouse, or notification side effect is involved.

Set ``COVENIA_BATCH26_SEQUENCE_ARTIFACT`` to a file path to also record the
observed sequences and replay vectors as JSON evidence.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI

from covenia_b.api.base import install_api_seams
from covenia_b.api.shipment import install_shipment_router
from covenia_b.domain.types import (
    AccountabilityState,
    CompiledCommitment,
    CompiledCommitments,
    LedgerSnapshot,
)
from covenia_b.domain.validation import validate_contract_payload
from covenia_b.ports.errors import LedgerConflict, LedgerUnavailable
from covenia_b.services.shipment import ShipmentEventService
from covenia_b.storage import SQLiteLedgerRepository

_ROUTE_PATH = "/api/events/shipment"
_ARTIFACT_ENV = "COVENIA_BATCH26_SEQUENCE_ARTIFACT"

DEADLINE = "2030-01-01T10:00:00+00:00"
INITIAL_NEXT_CHECK = "2030-01-01T10:05:00+00:00"
PROMISE_TEXT = "A replacement will be dispatched."

SEQUENCE_A_CASE = "CASE-SHIPMENT-HTTP-SEQUENCE-A"
SEQUENCE_B_CASE = "CASE-SHIPMENT-HTTP-SEQUENCE-B"


def _record(section: str, payload: Any) -> None:
    """Append observed evidence to the optional artifact without affecting tests."""

    target = os.environ.get(_ARTIFACT_ENV)
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "artifact_type": "SHIPMENT_HTTP_SEQUENCE_EVIDENCE",
        "batch_id": "BATCH-26",
        "route": f"POST {_ROUTE_PATH}",
        "transport": "in-process ASGI application; no network listener or external call",
        "records": {},
    }
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and loaded.get("artifact_type") == document["artifact_type"]:
            document = loaded
            document.setdefault("records", {})
    document["records"][section] = payload
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _state(case_id: str) -> AccountabilityState:
    return AccountabilityState.model_validate(
        {
            "case_id": case_id,
            "case_status": "IN_FULFILLMENT",
            "consumer_input_required": False,
            "accountable_side": "BRAND",
            "evidence_status": "VALID",
            "current_scope": {
                "order_id": f"ORDER-{case_id}",
                "fulfillment_item_id": f"ITEM-{case_id}",
                "sku_id": f"SKU-{case_id}",
                "issue_type": "PACKAGE_DAMAGE",
            },
            "active_commitments": [
                {
                    "promise_type": "REPLACEMENT_FULFILLMENT",
                    "raw_text": PROMISE_TEXT,
                    "status": "ACTIVE",
                    "deadline": DEADLINE,
                    "source_ids": [f"SOURCE-{case_id}"],
                }
            ],
            "prohibited_actions": [
                "SHIFT_FOLLOW_UP_TO_CONSUMER",
                "CLOSE_BEFORE_RESOLUTION",
            ],
            "experience_gap_diagnosis": {
                "consumer_expression": "A promised progress update is pending.",
                "traceable_service_facts": [
                    {
                        "fact_type": "PROMISE_ACTIVE",
                        "statement": "The replacement handoff is pending.",
                        "source_ids": [f"SOURCE-{case_id}"],
                    },
                    {
                        "fact_type": "TICKET_CREATED",
                        "statement": "A warehouse ticket already tracks the handoff.",
                        "source_ids": [f"TICKET-{case_id}"],
                    },
                ],
                "deterioration_cause": "Replacement fulfillment is pending.",
                "latent_need": "A traceable service update.",
                "responsibility_judgment": {
                    "consumer_input_complete": True,
                    "accountable_side": "BRAND",
                },
                "action_impacts": ["START_PROACTIVE_UPDATE"],
                "reply_strategy": "Provide a pending approval notification draft.",
            },
            "open_obligation": {
                "obligation_type": "REPLACEMENT_FULFILLMENT",
                "status": "ON_TRACK",
                "accountable_side": "BRAND",
                "executor": "WAREHOUSE",
                "deadline": DEADLINE,
                "next_check_at": INITIAL_NEXT_CHECK,
                "milestone": "AWAITING_CARRIER_PICKUP",
                "resolution_condition": "REPLACEMENT_DELIVERED",
            },
            "service_progress_receipt": {
                "receipt_id": f"RECEIPT-{case_id}",
                "status": "ACTIVE",
                "received_evidence": ["Service facts"],
                "brand_action": "The brand is monitoring the replacement handoff.",
                "latest_update_at": "2030-01-01T09:00:00+00:00",
                "next_update_by": INITIAL_NEXT_CHECK,
                "consumer_action_required": False,
                "recovery_if_missed": "The brand will provide another update.",
            },
            "experience_risk": "MEDIUM",
            "audit_trail": [
                {
                    "at": "2030-01-01T09:00:00+00:00",
                    "actor": "APPROVAL_SERVICE",
                    "action": "RESOLUTION_APPROVED",
                    "changed_fields": ["open_obligation"],
                    "request_id": f"approve-{case_id}",
                }
            ],
        }
    )


def _seed(
    tmp_path: Path,
    case_id: str,
) -> tuple[SQLiteLedgerRepository, Path]:
    db_path = tmp_path / f"{case_id}.db"
    repository = SQLiteLedgerRepository(db_path)
    repository.save(
        LedgerSnapshot(
            case_id=case_id,
            version=0,
            event_high_watermark=None,
            accountability_state=_state(case_id),
            compiled_commitments=CompiledCommitments(
                commitments=(
                    CompiledCommitment(
                        source_promise_text=PROMISE_TEXT,
                        commitment_class="STANDARD_APPROVED",
                        activation_status="ACTIVE",
                        deadline=DEADLINE,
                        next_check_at=INITIAL_NEXT_CHECK,
                    ),
                ),
                compiled_from_evidence=True,
            ),
        ),
        expected_version=None,
    )
    return repository, db_path


def _app(service: ShipmentEventService) -> FastAPI:
    app = FastAPI()
    install_api_seams(app)
    install_shipment_router(app, shipment_service=service)
    return app


def _app_with_case(
    tmp_path: Path,
    case_id: str,
) -> tuple[FastAPI, SQLiteLedgerRepository, Path]:
    repository, db_path = _seed(tmp_path, case_id)
    service = ShipmentEventService(repository=repository)
    return _app(service), repository, db_path


def _payload(
    *,
    case_id: str,
    event_id: str,
    event_type: str,
    event_time: str,
    key: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "event_id": event_id,
        "event_type": event_type,
        "event_time": event_time,
        "idempotency_key": key,
    }


def _post(
    app: FastAPI,
    payload: object,
    *,
    request_id: str | None = None,
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
        "path": _ROUTE_PATH,
        "raw_path": _ROUTE_PATH.encode(),
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
    assert status in {400, 409, 500, 503}
    assert body["data"] is None
    assert body["error"]["code"] == code
    validate_contract_payload("api-envelope.schema.json", body)


def _db_state(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("events", "idempotent_requests", "audit_entries", "case_versions")
        }
        row = connection.execute(
            "SELECT version, event_high_watermark FROM cases"
        ).fetchone()
    finally:
        connection.close()
    return {
        "row_counts": counts,
        "ledger_version": None if row is None else row[0],
        "event_high_watermark": None if row is None else row[1],
    }


def _step(
    app: FastAPI,
    *,
    case_id: str,
    event_id: str,
    event_type: str,
    event_time: str,
    key: str,
    request_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    status, body = _post(
        app,
        _payload(
            case_id=case_id,
            event_id=event_id,
            event_type=event_type,
            event_time=event_time,
            key=key,
        ),
        request_id=request_id,
    )
    assert status == 200, body
    assert body["error"] is None
    validate_contract_payload("api-envelope.schema.json", body)
    state = body["data"]["accountability_state"]
    observation = {
        "event_id": event_id,
        "event_type": event_type,
        "event_time": event_time,
        "http_status": status,
        "request_id": body["request_id"],
        "case_status": state["case_status"],
        "milestone": state["open_obligation"]["milestone"],
        "obligation_status": state["open_obligation"]["status"],
        "obligation_executor": state["open_obligation"]["executor"],
        "receipt_status": state["service_progress_receipt"]["status"],
        "next_update_by": state["service_progress_receipt"]["next_update_by"],
        "follow_up_candidate": body["data"]["follow_up_candidate"],
        "supervisor_escalation_candidate": body["data"]["supervisor_escalation_candidate"],
        "notification_commits_next_update_at": (
            body["data"]["proactive_notification_draft"]["commits_next_update_at"]
            if body["data"]["proactive_notification_draft"] is not None
            else None
        ),
        "audit_trail_length": len(state["audit_trail"]),
        "audit_actions": [entry["action"] for entry in state["audit_trail"]],
    }
    return observation, body


# --- acceptance criterion 1: two independent legal sequences -----------------


def test_approved_not_picked_up_then_later_pickup_then_delivered(tmp_path: Path) -> None:
    case_id = SEQUENCE_A_CASE
    app, repository, db_path = _app_with_case(tmp_path, case_id)

    not_picked, _ = _step(
        app,
        case_id=case_id,
        event_id="EVENT-SEQ-A-NOT-PICKED-UP",
        event_type="SHIPMENT_NOT_PICKED_UP",
        event_time="2030-01-01T09:30:00+00:00",
        key="seq-a-key-0001",
    )
    assert not_picked["case_status"] == "IN_FULFILLMENT"
    assert not_picked["milestone"] == "AWAITING_CARRIER_PICKUP"
    assert not_picked["obligation_status"] == "ON_TRACK"
    assert not_picked["receipt_status"] == "ACTIVE"
    assert not_picked["next_update_by"] == INITIAL_NEXT_CHECK
    assert not_picked["follow_up_candidate"] is None
    assert not_picked["supervisor_escalation_candidate"] is None
    assert not_picked["audit_trail_length"] == 2
    assert not_picked["audit_actions"] == [
        "RESOLUTION_APPROVED",
        "SHIPMENT_NOT_PICKED_UP",
    ]

    later_pickup, _ = _step(
        app,
        case_id=case_id,
        event_id="EVENT-SEQ-A-LATER-PICKUP",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T10:06:00+00:00",
        key="seq-a-key-0002",
    )
    assert later_pickup["case_status"] == "IN_FULFILLMENT"
    assert later_pickup["milestone"] == "IN_TRANSIT"
    assert later_pickup["obligation_status"] == "ON_TRACK"
    assert later_pickup["obligation_executor"] == "LOGISTICS_PROVIDER"
    assert later_pickup["next_update_by"] == "2030-01-01T10:36:00+00:00"
    assert later_pickup["notification_commits_next_update_at"] == "2030-01-01T10:36:00+00:00"
    assert later_pickup["audit_trail_length"] == 3

    delivered, _ = _step(
        app,
        case_id=case_id,
        event_id="EVENT-SEQ-A-DELIVERED",
        event_type="SHIPMENT_DELIVERED",
        event_time="2030-01-01T11:00:00+00:00",
        key="seq-a-key-0003",
    )
    assert delivered["case_status"] == "RESOLVED"
    assert delivered["milestone"] == "DELIVERED"
    assert delivered["obligation_status"] == "COMPLETED"
    assert delivered["receipt_status"] == "COMPLETED"
    assert delivered["next_update_by"] is None
    assert delivered["notification_commits_next_update_at"] is None
    assert delivered["follow_up_candidate"] is None
    assert delivered["supervisor_escalation_candidate"] is None
    assert delivered["audit_trail_length"] == 4
    assert delivered["audit_actions"] == [
        "RESOLUTION_APPROVED",
        "SHIPMENT_NOT_PICKED_UP",
        "SHIPMENT_PICKED_UP",
        "SHIPMENT_DELIVERED",
    ]

    persisted = repository.load(case_id)
    assert persisted is not None
    # The seeded approval snapshot is version 1; each accepted event adds one.
    assert persisted.version == 4
    assert persisted.accountability_state is not None
    contract = persisted.accountability_state.to_contract()
    assert contract["case_status"] == "RESOLVED"
    assert contract["service_progress_receipt"]["next_update_by"] is None
    assert _db_state(db_path)["ledger_version"] == 4

    _record(
        "sequence-approved-not-picked-up-later-pickup-delivered",
        {
            "case_id": case_id,
            "steps": [not_picked, later_pickup, delivered],
            "persisted_ledger_version": persisted.version,
            "persisted_case_status": contract["case_status"],
        },
    )


def test_approved_on_time_pickup_then_delivered(tmp_path: Path) -> None:
    case_id = SEQUENCE_B_CASE
    app, repository, db_path = _app_with_case(tmp_path, case_id)

    on_time_pickup, _ = _step(
        app,
        case_id=case_id,
        event_id="EVENT-SEQ-B-ON-TIME-PICKUP",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T09:40:00+00:00",
        key="seq-b-key-0001",
    )
    assert on_time_pickup["case_status"] == "IN_FULFILLMENT"
    assert on_time_pickup["milestone"] == "IN_TRANSIT"
    assert on_time_pickup["obligation_status"] == "ON_TRACK"
    assert on_time_pickup["next_update_by"] == INITIAL_NEXT_CHECK
    assert on_time_pickup["notification_commits_next_update_at"] == INITIAL_NEXT_CHECK
    assert on_time_pickup["audit_trail_length"] == 2
    assert on_time_pickup["follow_up_candidate"] is None
    assert on_time_pickup["supervisor_escalation_candidate"] is None

    delivered, _ = _step(
        app,
        case_id=case_id,
        event_id="EVENT-SEQ-B-DELIVERED",
        event_type="SHIPMENT_DELIVERED",
        event_time="2030-01-01T10:10:00+00:00",
        key="seq-b-key-0002",
    )
    assert delivered["case_status"] == "RESOLVED"
    assert delivered["milestone"] == "DELIVERED"
    assert delivered["obligation_status"] == "COMPLETED"
    assert delivered["receipt_status"] == "COMPLETED"
    assert delivered["next_update_by"] is None
    assert delivered["audit_trail_length"] == 3

    persisted = repository.load(case_id)
    assert persisted is not None
    assert persisted.version == 3
    assert _db_state(db_path)["ledger_version"] == 3

    _record(
        "sequence-approved-on-time-pickup-delivered",
        {
            "case_id": case_id,
            "steps": [on_time_pickup, delivered],
            "persisted_ledger_version": persisted.version,
        },
    )


# --- acceptance criterion 2: rejected vectors and rollback evidence ----------


def test_direct_delivery_is_rejected_without_any_partial_write(tmp_path: Path) -> None:
    case_id = "CASE-SHIPMENT-HTTP-DIRECT"
    app, repository, db_path = _app_with_case(tmp_path, case_id)
    before = _db_state(db_path)

    status, body = _post(
        app,
        _payload(
            case_id=case_id,
            event_id="EVENT-DIRECT-DELIVERY",
            event_type="SHIPMENT_DELIVERED",
            event_time="2030-01-01T09:30:00+00:00",
            key="direct-delivery-key",
        ),
        request_id=str(uuid4()),
    )
    _assert_error_envelope(status, body, code="INVALID_EVENT_TRANSITION")
    assert status == 409
    assert body["error"]["message"] == "Shipment delivery requires IN_TRANSIT."
    assert body["error"]["retryable"] is False

    after = _db_state(db_path)
    assert after == before
    assert after["row_counts"] == {
        "events": 0,
        "idempotent_requests": 0,
        "audit_entries": 1,
        "case_versions": 1,
    }
    snapshot = repository.load(case_id)
    assert snapshot is not None
    assert snapshot.version == 1
    assert snapshot.accountability_state is not None
    assert len(snapshot.accountability_state.audit_trail) == 1

    legal, _ = _step(
        app,
        case_id=case_id,
        event_id="EVENT-AFTER-ROLLBACK-PICKUP",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T09:45:00+00:00",
        key="after-rollback-key",
    )
    assert legal["audit_trail_length"] == 2

    _record(
        "vector-direct-delivery-rollback",
        {
            "case_id": case_id,
            "http_status": status,
            "error": body["error"],
            "row_counts_before": before,
            "row_counts_after_rejection": after,
            "next_legal_event_status": legal["case_status"],
            "next_legal_event_milestone": legal["milestone"],
        },
    )


def test_reverse_ordered_event_is_rejected_and_the_first_response_is_preserved(
    tmp_path: Path,
) -> None:
    case_id = "CASE-SHIPMENT-HTTP-REVERSE"
    app, repository, db_path = _app_with_case(tmp_path, case_id)

    first_payload = _payload(
        case_id=case_id,
        event_id="EVENT-REVERSE-FIRST",
        event_type="SHIPMENT_NOT_PICKED_UP",
        event_time="2030-01-01T10:30:00+00:00",
        key="reverse-order-key-1",
    )
    first_status, first_body = _post(app, first_payload, request_id=str(uuid4()))
    assert first_status == 200
    assert first_body["data"]["accountability_state"]["case_status"] == "AT_RISK"
    assert first_body["data"]["accountability_state"]["open_obligation"]["status"] == "AT_RISK"
    assert first_body["data"]["follow_up_candidate"] == {
        "task_type": "WAREHOUSE_FOLLOW_UP",
        "existing_ticket_id": f"TICKET-{case_id}",
        "priority": "HIGH",
        "summary": "Confirm the delayed shipment handoff.",
    }
    assert first_body["data"]["supervisor_escalation_candidate"] == {
        "escalation_type": "PROMISE_OVERDUE",
        "priority": "HIGH",
        "summary": "Review the overdue fulfillment handoff.",
    }
    after_first = _db_state(db_path)

    status, body = _post(
        app,
        _payload(
            case_id=case_id,
            event_id="EVENT-REVERSE-EARLIER",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T10:29:00+00:00",
            key="reverse-order-key-2",
        ),
        request_id=str(uuid4()),
    )
    _assert_error_envelope(status, body, code="INVALID_EVENT_TRANSITION")
    assert status == 409
    assert _db_state(db_path) == after_first

    snapshot = repository.load(case_id)
    assert snapshot is not None
    assert snapshot.version == 2
    assert snapshot.event_high_watermark == "2030-01-01T10:30:00+00:00"

    replay_status, replay_body = _post(app, first_payload, request_id=str(uuid4()))
    assert replay_status == 200
    assert replay_body == first_body
    assert _db_state(db_path) == after_first

    _record(
        "vector-reverse-order",
        {
            "case_id": case_id,
            "first_event": first_payload,
            "first_http_status": first_status,
            "rejected_event": {
                "event_id": "EVENT-REVERSE-EARLIER",
                "event_time": "2030-01-01T10:29:00+00:00",
            },
            "rejected_http_status": status,
            "rejected_error": body["error"],
            "row_counts_after_rejection": _db_state(db_path),
            "replay_body_identical": replay_body == first_body,
            "persisted_event_high_watermark": snapshot.event_high_watermark,
        },
    )


def test_same_event_id_with_different_content_is_an_idempotency_conflict(
    tmp_path: Path,
) -> None:
    case_id = "CASE-SHIPMENT-HTTP-EVENT-CONFLICT"
    app, _, db_path = _app_with_case(tmp_path, case_id)

    status, _ = _post(
        app,
        _payload(
            case_id=case_id,
            event_id="EVENT-IDENTITY-CONFLICT",
            event_type="SHIPMENT_NOT_PICKED_UP",
            event_time="2030-01-01T09:30:00+00:00",
            key="event-conflict-key-1",
        ),
    )
    assert status == 200
    after_first = _db_state(db_path)

    status, body = _post(
        app,
        _payload(
            case_id=case_id,
            event_id="EVENT-IDENTITY-CONFLICT",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T09:31:00+00:00",
            key="event-conflict-key-2",
        ),
    )
    _assert_error_envelope(status, body, code="IDEMPOTENCY_CONFLICT")
    assert status == 409
    assert body["error"]["message"] == (
        "event_id was already recorded with different event content."
    )
    assert _db_state(db_path) == after_first

    _record(
        "vector-event-id-conflict",
        {
            "case_id": case_id,
            "http_status": status,
            "error": body["error"],
            "row_counts_after_first": after_first,
            "row_counts_after_conflict": _db_state(db_path),
        },
    )


def test_duplicate_request_key_replays_the_first_response_and_rejects_new_content(
    tmp_path: Path,
) -> None:
    case_id = "CASE-SHIPMENT-HTTP-KEY-REPLAY"
    app, repository, db_path = _app_with_case(tmp_path, case_id)
    payload = _payload(
        case_id=case_id,
        event_id="EVENT-KEY-REPLAY",
        event_type="SHIPMENT_NOT_PICKED_UP",
        event_time="2030-01-01T09:30:00+00:00",
        key="duplicate-key-replay",
    )

    first_request_id = str(uuid4())
    first_status, first_body = _post(app, payload, request_id=first_request_id)
    assert first_status == 200
    assert first_body["request_id"] == first_request_id
    assert first_body["data"]["accountability_state"]["audit_trail"][-1]["request_id"] == (
        first_request_id
    )
    audit_after_first = len(first_body["data"]["accountability_state"]["audit_trail"])
    after_first = _db_state(db_path)

    replay_status, replay_body = _post(app, payload, request_id=str(uuid4()))
    assert replay_status == 200
    assert replay_body == first_body
    assert replay_body["request_id"] == first_request_id
    assert len(replay_body["data"]["accountability_state"]["audit_trail"]) == audit_after_first
    assert _db_state(db_path) == after_first

    conflict = deepcopy(payload)
    conflict["event_time"] = "2030-01-01T09:31:00+00:00"
    conflict_status, conflict_body = _post(app, conflict, request_id=str(uuid4()))
    _assert_error_envelope(conflict_status, conflict_body, code="IDEMPOTENCY_CONFLICT")
    assert conflict_status == 409
    assert conflict_body["error"]["message"] == (
        "The idempotency key was already used with a different normalized body."
    )
    assert _db_state(db_path) == after_first

    snapshot = repository.load(case_id)
    assert snapshot is not None
    assert snapshot.version == 2
    assert snapshot.accountability_state is not None
    assert len(snapshot.accountability_state.audit_trail) == audit_after_first

    _record(
        "vector-duplicate-request-key",
        {
            "case_id": case_id,
            "first_http_status": first_status,
            "first_request_id": first_request_id,
            "replay_http_status": replay_status,
            "replay_body_identical": replay_body == first_body,
            "replay_request_id": replay_body["request_id"],
            "audit_trail_length_before_and_after": [
                audit_after_first,
                len(replay_body["data"]["accountability_state"]["audit_trail"]),
            ],
            "conflict_http_status": conflict_status,
            "conflict_error": conflict_body["error"],
            "row_counts_after_replay": _db_state(db_path),
        },
    )


def test_event_after_completion_replays_exactly_and_rejects_new_content(
    tmp_path: Path,
) -> None:
    case_id = "CASE-SHIPMENT-HTTP-TERMINAL"
    app, _, db_path = _app_with_case(tmp_path, case_id)

    _step(
        app,
        case_id=case_id,
        event_id="EVENT-TERMINAL-PICKUP",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T09:40:00+00:00",
        key="terminal-key-0001",
    )
    delivered_payload = _payload(
        case_id=case_id,
        event_id="EVENT-TERMINAL-DELIVERED",
        event_type="SHIPMENT_DELIVERED",
        event_time="2030-01-01T10:10:00+00:00",
        key="terminal-key-0002",
    )
    delivered_status, delivered_body = _post(app, delivered_payload, request_id=str(uuid4()))
    assert delivered_status == 200
    assert delivered_body["data"]["accountability_state"]["case_status"] == "RESOLVED"
    after_delivery = _db_state(db_path)

    replay_status, replay_body = _post(app, delivered_payload, request_id=str(uuid4()))
    assert replay_status == 200
    assert replay_body == delivered_body
    assert _db_state(db_path) == after_delivery

    late_status, late_body = _post(
        app,
        _payload(
            case_id=case_id,
            event_id="EVENT-AFTER-COMPLETION",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T10:20:00+00:00",
            key="terminal-key-0003",
        ),
        request_id=str(uuid4()),
    )
    _assert_error_envelope(late_status, late_body, code="INVALID_EVENT_TRANSITION")
    assert late_status == 409
    assert late_body["error"]["message"] == (
        "Completed shipment only permits an exact recorded replay."
    )
    assert _db_state(db_path) == after_delivery

    _record(
        "vector-terminal-replay",
        {
            "case_id": case_id,
            "delivered_http_status": delivered_status,
            "replay_http_status": replay_status,
            "replay_body_identical": replay_body == delivered_body,
            "post_completion_http_status": late_status,
            "post_completion_error": late_body["error"],
            "row_counts_after_delivery": after_delivery,
        },
    )


def test_concurrent_duplicate_and_distinct_keys_record_one_transition(
    tmp_path: Path,
) -> None:
    duplicate_case = "CASE-SHIPMENT-HTTP-CONCURRENT-SAME"
    app, _, db_path = _app_with_case(tmp_path, duplicate_case)
    shared_payload = _payload(
        case_id=duplicate_case,
        event_id="EVENT-CONCURRENT-SHARED",
        event_type="SHIPMENT_NOT_PICKED_UP",
        event_time="2030-01-01T09:30:00+00:00",
        key="concurrent-shared-key",
    )
    results = _post_concurrently(app, [shared_payload, shared_payload])
    same_key_statuses = [status for status, _ in results]
    assert same_key_statuses == [200, 200]
    bodies = [body for _, body in results]
    assert bodies[0] == bodies[1]
    same_key_request_ids = [body["request_id"] for body in bodies]
    assert len(set(same_key_request_ids)) == 1
    audit_length = len(bodies[0]["data"]["accountability_state"]["audit_trail"])
    assert audit_length == 2
    same_key_state = _db_state(db_path)
    assert same_key_state["row_counts"]["events"] == 1
    assert same_key_state["row_counts"]["idempotent_requests"] == 1
    assert same_key_state["ledger_version"] == 2

    distinct_case = "CASE-SHIPMENT-HTTP-CONCURRENT-DISTINCT"
    app, _, db_path = _app_with_case(tmp_path, distinct_case)
    distinct_payloads = [
        _payload(
            case_id=distinct_case,
            event_id="EVENT-CONCURRENT-DISTINCT",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T09:40:00+00:00",
            key=f"concurrent-distinct-key-{index}",
        )
        for index in (1, 2)
    ]
    results = _post_concurrently(app, distinct_payloads)
    distinct_statuses = [status for status, _ in results]
    assert distinct_statuses == [200, 200]
    bodies = [body for _, body in results]
    assert bodies[0] == bodies[1]
    assert bodies[0]["request_id"] == bodies[1]["request_id"]
    distinct_state = _db_state(db_path)
    assert distinct_state["row_counts"]["events"] == 1
    assert distinct_state["row_counts"]["idempotent_requests"] == 2
    assert distinct_state["ledger_version"] == 2

    _record(
        "vector-concurrency",
        {
            "same_key_concurrent": {
                "case_id": duplicate_case,
                "http_statuses": same_key_statuses,
                "bodies_identical": True,
                "shared_request_id": same_key_request_ids[0],
                "audit_trail_length": audit_length,
                "row_counts": same_key_state["row_counts"],
                "ledger_version": same_key_state["ledger_version"],
            },
            "distinct_key_concurrent": {
                "case_id": distinct_case,
                "http_statuses": distinct_statuses,
                "bodies_identical": bodies[0] == bodies[1],
                "shared_request_id": bodies[0]["request_id"],
                "row_counts": distinct_state["row_counts"],
                "ledger_version": distinct_state["ledger_version"],
            },
        },
    )


def test_unknown_case_and_unavailable_ledger_never_become_success(tmp_path: Path) -> None:
    unknown_case = "CASE-SHIPMENT-HTTP-UNKNOWN"
    repository = SQLiteLedgerRepository(tmp_path / "unknown.db")
    app = _app(ShipmentEventService(repository=repository))
    status, body = _post(
        app,
        _payload(
            case_id=unknown_case,
            event_id="EVENT-UNKNOWN-CASE",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T09:40:00+00:00",
            key="unknown-case-key",
        ),
        request_id=str(uuid4()),
    )
    _assert_error_envelope(status, body, code="INVALID_EVENT_TRANSITION")
    assert status == 409
    unknown_case_message = body["error"]["message"]
    assert unknown_case_message == (
        "Shipment event requires an existing accountability ledger."
    )
    assert repository.load(unknown_case) is None

    class UnavailableRepository:
        def execute(self, **kwargs: Any) -> Any:
            del kwargs
            raise LedgerUnavailable("ledger offline")

    status, body = _post(
        _app(ShipmentEventService(repository=UnavailableRepository())),
        _payload(
            case_id="CASE-SHIPMENT-HTTP-UNAVAILABLE",
            event_id="EVENT-UNAVAILABLE",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T09:40:00+00:00",
            key="unavailable-key",
        ),
    )
    _assert_error_envelope(status, body, code="INTERNAL_ERROR")
    assert status == 503
    assert body["error"]["retryable"] is True

    class ConflictingRepository:
        def execute(self, **kwargs: Any) -> Any:
            del kwargs
            raise LedgerConflict("ledger version changed")

    status, body = _post(
        _app(ShipmentEventService(repository=ConflictingRepository())),
        _payload(
            case_id="CASE-SHIPMENT-HTTP-CONFLICT",
            event_id="EVENT-CONFLICT",
            event_type="SHIPMENT_PICKED_UP",
            event_time="2030-01-01T09:40:00+00:00",
            key="conflict-key-0001",
        ),
    )
    _assert_error_envelope(status, body, code="INVALID_EVENT_TRANSITION")
    assert status == 409

    _record(
        "vector-fault-rollback",
        {
            "unknown_case": {"http_status": 409, "message": unknown_case_message},
            "unknown_case_rows_created": repository.load(unknown_case) is not None,
            "unavailable_ledger": {"http_status": 503, "retryable": True},
            "conflicting_ledger": {"http_status": 409, "retryable": False},
        },
    )


# --- acceptance criterion 2: request-schema boundary -------------------------


def test_invalid_requests_use_the_frozen_schema_error_envelope(tmp_path: Path) -> None:
    case_id = "CASE-SHIPMENT-HTTP-SCHEMA"
    app, _, db_path = _app_with_case(tmp_path, case_id)
    before = _db_state(db_path)

    invalid_time = _payload(
        case_id=case_id,
        event_id="EVENT-INVALID-TIME",
        event_type="SHIPMENT_PICKED_UP",
        event_time="not-a-date-time",
        key="invalid-time-key",
    )
    status, body = _post(app, invalid_time)
    _assert_error_envelope(status, body, code="SCHEMA_INVALID")
    assert status == 400
    assert body["error"]["message"] == "event_time must be a date-time with an offset."

    extra_field = _payload(
        case_id=case_id,
        event_id="EVENT-EXTRA-FIELD",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T09:40:00+00:00",
        key="extra-field-key",
    )
    extra_field["actor"] = "CLIENT"
    status, body = _post(app, extra_field)
    _assert_error_envelope(status, body, code="SCHEMA_INVALID")
    assert status == 400

    missing_case = _payload(
        case_id=case_id,
        event_id="EVENT-MISSING-CASE",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T09:40:00+00:00",
        key="missing-case-key",
    )
    del missing_case["case_id"]
    status, body = _post(app, missing_case)
    _assert_error_envelope(status, body, code="SCHEMA_INVALID")
    assert status == 400

    short_key = _payload(
        case_id=case_id,
        event_id="EVENT-SHORT-KEY",
        event_type="SHIPMENT_PICKED_UP",
        event_time="2030-01-01T09:40:00+00:00",
        key="short",
    )
    status, body = _post(app, short_key)
    _assert_error_envelope(status, body, code="SCHEMA_INVALID")
    assert status == 400

    unknown_event_type = _payload(
        case_id=case_id,
        event_id="EVENT-UNKNOWN-TYPE",
        event_type="SHIPMENT_LOST",
        event_time="2030-01-01T09:40:00+00:00",
        key="unknown-type-key",
    )
    status, body = _post(app, unknown_event_type)
    _assert_error_envelope(status, body, code="SCHEMA_INVALID")
    assert status == 400

    status, body = _post(app, None)
    _assert_error_envelope(status, body, code="VALIDATION_ERROR")
    assert status == 400

    assert _db_state(db_path) == before

    _record(
        "vector-schema-boundary",
        {
            "invalid_event_time": {"http_status": 400, "code": "SCHEMA_INVALID"},
            "extra_field": {"http_status": 400, "code": "SCHEMA_INVALID"},
            "missing_case_id": {"http_status": 400, "code": "SCHEMA_INVALID"},
            "short_idempotency_key": {"http_status": 400, "code": "SCHEMA_INVALID"},
            "unknown_event_type": {"http_status": 400, "code": "SCHEMA_INVALID"},
            "non_json_body": {"http_status": 400, "code": "VALIDATION_ERROR"},
            "row_counts_after_rejections": _db_state(db_path),
        },
    )


def _post_concurrently(
    app: FastAPI,
    payloads: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    results: list[tuple[int, dict[str, Any]] | None] = [None] * len(payloads)
    errors: list[BaseException] = []
    barrier = threading.Barrier(len(payloads))

    def worker(index: int, payload: dict[str, Any]) -> None:
        try:
            barrier.wait(timeout=30)
            results[index] = _post(app, payload)
        except BaseException as error:  # noqa: BLE001 - re-raised on the main thread
            errors.append(error)

    threads = [
        threading.Thread(target=worker, args=(index, payload))
        for index, payload in enumerate(payloads)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors
    assert all(result is not None for result in results)
    return [result for result in results if result is not None]
