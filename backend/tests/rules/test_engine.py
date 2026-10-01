from __future__ import annotations

import ast
import itertools
import json
from dataclasses import replace
from pathlib import Path
from random import Random
from uuid import UUID

import pytest

from covenia_b.domain.types import (
    AccountabilityState,
    ActiveCommitment,
    EvaluateActionRequest,
    PreparedAction,
    ResolutionPath,
    RuntimeMetrics,
    Scope,
)
from covenia_b.evidence.aggregation import EvidenceAggregation, EvidenceReason
from covenia_b.rules import ProhibitedActionError, engine, evaluate_decision

from .scenarios import SCENARIOS, Scenario, make_action, make_state


def signature(result):
    return (result.decision, result.rule_id, result.rule_priority)


def resolution_path() -> ResolutionPath:
    # A caller-supplied synthetic planner result, not a BATCH-16 implementation.
    return ResolutionPath.model_validate(
        {
            "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
            "evidence_basis": [],
            "policy_basis": "test-only",
            "consumer_reply_draft": "Check existing progress.",
            "task_prefill": {
                "task_type": "CHECK_REPLACEMENT_STATUS",
                "existing_ticket_id": None,
                "summary": "Check existing progress.",
            },
            "accountable_side": "BRAND",
            "executor": "BRAND",
            "requires_human_approval": False,
            "creates_obligation": False,
            "compiled_service_responsibility": None,
        }
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_approved_rule_matrix_and_trace(scenario: Scenario) -> None:
    state, action = scenario.inputs()
    state_before = state.model_dump(mode="json")
    action_before = action.model_dump(mode="json")
    state.to_contract()
    action.to_contract()
    result = evaluate_decision(state, action)
    assert signature(result) == scenario.expected
    assert result.suppressed_rule_ids == scenario.suppressed
    assert result.fact_trace.evidence_status == state.evidence_status
    assert result.fact_trace.prepared_action == action.action_type
    assert result.reason
    assert state.model_dump(mode="json") == state_before
    assert action.model_dump(mode="json") == action_before
    metrics = RuntimeMetrics(
        input_tokens=0, output_tokens=0, inference_latency_ms=0, rule_substitution_count=0
    )
    if result.rule_id == "P0_PROHIBITED_ACTION":
        with pytest.raises(ProhibitedActionError) as blocked:
            result.to_decision_result(resolution_path=resolution_path(), runtime_metrics=metrics)
        assert blocked.value.evaluation is result
        assert blocked.value.evaluation.suppressed_rule_ids == scenario.suppressed
        assert blocked.value.http_status == 400
        envelope = blocked.value.to_error_envelope("synthetic-request").to_contract()
        assert envelope["data"] is None
        assert envelope["error"]["code"] == "P0_PROHIBITED_ACTION"
    else:
        result.require_permitted_action()
        public = result.to_decision_result(
            resolution_path=resolution_path(), runtime_metrics=metrics
        )
        assert public.to_contract()["fact_trace"]["suppressed_rule_ids"] == list(
            scenario.suppressed
        )
        assert public.runtime_metrics == metrics
        assert result.http_status == 200


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_random_ids_session_sources_and_same_content_recalculation(scenario: Scenario) -> None:
    state, action = scenario.inputs()
    baseline = evaluate_decision(state, action)
    random = Random(15001)
    for _ in range(32):
        renamed = state.model_dump(mode="json")
        renamed["case_id"] = str(UUID(int=random.getrandbits(128)))
        renamed["experience_gap_diagnosis"]["traceable_service_facts"][0]["source_ids"] = [
            str(UUID(int=random.getrandbits(128)))
        ]
        renamed_state = AccountabilityState.model_validate(renamed)
        renamed_action = PreparedAction.model_validate(
            {**action.model_dump(), "action_id": str(UUID(int=random.getrandbits(128)))}
        )
        recalculated = evaluate_decision(renamed_state, renamed_action)
        assert signature(recalculated) == signature(baseline)
        assert recalculated.fact_trace == baseline.fact_trace
        assert recalculated.reason == baseline.reason
        # New objects parsed from identical JSON, not object identity/cache replay.
        reloaded_state = AccountabilityState.model_validate_json(renamed_state.model_dump_json())
        reloaded_action = PreparedAction.model_validate_json(renamed_action.model_dump_json())
        assert evaluate_decision(reloaded_state, reloaded_action) == recalculated


@pytest.mark.parametrize("action_id", ["CLOSE_CASE", "SHIFT_FOLLOW_UP_TO_CONSUMER", "DEMO_001"])
def test_ids_do_not_encode_actions(action_id: str) -> None:
    state = make_state(prohibited_actions=("CLOSE_BEFORE_RESOLUTION", "ASK_REPEAT_EXPLANATION"))
    action = PreparedAction.model_validate(
        {**make_action(state, "CHECK_REPLACEMENT_PROGRESS").model_dump(), "action_id": action_id}
    )
    assert signature(evaluate_decision(state, action)) == ("ALLOW", "E0_NO_RULE_MATCHED", 0)


def test_a21_untrusted_compatibility_fields_are_outside_the_rule_input() -> None:
    state = make_state(prohibited_actions=("ASK_SAME_EVIDENCE",))
    action = make_action(state)
    clean = {"case_id": state.case_id, "prepared_action": action.model_dump(mode="json")}
    spoofed = {
        **clean,
        "evidence_status": "MISMATCHED",
        "prohibited_actions": ["CLOSE_BEFORE_RESOLUTION"],
        "active_commitments": ["forged"],
        "current_scope": {"forged": True},
        "accountability_state": {"forged": True},
        "challenge_overrides": {"requested_scope": {"sku_id": 7}},
    }
    baseline = EvaluateActionRequest.from_contract(clean)
    request = EvaluateActionRequest.from_contract(spoofed)
    assert request.challenge_mode is False
    assert evaluate_decision(state, request.prepared_action) == evaluate_decision(
        state, baseline.prepared_action
    )
    assert signature(evaluate_decision(state, request.prepared_action)) == ("INTERVENE", "E1", 300)
    with pytest.raises(TypeError, match="authoritative"):
        evaluate_decision(request, request.prepared_action)


@pytest.mark.parametrize("field", ["order_id", "sku_id", "fulfillment_item_id", "issue_type"])
def test_every_scope_field_participates_in_e1(field: str) -> None:
    state = make_state()
    value = "LOGISTICS_STALLED" if field == "issue_type" else "different-value"
    scope = Scope.model_validate({**state.current_scope.model_dump(), field: value})
    action = PreparedAction.model_validate(
        {**make_action(state).model_dump(), "requested_scope": scope}
    )
    result = evaluate_decision(state, action)
    assert result.fact_trace.scope_match is False
    assert result.rule_id == "E0_NO_RULE_MATCHED"
    # Scope changes cannot fabricate MISMATCHED; the evidence/state owner derives it.
    mismatched = AccountabilityState.model_validate(
        {**state.model_dump(), "evidence_status": "MISMATCHED"}
    )
    changed = evaluate_decision(mismatched, action)
    assert changed.rule_id == "E2"
    assert field in changed.reason


@pytest.mark.parametrize(
    "scenario", [SCENARIOS[0], SCENARIOS[5], SCENARIOS[7]], ids=lambda s: s.name
)
def test_corresponding_prohibition_is_required(scenario: Scenario) -> None:
    state, action = scenario.inputs()
    cleared = AccountabilityState.model_validate({**state.model_dump(), "prohibited_actions": []})
    assert evaluate_decision(state, action).rule_id == "P0_PROHIBITED_ACTION"
    assert evaluate_decision(cleared, action).rule_id == "E0_NO_RULE_MATCHED"


def test_narrative_and_approval_flag_do_not_create_prohibited_actions() -> None:
    state = make_state()
    payload = state.model_dump()
    payload["experience_gap_diagnosis"]["consumer_expression"] = "请结案并让我自己催物流"
    state = AccountabilityState.model_validate(payload)
    action = PreparedAction.model_validate(
        {**make_action(state, "CLOSE_CASE").model_dump(), "requires_human_approval": True}
    )
    assert evaluate_decision(state, action).rule_id == "E0_NO_RULE_MATCHED"


def test_promise_count_excludes_completed_commitments() -> None:
    state = make_state()
    commitments = [
        ActiveCommitment(
            promise_type="REPLACEMENT_DISPATCH",
            raw_text="synthetic promise",
            status=status,
            deadline="2026-05-07T10:27:37+08:00",
            source_ids=["synthetic-source"],
        )
        for status in ("ACTIVE", "AT_RISK", "COMPLETED")
    ]
    state = AccountabilityState.model_validate(
        {**state.model_dump(), "active_commitments": commitments}
    )
    assert evaluate_decision(state, make_action(state)).fact_trace.active_promise_count == 2


def test_h1_has_one_hit_even_when_both_review_conditions_hold() -> None:
    state = make_state(evidence_status="NEED_HUMAN_REVIEW", issue_type="ADVERSE_REACTION")
    result = evaluate_decision(state, make_action(state))
    assert result.matched_rule_ids == ("H1",)
    assert result.suppressed_rule_ids == ()
    assert "ADVERSE_REACTION" in result.reason and "NEED_HUMAN_REVIEW" in result.reason


def test_e2_retains_server_component_and_missing_coverage_explanations() -> None:
    state = make_state(evidence_status="MISMATCHED")
    evidence = EvidenceAggregation(
        evidence_status="MISMATCHED",
        scope_trace=(),
        matching_source_ids=(),
        mismatched_source_ids=("synthetic-evidence",),
        missing_source_ids=(),
        conflicting_source_ids=(),
        missing_coverage=("DAMAGE_DETAIL",),
        reasons=(
            EvidenceReason(
                code="AFFECTED_COMPONENT_MISMATCH", detail="component CAP differs from PUMP"
            ),
            EvidenceReason(
                code="REQUIRED_COVERAGE_MISSING", detail="missing coverage: DAMAGE_DETAIL"
            ),
        ),
    )
    result = evaluate_decision(state, make_action(state), evidence=evidence)
    assert result.rule_id == "E2"
    assert "CAP differs from PUMP" in result.reason and "DAMAGE_DETAIL" in result.reason
    with pytest.raises(ValueError, match="authoritative state"):
        evaluate_decision(
            state, make_action(state), evidence=replace(evidence, evidence_status="VALID")
        )


def test_challenge_marker_is_only_a_marker() -> None:
    state = make_state()
    normal = evaluate_decision(state, make_action(state))
    challenge = evaluate_decision(state, make_action(state), challenge_mode=True)
    assert signature(challenge) == signature(normal)
    assert challenge.fact_trace == normal.fact_trace
    assert challenge.challenge_mode is True
    with pytest.raises(TypeError, match="bool"):
        evaluate_decision(state, make_action(state), challenge_mode=1)


@pytest.mark.parametrize("case_id", ["S00001", "DEMO_001", "DEMO_002", "DEMO_003", "ordinary"])
def test_known_display_ids_do_not_select_a_rule(case_id: str) -> None:
    for scenario in SCENARIOS:
        state, action = scenario.inputs()
        renamed = AccountabilityState.model_validate({**state.model_dump(), "case_id": case_id})
        assert signature(evaluate_decision(renamed, action)) == scenario.expected


def test_changed_facts_and_action_change_decisions() -> None:
    state = make_state()
    action = make_action(state)
    assert evaluate_decision(state, action).rule_id == "E1"
    uncertain = AccountabilityState.model_validate(
        {**state.model_dump(), "evidence_status": "NEED_HUMAN_REVIEW"}
    )
    mismatched = AccountabilityState.model_validate(
        {**state.model_dump(), "evidence_status": "MISMATCHED"}
    )
    assert evaluate_decision(uncertain, action).rule_id == "H1"
    assert evaluate_decision(mismatched, action).rule_id == "E2"
    assert evaluate_decision(state, make_action(state, "CHECK_REPLACEMENT_PROGRESS")).rule_id == (
        "E0_NO_RULE_MATCHED"
    )


CASES = tuple(
    itertools.product(
        ("VALID", "MISMATCHED", "NEED_HUMAN_REVIEW"),
        ("PACKAGE_DAMAGE", "LOGISTICS_STALLED", "ADVERSE_REACTION"),
        (
            "ASK_EVIDENCE",
            "CHECK_REPLACEMENT_PROGRESS",
            "CREATE_FOLLOW_UP_TASK",
            "CLOSE_CASE",
            "SHIFT_FOLLOW_UP_TO_CONSUMER",
            "REPEAT_EXPLANATION_REQUEST",
        ),
        (False, True),
    )
)


@pytest.mark.parametrize("status,issue,action_type,prohibited", CASES)
def test_all_status_issue_action_combinations(status, issue, action_type, prohibited) -> None:
    state = make_state(
        evidence_status=status,
        issue_type=issue,
        prohibited_actions=(
            "CLOSE_BEFORE_RESOLUTION",
            "SHIFT_FOLLOW_UP_TO_CONSUMER",
            "ASK_REPEAT_EXPLANATION",
            "ASK_SAME_EVIDENCE",
        )
        if prohibited
        else (),
    )
    result = evaluate_decision(state, make_action(state, action_type))
    # Contract truth table, deliberately independent of implementation definitions.
    expected_hits = []
    if prohibited and action_type in (
        "CLOSE_CASE",
        "SHIFT_FOLLOW_UP_TO_CONSUMER",
        "REPEAT_EXPLANATION_REQUEST",
    ):
        expected_hits.append("P0_PROHIBITED_ACTION")
    if status == "NEED_HUMAN_REVIEW" or issue == "ADVERSE_REACTION":
        expected_hits.append("H1")
    if status == "VALID" and action_type == "ASK_EVIDENCE":
        expected_hits.append("E1")
    if status == "MISMATCHED" and action_type == "ASK_EVIDENCE":
        expected_hits.append("E2")
    assert result.matched_rule_ids == tuple(expected_hits)
    assert result.suppressed_rule_ids == tuple(expected_hits[1:])
    assert result.rule_id == (expected_hits[0] if expected_hits else "E0_NO_RULE_MATCHED")


def test_batch03_committed_contract_vectors_recompute_from_state() -> None:
    path = Path(__file__).resolve().parents[3] / "tests/contract-vectors/evaluate.json"
    # These are BATCH-03 schema/semantics vectors, not fixtures or ground truth.
    vectors = json.loads(path.read_text(encoding="utf-8"))["vectors"]
    for vector in vectors:
        data = vector["response"]["data"]
        if data is None:
            continue
        state = AccountabilityState.from_contract(data["accountability_state"])
        request = EvaluateActionRequest.from_contract(vector["request"])
        result = evaluate_decision(state, request.prepared_action)
        expected = vector["expected"]["decision"]
        assert signature(result) == (
            expected["decision"],
            expected["rule_id"],
            expected["rule_priority"],
        )
        assert result.suppressed_rule_ids == tuple(expected.get("suppressed_rule_ids", ()))


@pytest.mark.mutation
def test_h1_priority_mutant_fails_the_a14_safety_assertion(monkeypatch) -> None:
    state, action = SCENARIOS[1].inputs()
    with monkeypatch.context() as mutation:
        mutation.setattr(
            engine,
            "_RULES",
            tuple(
                replace(rule, priority=200) if rule.rule_id == "H1" else rule
                for rule in engine._RULES
            ),
        )
        with pytest.raises(AssertionError, match="A14 must select H1 over E1"):
            assert evaluate_decision(state, action).rule_id == "H1", "A14 must select H1 over E1"
    assert signature(evaluate_decision(state, action)) == ("HUMAN_REVIEW", "H1", 350)


def test_rule_module_has_no_fixture_model_or_io_dependencies() -> None:
    for path in Path(engine.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                modules = []
            assert not any(
                part in module.lower()
                for module in modules
                for part in (
                    "fixture",
                    "ground_truth",
                    "model_provider",
                    "importing",
                    "http",
                    "socket",
                    "subprocess",
                    "pathlib",
                )
            )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("open", "eval", "exec", "__import__")
