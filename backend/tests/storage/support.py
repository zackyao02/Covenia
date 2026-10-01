"""Synthetic request/response construction; never a business implementation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from covenia_b.domain.types import (
    AccountabilityState,
    AuditEntry,
    CompiledCommitments,
    LedgerSnapshot,
)
from covenia_b.storage import EventRecord, Mutation, SQLiteLedgerRepository, StoredResponse

ROOT = Path(__file__).resolve().parents[3]
INSTANT = "2030-01-01T18:02:00+08:00"


def body(case_id: str = "9007199254740993", key: str = "synthetic-key-0001") -> dict:
    return {
        "case_id": case_id,
        "idempotency_key": key,
        "approver_id": "test-actor",
        "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "human_edits": {},
    }


def mutate(
    current: LedgerSnapshot | None,
    *,
    case_id: str = "9007199254740993",
    request_id: str = "first-request",
    event: EventRecord | None = None,
) -> Mutation:
    with (ROOT / "tests/contract-vectors/approve.json").open(encoding="utf-8") as stream:
        response = json.load(stream)["vectors"][0]["response"]
    if current is None:
        state_payload = response["data"]["accountability_state"]
        state_payload["case_id"] = case_id
        state_payload["audit_trail"] = []
        state = AccountabilityState.from_contract(state_payload)
        current = LedgerSnapshot(case_id, 0, None, state, CompiledCommitments((), True))
    assert current.accountability_state is not None
    state = current.accountability_state
    entry = AuditEntry(
        at=event.event_time if event else INSTANT,
        actor="test-actor",
        action=event.event_type if event else "RESOLUTION_APPROVED",
        changed_fields=["open_obligation"],
        request_id=request_id,
    )
    state = state.model_copy(update={"audit_trail": [*state.audit_trail, entry]})
    proposed = replace(current, accountability_state=state)
    response["data"]["accountability_state"] = state.to_contract()
    response["data"]["audit_trail"] = [item.model_dump(mode="json") for item in state.audit_trail]
    response["request_id"] = request_id
    return Mutation(proposed, StoredResponse(response, 200, {"X-Request-Id": request_id}))


def submit(
    repo: SQLiteLedgerRepository,
    *,
    case_id: str = "9007199254740993",
    key: str = "synthetic-key-0001",
    request_id: str = "first-request",
    event: EventRecord | None = None,
):
    request = body(case_id, key)
    if event is not None:
        request = {
            "case_id": case_id,
            "idempotency_key": key,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "event_time": event.event_time,
        }
    return repo.execute(
        case_id=case_id,
        operation="shipment" if event else "approve",
        idempotency_key=key,
        request_body=request,
        event=event,
        mutate=lambda current: mutate(current, case_id=case_id, request_id=request_id, event=event),
    )
