from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "contracts"))

import check_contracts  # noqa: E402


def test_locked_contract_vectors_pass_strict_validation() -> None:
    summary = check_contracts.validate_contracts(strict=True)

    assert summary["schemas_validated"] >= 14
    assert summary["vectors_validated"] >= 16


def test_draft_2020_12_date_time_format_is_enforced() -> None:
    schemas, registry = check_contracts.load_schema_registry()
    validator = check_contracts.validator_for(
        "shipment-event-request.schema.json", schemas, registry
    )
    invalid = {
        "case_id": "CASE-FORMAT-001",
        "event_id": "EVENT-FORMAT-001",
        "event_type": "SHIPMENT_PICKED_UP",
        "event_time": "not-a-date-time",
        "idempotency_key": "shipment-format-key",
    }

    assert check_contracts.validation_messages(validator, invalid)


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
    try:
        check_contracts.validate_d03_repeat_evidence_semantics(lock, regressed_vectors)
    except check_contracts.ContractCheckError as error:
        assert "HTTP 200" in str(error)
    else:
        raise AssertionError("D03 repeat evidence remapped to P0 was not rejected")
