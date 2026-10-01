"""Emit implementation evidence to stdout without writing files or using models.

Run from the checkout root with the BATCH-15 interpreter and
``-m backend.tests.rules.evidence_probe``. All examples are explicit synthetic
server DTOs. The in-memory mutant must fail its named A14 safety assertion.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from random import Random
from unittest.mock import patch
from uuid import UUID

from covenia_b.domain.types import AccountabilityState, PreparedAction
from covenia_b.rules import RULE_VERSION, engine, evaluate_decision

from .scenarios import SCENARIOS


def _source_hash() -> str:
    content = subprocess.check_output(
        [
            "git",
            "show",
            "HEAD:backend/src/covenia_b/rules/engine.py",
        ]
    )
    return hashlib.sha256(content).hexdigest().upper()


def main() -> None:
    matrix = []
    metamorphic = []
    random = Random(15001)
    for scenario in SCENARIOS:
        state, action = scenario.inputs()
        state.to_contract()
        action.to_contract()
        result = evaluate_decision(state, action)
        assert (result.decision, result.rule_id, result.rule_priority) == scenario.expected
        assert result.suppressed_rule_ids == scenario.suppressed
        matrix.append(
            {
                "id": scenario.name,
                "inputs": {
                    "accountability_state": state.to_contract(),
                    "prepared_action": action.to_contract(),
                },
                "actual": {
                    "decision": result.decision,
                    "rule_id": result.rule_id,
                    "rule_priority": result.rule_priority,
                    "http_status_mapping": result.http_status,
                    "matched_rule_ids": result.matched_rule_ids,
                    "fact_trace": result.fact_trace.model_dump(mode="json"),
                    "reason": result.reason,
                },
                "expected": {
                    "decision": scenario.expected[0],
                    "rule_id": scenario.expected[1],
                    "priority": scenario.expected[2],
                    "suppressed_rule_ids": scenario.suppressed,
                },
                "result": "EVIDENCED",
            }
        )
        sample = None
        for _ in range(32):
            renamed = state.model_dump(mode="json")
            renamed["case_id"] = str(UUID(int=random.getrandbits(128)))
            renamed["experience_gap_diagnosis"]["traceable_service_facts"][0]["source_ids"] = [
                str(UUID(int=random.getrandbits(128)))
            ]
            renamed_state = AccountabilityState.model_validate(renamed)
            renamed_action = PreparedAction.model_validate(
                {
                    **action.model_dump(),
                    "action_id": str(UUID(int=random.getrandbits(128))),
                }
            )
            recalculated = evaluate_decision(renamed_state, renamed_action)
            assert (
                recalculated.decision,
                recalculated.rule_id,
                recalculated.rule_priority,
            ) == scenario.expected
            assert (
                recalculated.fact_trace == result.fact_trace
                and recalculated.reason == result.reason
            )
            cloned_state = AccountabilityState.model_validate_json(renamed_state.model_dump_json())
            cloned_action = PreparedAction.model_validate_json(renamed_action.model_dump_json())
            assert evaluate_decision(cloned_state, cloned_action) == recalculated
            sample = {
                "case_id": renamed_state.case_id,
                "action_id": renamed_action.action_id,
                "session_source_id": renamed["experience_gap_diagnosis"]["traceable_service_facts"][
                    0
                ]["source_ids"][0],
            }
        metamorphic.append(
            {
                "scenario": scenario.name,
                "renaming_trials": 32,
                "json_reparse_trials": 32,
                "result": "EVIDENCED",
                "last_identifiers": sample,
            }
        )

    before = _source_hash()
    state, action = SCENARIOS[1].inputs()
    with patch.object(
        engine,
        "_RULES",
        tuple(
            replace(rule, priority=200) if rule.rule_id == "H1" else rule for rule in engine._RULES
        ),
    ):
        mutant_result = evaluate_decision(state, action)
        try:
            assert mutant_result.rule_id == "H1", "A14 must select H1 over E1"
        except AssertionError as error:
            assert str(error) == "A14 must select H1 over E1"
            observed_failure = str(error)
        else:
            raise AssertionError("priority mutant escaped the A14 safety assertion")
    restored = evaluate_decision(state, action)
    assert restored.rule_id == "H1" and restored.rule_priority == 350
    after = _source_hash()
    assert before == after
    print(
        json.dumps(
            {
                "rule_matrix": {
                    "batch_id": "BATCH-15",
                    "rule_version": RULE_VERSION,
                    "mode": "UNIT",
                    "http_was_run": False,
                    "vectors": matrix,
                },
                "metamorphic_evidence": {
                    "batch_id": "BATCH-15",
                    "seed": 15001,
                    "mode": "UNIT",
                    "trials": metamorphic,
                    "totals": {"id_renamings": 352, "fresh_json_recomputations": 352},
                    "negative_control": {
                        "mode": "MUTATION",
                        "mutation": "in-memory H1 priority 350 -> 200",
                        "inner_expected_assertion": "A14 must select H1 over E1",
                        "inner_observed_assertion": observed_failure,
                        "inner_assertion_failed": True,
                        "mutant_selected_rule": mutant_result.rule_id,
                        "outer_result": "EVIDENCED",
                        "restored_selection": {
                            "rule_id": restored.rule_id,
                            "priority": restored.rule_priority,
                        },
                        "source_hash_method": (
                            "SHA256 raw git show "
                            "HEAD:backend/src/covenia_b/rules/engine.py bytes"
                        ),
                        "source_hash_before": before,
                        "source_hash_after": after,
                    },
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
