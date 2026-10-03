from fastapi.testclient import TestClient
from datetime import datetime
import json
from pathlib import Path
import pytest

from backend.decision import engine as decision_engine
from backend.main import app, analyses, deadline_escalations, idempotency, last_event_times, redact_for_model, shipment_stages, states


client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_hero_fixture_keeps_original_fuzzy_ack_before_deadline() -> None:
    cases = json.loads((PROJECT_ROOT / "fixtures/demo-cases.json").read_text(encoding="utf-8"))
    ground_truth = json.loads((PROJECT_ROOT / "fixtures/ground-truth.json").read_text(encoding="utf-8"))
    frontend_example = json.loads((PROJECT_ROOT / "frontend/src/api/examples/01-analyze-case.json").read_text(encoding="utf-8"))
    hero = next(item["case_input"] for item in cases if item["demo_case_id"] == "DEMO_001")
    expected = next(item for item in ground_truth if item["demo_case_id"] == "DEMO_001")

    fuzzy_ack = next(message for message in hero["conversation"] if message["message_id"] == "94357468399952.PNM")
    assert fuzzy_ack["text"] == "行，那尽快哈"
    assert fuzzy_ack["speaker"] == "CONSUMER"
    assert fuzzy_ack["source_kind"] == "COMPETITION_MOCK"

    promise = expected["expected_promise"]
    agent_promise = next(message for message in hero["conversation"] if message["text"] == promise["raw_text"])
    assert agent_promise["speaker"] == "AGENT"
    evaluation_time = datetime.fromisoformat(hero["evaluation_time"])
    deadline = datetime.fromisoformat(promise["deadline"])
    follow_up = datetime.fromisoformat(next(
        message["timestamp"] for message in hero["conversation"] if message["message_id"] == "DEMO_AUG_MSG_001"
    ))
    assert evaluation_time < deadline
    assert follow_up == datetime.fromisoformat("2026-05-07T09:32:00+08:00")
    assert 40 * 60 < (deadline - evaluation_time).total_seconds() < 60 * 60
    assert "RAISE_PRIORITY" not in expected["expected_action_impacts"]

    front_input = frontend_example["case_input_fixture"]
    assert front_input["evaluation_time"] == hero["evaluation_time"]
    assert [m["message_id"] for m in front_input["conversation"]] == [m["message_id"] for m in hero["conversation"]]


def test_demo_adapter_does_not_claim_live_model_or_measured_usage() -> None:
    reset_service()
    data = analyze()
    assert data["model_metadata"]["model_id"] == "COVENIA_DEMO_ADAPTER"
    assert data["extracted_journey"]["model_metadata"]["model_id"] == "COVENIA_DEMO_ADAPTER"
    assert data["runtime_metrics"] == {
        "measurement_status": "NOT_MEASURED",
        "input_tokens": None,
        "output_tokens": None,
        "inference_latency_ms": None,
        "rule_substitution_count": None,
    }
    decision = client.post("/api/actions/evaluate", json={
        "case_id": "DEMO_001", "prepared_action": hero_action(),
    }).json()["data"]
    assert decision["runtime_metrics"]["measurement_status"] == "NOT_MEASURED"
    assert decision["runtime_metrics"]["inference_latency_ms"] is None


@pytest.fixture(autouse=True)
def disable_live_typesafe_calls(monkeypatch) -> None:
    """Keep the default API suite deterministic and independent of real credits."""
    monkeypatch.setattr(decision_engine, "typesafe_configured", lambda: False)
    monkeypatch.setattr(decision_engine, "ask_jev", lambda state, questions: {
        "ok": False,
        "source": "RULE_FALLBACK",
        "attempted": False,
        "error": {"code": "TYPESAFE_API_KEY_NOT_SET", "message": "test fallback"},
        "latency_ms": 0,
        "raw": None,
        "model_version": "test-fallback",
    })


def reset_service() -> None:
    states.clear()
    analyses.clear()
    shipment_stages.clear()
    last_event_times.clear()
    idempotency.clear()
    deadline_escalations.clear()
    decision_engine._CACHE.clear()
    decision_engine.AUDIT_LOG.clear()


def analyze(case_id: str = "DEMO_001") -> dict:
    response = client.post("/api/cases/analyze", json={"case_id": case_id})
    assert response.status_code == 200
    assert response.json()["error"] is None
    return response.json()["data"]


def hero_action(kind: str = "ASK_EVIDENCE") -> dict:
    return {
        "action_id": "ACT_TEST",
        "action_type": kind,
        "requested_scope": {
            "order_id": "6920185815517983396",
            "fulfillment_item_id": "6920185815517983396-XC33003",
            "sku_id": "XC33003",
            "issue_type": "PACKAGE_DAMAGE",
        },
        "requires_human_approval": False,
    }


def test_evaluate_uses_server_state_and_challenge_gate() -> None:
    reset_service()
    analyze()
    base = {"case_id": "DEMO_001", "prepared_action": hero_action()}
    forged = client.post("/api/actions/evaluate", json={
        **base,
        "evidence_status": "MISMATCHED",
        "challenge_overrides": {"requested_scope": {**hero_action()["requested_scope"], "sku_id": "GIFT-B5-MASK-2"}},
    }).json()
    assert forged["data"]["rule_id"] == "E1"
    assert forged["data"]["challenge_mode"] is False

    challenged = client.post("/api/actions/evaluate", json={
        **base,
        "challenge_mode": True,
        "challenge_overrides": {"requested_scope": {**hero_action()["requested_scope"], "sku_id": "GIFT-B5-MASK-2"}},
    }).json()
    assert challenged["data"]["rule_id"] == "E2"
    assert challenged["data"]["challenge_mode"] is True


def test_priority_order_is_p0_then_h1_then_e1() -> None:
    reset_service()
    source = analyze()["extracted_journey"]
    assert source["case_id"] == "DEMO_001"
    close = client.post("/api/actions/evaluate", json={"case_id": "DEMO_001", "prepared_action": hero_action("CLOSE_CASE")}).json()
    assert close["data"]["rule_id"] == "P0_PROHIBITED_ACTION"
    assert close["data"]["rule_priority"] == 400

    case_input = client.post("/api/cases/analyze", json={"case_id": "DEMO_001"}).json()["data"]
    # Build the adverse case through the permitted challenge input, rather than a rule keyed by case ID.
    from backend.main import find_case
    adverse = find_case("DEMO_001")
    adverse["current_issue"]["issue_type"] = "ADVERSE_REACTION"
    client.post("/api/cases/analyze", json={"case_id": "ADVERSE", "challenge_mode": True, "case_input": adverse})
    action = hero_action()
    action["requested_scope"]["issue_type"] = "ADVERSE_REACTION"
    reviewed = client.post("/api/actions/evaluate", json={"case_id": "ADVERSE", "prepared_action": action}).json()
    assert reviewed["data"]["rule_id"] == "H1"
    assert reviewed["data"]["rule_priority"] == 350
    assert "E1" in reviewed["data"]["fact_trace"]["suppressed_rule_ids"]


def test_approval_is_validated_and_idempotent() -> None:
    reset_service()
    analyze()
    missing = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT", "approver_id": "",
        "idempotency_key": "approve-001", "human_edits": {},
    })
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "VALIDATION_ERROR"
    payload = {"case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT", "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-001", "human_edits": {"executor": "WAREHOUSE"}}
    first = client.post("/api/resolutions/approve", json=payload).json()
    replay = client.post("/api/resolutions/approve", json=payload).json()
    assert first == replay
    assert first["data"]["accountability_state"]["open_obligation"]["next_check_at"] == "2026-05-07T10:30:00+08:00"
    conflict = client.post("/api/resolutions/approve", json={**payload, "approver_id": "ANOTHER"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_shipment_transition_requires_pickup_before_delivery() -> None:
    reset_service()
    analyze()
    direct = client.post("/api/events/shipment", json={"case_id": "DEMO_001", "event_id": "DIRECT", "event_type": "SHIPMENT_DELIVERED", "event_time": "2026-05-08T15:20:00+08:00", "idempotency_key": "shipment-direct"})
    assert direct.status_code == 409
    pickup = client.post("/api/events/shipment", json={"case_id": "DEMO_001", "event_id": "PICKUP", "event_type": "SHIPMENT_PICKED_UP", "event_time": "2026-05-07T10:10:00+08:00", "idempotency_key": "shipment-pickup"}).json()
    assert pickup["data"]["accountability_state"]["case_status"] == "IN_FULFILLMENT"
    delivered = client.post("/api/events/shipment", json={"case_id": "DEMO_001", "event_id": "DELIVER", "event_type": "SHIPMENT_DELIVERED", "event_time": "2026-05-08T15:20:00+08:00", "idempotency_key": "shipment-deliver"}).json()
    assert delivered["data"]["accountability_state"]["case_status"] == "RESOLVED"
    assert delivered["data"]["accountability_state"]["active_commitments"] == []


def test_delayed_pickup_can_recover_after_not_picked_up_and_rejects_contradiction() -> None:
    reset_service()
    analyze()
    delayed = client.post("/api/events/shipment", json={
        "case_id": "DEMO_001", "event_id": "NOT-PICKED", "event_type": "SHIPMENT_NOT_PICKED_UP",
        "event_time": "2026-05-07T11:35:00+08:00", "idempotency_key": "shipment-not-picked",
    })
    assert delayed.status_code == 200
    assert delayed.json()["data"]["accountability_state"]["case_status"] == "AT_RISK"

    pickup = client.post("/api/events/shipment", json={
        "case_id": "DEMO_001", "event_id": "PICKUP-AFTER-DELAY", "event_type": "SHIPMENT_PICKED_UP",
        "event_time": "2026-05-07T11:50:00+08:00", "idempotency_key": "shipment-pickup-after-delay",
    })
    assert pickup.status_code == 200
    assert pickup.json()["data"]["accountability_state"]["case_status"] == "IN_FULFILLMENT"

    contradictory = client.post("/api/events/shipment", json={
        "case_id": "DEMO_001", "event_id": "CONTRADICTION", "event_type": "SHIPMENT_NOT_PICKED_UP",
        "event_time": "2026-05-07T12:00:00+08:00", "idempotency_key": "shipment-contradiction",
    })
    assert contradictory.status_code == 409
    assert contradictory.json()["error"]["code"] == "INVALID_EVENT_TRANSITION"


def test_redacts_pii_before_the_extractor_receives_case_text() -> None:
    case = {"conversation": [{"text": "请寄到地址：上海市徐汇区，联系电话 13800138000；我有不良反应。"}]}
    redacted, count = redact_for_model(case)
    assert count >= 3
    assert "13800138000" not in redacted["conversation"][0]["text"]
    assert "[已脱敏]" in redacted["conversation"][0]["text"]
    assert "13800138000" in case["conversation"][0]["text"]


def test_v11_customer_state_risk_priority_and_emerging_endpoints() -> None:
    reset_service()
    analyze()
    customer = client.get("/api/customer-state/DEMO_001")
    assert customer.status_code == 200
    customer_data = customer.json()["data"]
    assert customer_data["case_id"] == "DEMO_001"
    assert customer_data["emotion"]["risk_scoring_allowed"] is False
    assert customer_data["decision"]["decision"] in ("INTERVENE", "ALLOW", "HUMAN_REVIEW")
    assert customer_data["decision"]["decision_advisory"]["status"] in ("READY", "FALLBACK")
    assert customer_data["decision_advisory"]["assessment_id"] == customer_data["decision"]["jev_assessment_id"]

    risk = client.get("/api/risk")
    assert risk.status_code == 200
    risk_rows = risk.json()["data"]
    assert len(risk_rows) >= 3
    assert risk_rows == sorted(risk_rows, key=lambda item: item["score"], reverse=True)
    assert all(item["prediction"] is False for item in risk_rows)

    priority = client.get("/api/priority")
    assert priority.status_code == 200
    priority_rows = priority.json()["data"]
    assert [item["rank"] for item in priority_rows] == list(range(1, len(priority_rows) + 1))

    emerging = client.get("/api/emerging-issues")
    assert emerging.status_code == 200
    assert all(item["requires_human_confirmation"] is True and item["prediction"] is False for item in emerging.json()["data"])


def test_v11_decisions_aliases_evaluate_and_deadline_monitor_runs_once() -> None:
    reset_service()
    analyze()
    decision = client.post("/api/decisions", json={"case_id": "DEMO_001", "prepared_action": hero_action()})
    assert decision.status_code == 200
    assert decision.json()["data"]["decision_result"]["rule_id"] == "E1"

    payload = {"case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT", "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-deadline", "human_edits": {"executor": "WAREHOUSE"}}
    client.post("/api/resolutions/approve", json=payload)
    before = client.get("/api/deadlines").json()["data"]
    assert any(item["case_id"] == "DEMO_001" and item["status"] == "SCHEDULED" for item in before)

    first = client.post("/api/deadlines/run", json={"case_ids": ["DEMO_001"], "now": "2026-05-07T11:00:00+08:00"}).json()["data"]
    assert "DEMO_001" in first["escalated_case_ids"]
    assert first["deadline_states"][0]["status"] == "ESCALATED"
    audit_count = len(states["DEMO_001"]["audit_trail"])

    second = client.post("/api/deadlines/run", json={"case_ids": ["DEMO_001"], "now": "2026-05-07T12:00:00+08:00"}).json()["data"]
    assert second["deadline_states"][0]["escalated_once"] is True
    assert len(states["DEMO_001"]["audit_trail"]) == audit_count


def test_jev_decision_layer_falls_back_without_provider(monkeypatch) -> None:
    reset_service()
    monkeypatch.setattr(decision_engine, "ask_jev", lambda state, questions: {
        "ok": False,
        "source": "RULE_FALLBACK",
        "error": {"code": "TYPESAFE_API_KEY_NOT_SET", "message": "missing"},
        "latency_ms": 0,
        "raw": None,
    })
    monkeypatch.setattr(decision_engine, "typesafe_configured", lambda: False)
    analyze()

    decision = client.post("/api/decisions", json={"case_id": "DEMO_001", "prepared_action": hero_action()}).json()["data"]
    advisory = decision["decision_advisory"]
    assert advisory["status"] == "FALLBACK"
    assert advisory["source"] == "RULE_FALLBACK"
    assert advisory["configured"] is False
    assert advisory["jev_call"] == {
        "configured": False,
        "attempted": False,
        "succeeded": False,
        "fallback_used": True,
        "error_code": "TYPESAFE_API_KEY_NOT_SET",
    }
    assert advisory["next_best_action"]["source"] == "RULE_FALLBACK"
    assert decision_engine.AUDIT_LOG[-1]["provider_error"]["code"] == "TYPESAFE_API_KEY_NOT_SET"


def test_jev_decision_layer_maps_provider_response(monkeypatch) -> None:
    reset_service()
    monkeypatch.setattr(decision_engine, "ask_jev", lambda state, questions: {
        "ok": True,
        "source": "JEV",
        "error": None,
        "latency_ms": 12,
        "model_version": "systemone-test",
        "raw": {
            "answers": {
                "emotion_worsening": {"type": "noul", "noul": 0.91},
                "needs_human": {"type": "noul", "noul": 0.72},
                "next_action": {
                    "type": "choice",
                    "choice": "HUMAN_ESCALATION",
                    "probabilities": {
                        "CHECK_REPLACEMENT": 0.04,
                        "HUMAN_ESCALATION": 0.88,
                        "CONTINUE_TROUBLESHOOTING": 0.05,
                        "REQUEST_EVIDENCE": 0.03,
                    },
                },
            },
        },
    })
    monkeypatch.setattr(decision_engine, "typesafe_configured", lambda: True)
    analyze()

    customer = client.get("/api/customer-state/DEMO_001").json()["data"]
    advisory = customer["decision_advisory"]
    assert advisory["status"] == "READY"
    assert advisory["source"] == "JEV"
    assert advisory["jev_call"]["attempted"] is True
    assert advisory["jev_call"]["succeeded"] is True
    assert advisory["emotion"]["trend"] == "WORSENING"
    assert advisory["human_escalation"]["required"] is True
    assert advisory["next_best_action"]["recommended"] == "HUMAN_ESCALATION"
    assert advisory["audit"]["model_version"] == "systemone-test"
