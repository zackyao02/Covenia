from __future__ import annotations

import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "contracts"))

import check_contracts  # noqa: E402


def test_locked_contract_vectors_pass_strict_validation() -> None:
    summary = check_contracts.validate_contracts(strict=True)

    assert summary["schemas_validated"] >= 14
    assert summary["vectors_validated"] >= 16


def shipment_event_with_time(event_time: str) -> dict[str, str]:
    return {
        "case_id": "CASE-FORMAT-001",
        "event_id": "EVENT-FORMAT-001",
        "event_type": "SHIPMENT_PICKED_UP",
        "event_time": event_time,
        "idempotency_key": "shipment-format-key",
    }


@pytest.mark.parametrize(
    "event_time",
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
def test_draft_2020_12_date_time_rejects_parseable_non_rfc3339_forms(event_time: str) -> None:
    schemas, registry = check_contracts.load_schema_registry()
    validator = check_contracts.validator_for(
        "shipment-event-request.schema.json", schemas, registry
    )

    # These values are accepted by Python's permissive ISO parser but fall
    # outside RFC 3339's required date-time ABNF.
    assert datetime.fromisoformat(event_time)
    assert check_contracts.validation_messages(validator, shipment_event_with_time(event_time))


@pytest.mark.parametrize(
    "event_time",
    (
        "2030-01-01T11:00:00Z",
        "2030-01-01t11:00:00.123456789z",
        "2032-02-29T11:00:00-00:00",
        "1990-12-31T23:59:60Z",
    ),
)
def test_draft_2020_12_date_time_keeps_legal_rfc3339_forms(event_time: str) -> None:
    schemas, registry = check_contracts.load_schema_registry()
    validator = check_contracts.validator_for(
        "shipment-event-request.schema.json", schemas, registry
    )

    assert not check_contracts.validation_messages(validator, shipment_event_with_time(event_time))


def test_prepared_action_expresses_the_two_approved_p0_actions() -> None:
    schemas, registry = check_contracts.load_schema_registry()
    validator = check_contracts.validator_for(
        "prepared-action.schema.json", schemas, registry
    )
    for action_type in (
        "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "REPEAT_EXPLANATION_REQUEST",
    ):
        action = {
            "action_id": f"ACTION-{action_type}",
            "action_type": action_type,
            "requires_human_approval": False,
        }
        assert not check_contracts.validation_messages(validator, action)


def test_approved_d03_repeat_evidence_contract_uses_e1_not_p0() -> None:
    lock = check_contracts.load_json(check_contracts.LOCK_PATH)
    evaluate_vectors = check_contracts.load_json(
        check_contracts.VECTOR_DIR / "evaluate.json"
    )["vectors"]
    vectors_by_id = {vector["id"]: vector for vector in evaluate_vectors}

    check_contracts.validate_d03_repeat_evidence_semantics(lock, vectors_by_id)

    regressed_vectors = deepcopy(vectors_by_id)
    regressed_vectors["evaluate-d03-repeat-evidence-e1"]["expected"]["http_status"] = 400
    with pytest.raises(check_contracts.ContractCheckError, match="HTTP 200"):
        check_contracts.validate_d03_repeat_evidence_semantics(lock, regressed_vectors)

    inconsistent_vectors = deepcopy(vectors_by_id)
    inconsistent_vectors["evaluate-d03-repeat-evidence-e1"]["response"]["data"][
        "fact_trace"
    ]["active_promise_count"] = 1
    with pytest.raises(check_contracts.ContractCheckError, match="active_promise_count"):
        check_contracts.validate_d03_repeat_evidence_semantics(lock, inconsistent_vectors)


def test_decision_result_rejects_p0_success_but_keeps_suppressed_rule_audit() -> None:
    schemas, registry = check_contracts.load_schema_registry()
    evaluate_vectors = check_contracts.load_json(
        check_contracts.VECTOR_DIR / "evaluate.json"
    )["vectors"]
    vectors_by_id = {vector["id"]: vector for vector in evaluate_vectors}

    check_contracts.validate_p0_success_schema_semantics(schemas, registry, vectors_by_id)
    validator = check_contracts.validator_for(
        "decision-result.schema.json", schemas, registry
    )
    p0_success_data = deepcopy(
        vectors_by_id["evaluate-d03-repeat-evidence-e1"]["response"]["data"]
    )
    p0_success_data.update(
        decision="INTERVENE", rule_id="P0_PROHIBITED_ACTION", rule_priority=400
    )
    assert check_contracts.validation_messages(validator, p0_success_data)
    suppressed_ids = schemas["decision-result.schema.json"]["properties"]["fact_trace"][
        "properties"
    ]["suppressed_rule_ids"]["items"]["enum"]
    assert "P0_PROHIBITED_ACTION" in suppressed_ids


def test_d08_a32_time_authorities_and_notification_text_negative_controls() -> None:
    lock = check_contracts.load_json(check_contracts.LOCK_PATH)
    shipment_vectors = check_contracts.load_json(
        check_contracts.VECTOR_DIR / "shipment.json"
    )["vectors"]
    vectors_by_id = {vector["id"]: vector for vector in shipment_vectors}

    check_contracts.validate_d08_a32_time_semantics(lock, vectors_by_id)
    committed_instant = vectors_by_id["shipment-not-picked-up-success"]["response"][
        "data"
    ]["proactive_notification_draft"]["commits_next_update_at"]
    negative_texts = (
        "The shipment handoff is being escalated and another update will follow.",
        f"The shipment handoff is being escalated; the next update will follow by "
        f"{committed_instant.replace('11:00', '11:30')}.",
    )
    for text in negative_texts:
        regressed_vectors = deepcopy(vectors_by_id)
        regressed_vectors["shipment-not-picked-up-success"]["response"]["data"][
            "proactive_notification_draft"
        ]["text"] = text
        with pytest.raises(
            check_contracts.ContractCheckError,
            match="notification text must contain commits_next_update_at",
        ):
            check_contracts.validate_d08_a32_time_semantics(lock, regressed_vectors)
