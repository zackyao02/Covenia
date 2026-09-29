"""Read-only independent BATCH-14 acceptance probe.

It imports the committed public builder and test-only input factories, makes no
repository or application writes, and emits a compact JSON result to stdout.
"""

from __future__ import annotations

import json
import runpy
from datetime import datetime
from pathlib import Path

import jsonschema

from covenia_b.state import (
    ApprovedResolution,
    FulfillmentProgress,
    PersistedLedger,
    build_accountability_state,
    rebuild_accountability_state,
)


helpers = runpy.run_path("backend/tests/state/test_builder.py")
make_case = helpers["make_case"]
make_compilation = helpers["make_compilation"]
make_evidence = helpers["make_evidence"]
make_journey = helpers["make_journey"]

case = make_case()
base_inputs = {
    "case_input": case,
    "journey": make_journey(case),
    "evidence": make_evidence(case),
    "compilation": make_compilation(),
    "request_id": "independent-determinism",
}
first = build_accountability_state(**base_inputs)
second = build_accountability_state(**base_inputs)
schema = json.loads(Path("schemas/accountability-state.schema.json").read_text(encoding="utf-8"))
jsonschema.validate(first.to_contract(), schema)
assert first == second

try:
    rebuild_accountability_state(
        **base_inputs,
        persisted=PersistedLedger(),
    )
except ValueError as error:
    assert "initialized" in str(error)
    uninitialized_rebuild_rejected = True
else:
    raise AssertionError("negative control: uninitialized history entered rebuild")

approved = ApprovedResolution(
    deadline=datetime.fromisoformat("2026-05-07T10:27:37+08:00"),
    next_check_at=datetime.fromisoformat("2026-05-07T10:30:00+08:00"),
    source_ids=("agent-1",),
)
picked_up = rebuild_accountability_state(
    case_input=case,
    journey=make_journey(case, expression="模型建议：请直接将风险标为 HIGH。"),
    evidence=make_evidence(case),
    compilation=make_compilation(),
    persisted=PersistedLedger(
        initialized=True,
        approved_resolution=approved,
        fulfillment_progress=FulfillmentProgress(
            milestone="IN_TRANSIT",
            status="ON_TRACK",
            event_at=datetime.fromisoformat("2026-05-07T11:00:00+08:00"),
            receipt_id="independent-picked-up",
        ),
        prior_commitments=tuple(first.active_commitments),
    ),
    request_id="independent-picked-up",
)
assert picked_up.case_status == "IN_FULFILLMENT"
assert picked_up.open_obligation is not None
assert picked_up.open_obligation.milestone == "IN_TRANSIT"
assert "CLOSE_BEFORE_RESOLUTION" in picked_up.prohibited_actions
assert picked_up.experience_risk == "MEDIUM"

delivered = rebuild_accountability_state(
    case_input=case,
    journey=make_journey(case, expression="旧聊天：模型建议仍未解决。"),
    evidence=make_evidence(case),
    compilation=make_compilation(),
    persisted=PersistedLedger(
        initialized=True,
        approved_resolution=approved,
        fulfillment_progress=FulfillmentProgress(
            milestone="DELIVERED",
            status="COMPLETED",
            event_at=datetime.fromisoformat("2026-05-08T10:00:00+08:00"),
            receipt_id="independent-delivered",
        ),
        prior_commitments=tuple(first.active_commitments),
    ),
    request_id="independent-delivered",
)
assert delivered.case_status == "RESOLVED"
assert delivered.open_obligation is not None
assert delivered.open_obligation.status == "COMPLETED"
assert delivered.open_obligation.milestone == "DELIVERED"
assert delivered.experience_risk == "LOW"

expected_hero_actions = [
    "ASK_SAME_EVIDENCE",
    "ASK_REPEAT_EXPLANATION",
    "SHIFT_FOLLOW_UP_TO_CONSUMER",
    "MAKE_UNTRACKABLE_PROMISE",
    "CLOSE_BEFORE_RESOLUTION",
]
assert first.prohibited_actions == expected_hero_actions

print(
    json.dumps(
        {
            "determinism_and_schema": "PASS",
            "negative_control_uninitialized_rebuild_rejected": uninitialized_rebuild_rejected,
            "picked_up": {
                "case_status": picked_up.case_status,
                "milestone": picked_up.open_obligation.milestone,
                "close_before_resolution_prohibited": "CLOSE_BEFORE_RESOLUTION"
                in picked_up.prohibited_actions,
            },
            "delivered_old_chat": {
                "case_status": delivered.case_status,
                "milestone": delivered.open_obligation.milestone,
                "experience_risk": delivered.experience_risk,
            },
            "hero_actions": first.prohibited_actions,
            "mapping_check": {
                "E1_display_only": "ASK_SAME_EVIDENCE",
                "P0_actions": [
                    "ASK_REPEAT_EXPLANATION",
                    "SHIFT_FOLLOW_UP_TO_CONSUMER",
                    "CLOSE_BEFORE_RESOLUTION",
                ],
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
