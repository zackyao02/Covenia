from __future__ import annotations

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
