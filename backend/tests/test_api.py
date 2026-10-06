from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import copy
import json
from pathlib import Path
import pytest

from backend.decision import engine as decision_engine
from backend.draft_review import assess_draft, contains_unsupported_fulfillment_guarantee
from backend.main import app, analyses, analyzed_inputs, deadline_escalations, idempotency, last_event_times, redact_for_model, shipment_stages, simulated_clocks, states


client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_conversational_evidence_reply_stays_scoped_and_negative_phrase_is_not_request() -> None:
    scoped = assess_draft("对，不用重传整单。您只要补一张精华瓶口裂痕近照。")
    assert scoped["kind"] == "EVIDENCE_REQUEST"
    assert scoped["requires_confirmation"] is False
    negative = assess_draft("照片不用再发，您之前提交的材料已经收到了。")
    assert "EVIDENCE_REQUEST" not in negative["_detected_actions"]


def test_existing_fulfillment_check_is_not_misread_as_a_delivery_guarantee() -> None:
    progress_reply = "您之前提交的泵头照片已经收到，不用再发。我会先核实换货单是否已被物流揽收，并在约定更新时间前主动告诉您核实结果。"
    assert contains_unsupported_fulfillment_guarantee(progress_reply) is False
    assert contains_unsupported_fulfillment_guarantee("我保证换货件明天送达。") is True
    assert contains_unsupported_fulfillment_guarantee("我会为您安排补发。") is True
    assert contains_unsupported_fulfillment_guarantee("我不能保证明天送达，但会帮您查询物流进度。") is False
    assert assess_draft("我会先核实换货进度，并主动告知您。 ")["_detected_actions"] == ["PROGRESS_UPDATE"]
    assert assess_draft("我会先核实换货单是否已被物流揽收，并在约定更新时间前主动告诉您核实结果。")["kind"] == "PROGRESS_UPDATE"
    assert "CLOSE_CASE" not in assess_draft("您的问题还未解决，我不会结案。")["_detected_actions"]


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


def test_demo_session_reset_clears_only_selected_demo_case() -> None:
    reset_service()
    analyze("DEMO_001")
    states["DEMO_001"]["case_status"] = "RESOLVED"
    shipment_stages["DEMO_001"] = "DELIVERED"
    last_event_times["DEMO_001"] = datetime.fromisoformat("2026-05-08T15:20:00+08:00")
    idempotency[("shipment", "DEMO_001", "shipment-reset-test")] = ("fingerprint", {"ok": True})
    states["DEMO_002"] = {"case_id": "DEMO_002", "case_status": "ACTION_REVIEW"}

    reset = client.post("/api/demo/session/reset", json={"case_id": "DEMO_001"})
    assert reset.status_code == 200
    assert reset.json()["data"] == {"case_id": "DEMO_001", "reset": True}
    assert "DEMO_001" not in states
    assert "DEMO_001" not in analyses
    assert "DEMO_001" not in analyzed_inputs
    assert "DEMO_001" not in shipment_stages
    assert "DEMO_001" not in last_event_times
    assert ("shipment", "DEMO_001", "shipment-reset-test") not in idempotency
    assert states["DEMO_002"]["case_status"] == "ACTION_REVIEW"

    replayed = analyze("DEMO_001")
    assert replayed["accountability_state"]["open_obligation"] is None

    invalid = client.post("/api/demo/session/reset", json={"case_id": "not-a-demo-case"})
    assert invalid.status_code == 400


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
    analyzed_inputs.clear()
    shipment_stages.clear()
    last_event_times.clear()
    simulated_clocks.clear()
    idempotency.clear()
    deadline_escalations.clear()
    decision_engine._CACHE.clear()
    decision_engine.AUDIT_LOG.clear()


def approve_demo_replacement() -> dict:
    response = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-clock-demo",
        "human_edits": {"executor": "WAREHOUSE"},
    })
    assert response.status_code == 200
    return response.json()["data"]["accountability_state"]


def test_demo_clock_requires_approved_active_replacement_and_near_due_is_honest() -> None:
    reset_service()
    analyze()
    rejected = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "NEAR_DUE", "idempotency_key": "clock-before-approval",
    })
    assert rejected.status_code == 409
    assert states["DEMO_001"]["active_commitments"]
    assert states["DEMO_001"]["open_obligation"] is None

    approved = approve_demo_replacement()
    deadline = datetime.fromisoformat(approved["open_obligation"]["deadline"])
    response = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "NEAR_DUE", "idempotency_key": "clock-near-due-01",
    })
    assert response.status_code == 200
    data = response.json()["data"]
    expected_clock = deadline - timedelta(minutes=10)
    assert data["simulation"] is True

    assert "人工审核" not in data["proactive_notification_draft"]["text"]
    assert "T10:" not in data["proactive_notification_draft"]["text"]
    assert datetime.fromisoformat(data["service_clock"]) == expected_clock
    assert data["deadline_state"]["status"] == "NEAR_DUE"
    assert data["accountability_state"]["active_commitments"][0]["status"] == "ACTIVE"
    assert data["accountability_state"]["case_status"] == approved["case_status"]
    assert data["proactive_notification_draft"]["requires_human_approval"] is True
    next_check = (deadline - timedelta(minutes=5)).isoformat()
    assert data["proactive_notification_draft"]["commits_next_update_at"] == next_check
    assert data["accountability_state"]["open_obligation"]["next_check_at"] == next_check
    assert data["accountability_state"]["service_progress_receipt"]["next_update_by"] == next_check
    assert data["accountability_state"]["audit_trail"][-1]["actor"] == "DEMO_CLOCK_SIMULATOR"


def test_demo_clock_overdue_escalates_once_and_idempotency_conflicts() -> None:
    reset_service()
    analyze()
    approve_demo_replacement()
    response = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "OVERDUE", "idempotency_key": "clock-overdue-01",
    })
    assert response.status_code == 200
    data = response.json()["data"]
    clock = datetime.fromisoformat(data["service_clock"])
    deadline = datetime.fromisoformat(data["accountability_state"]["open_obligation"]["deadline"])
    assert clock == deadline + timedelta(minutes=1)
    assert data["accountability_state"]["case_status"] == "AT_RISK"
    assert data["accountability_state"]["active_commitments"][0]["status"] == "AT_RISK"
    obligation = data["accountability_state"]["open_obligation"]
    receipt = data["accountability_state"]["service_progress_receipt"]
    assert datetime.fromisoformat(obligation["next_check_at"]) > clock
    assert obligation["next_check_at"] == receipt["next_update_by"] == data["proactive_notification_draft"]["commits_next_update_at"]
    assert data["follow_up_candidate"]["task_type"] == "WAREHOUSE_FOLLOW_UP"
    assert data["follow_up_candidate"]["existing_ticket_id"]
    assert data["supervisor_escalation_candidate"]["escalation_type"] == "PROMISE_OVERDUE"
    assert data["proactive_notification_draft"]["requires_human_approval"] is True
    assert data["simulation"] is True
    assert any("已逾期" in fact["statement"] for fact in data["customer_state"]["facts"])
    assert all("仍在有效期内" not in item for item in data["customer_state"]["evidence"]["known"])
    before_rewind = copy.deepcopy(states["DEMO_001"])
    rewind = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "NEAR_DUE", "idempotency_key": "clock-overdue-rewind",
    })
    assert rewind.status_code == 409
    assert states["DEMO_001"] == before_rewind
    reviewed = client.post("/api/actions/evaluate", json={
        "case_id": "DEMO_001", "prepared_action": hero_action("CHECK_REPLACEMENT_PROGRESS"),
        "draft_reply": data["proactive_notification_draft"]["text"],
    }).json()["data"]
    assert reviewed["resolution_path"]["compiled_service_responsibility"]["next_check_at"] == receipt["next_update_by"]
    confirmed = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-clock-notification",
        "human_edits": {"executor": "WAREHOUSE", "next_check_at": receipt["next_update_by"],
                        "consumer_reply": data["proactive_notification_draft"]["text"]},
    })
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["accountability_state"]["open_obligation"]["status"] == "AT_RISK"

    audit_count = len(states["DEMO_001"]["audit_trail"])
    repeated = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "OVERDUE", "idempotency_key": "clock-overdue-02",
    }).json()["data"]
    assert repeated["follow_up_candidate"] is None
    assert repeated["supervisor_escalation_candidate"] is None
    assert len(states["DEMO_001"]["audit_trail"]) == audit_count
    conflict = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "NEAR_DUE", "idempotency_key": "clock-overdue-01",
    })
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_demo_clock_outputs_match_extension_contract_without_changing_frozen_schema() -> None:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource

    schemas = [json.loads(file.read_text(encoding="utf-8")) for file in (PROJECT_ROOT / "schemas").glob("*.json")]
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas)
    extension = next(schema for schema in schemas if schema["$id"] == "demo-clock-advance-response.schema.json")
    validator = Draft202012Validator(extension, registry=registry, format_checker=FormatChecker())
    reset_service()
    analyze()
    approve_demo_replacement()
    for step in ("NEAR_DUE", "OVERDUE"):
        response = client.post("/api/demo/clock/advance", json={
            "case_id": "DEMO_001", "step": step, "idempotency_key": f"clock-schema-{step}",
        })
        assert response.status_code == 200
        errors = list(validator.iter_errors(response.json()["data"]))
        def leaf_errors(error):
            return [leaf for child in error.context for leaf in leaf_errors(child)] if error.context else [error]
        assert not errors, [(list(error.absolute_path), error.validator, str(error.validator_value)[:240]) for root in errors for error in leaf_errors(root)]


def test_demo_clock_never_rewinds_blocks_in_transit_and_reset_clears_it() -> None:
    reset_service()
    analyze()
    approve_demo_replacement()
    near = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "NEAR_DUE", "idempotency_key": "clock-no-rewind-01",
    }).json()["data"]
    near_clock = datetime.fromisoformat(near["service_clock"])
    repeated_near = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "NEAR_DUE", "idempotency_key": "clock-no-rewind-02",
    }).json()["data"]
    assert datetime.fromisoformat(repeated_near["service_clock"]) == near_clock

    pickup_time = (near_clock + timedelta(minutes=1)).isoformat()
    pickup = client.post("/api/events/shipment", json={
        "case_id": "DEMO_001", "event_id": "PICKUP_AFTER_CLOCK", "event_type": "SHIPMENT_PICKED_UP",
        "event_time": pickup_time, "idempotency_key": "pickup-after-demo-clock",
    })
    assert pickup.status_code == 200
    blocked = client.post("/api/demo/clock/advance", json={
        "case_id": "DEMO_001", "step": "OVERDUE", "idempotency_key": "clock-after-pickup",
    })
    assert blocked.status_code == 409

    reset = client.post("/api/demo/session/reset", json={"case_id": "DEMO_001"})
    assert reset.status_code == 200
    assert "DEMO_001" not in simulated_clocks
    assert client.get("/api/customer-state/DEMO_001").json()["data"]["service_clock"] == "2026-05-07T09:42:00+08:00"


def analyze(case_id: str = "DEMO_001") -> dict:
    response = client.post("/api/cases/analyze", json={"case_id": case_id})
    assert response.status_code == 200
    assert response.json()["error"] is None
    return response.json()["data"]


def test_simulated_new_consumer_reply_reaches_jev_without_rewriting_service_state(monkeypatch) -> None:
    reset_service()
    analyze()
    baseline = client.get("/api/customer-state/DEMO_001").json()["data"]
    original_state = copy.deepcopy(states["DEMO_001"])
    seen: list[dict] = []

    def fake_jev(model_state: dict, _questions: list) -> dict:
        seen.append(model_state)
        return {
            "ok": True, "attempted": True, "source": "JEV", "latency_ms": 1,
            "model_version": "test-jev", "raw": {"answers": {
                "emotion_worsening": {"type": "noul", "noul": 0.92},
                "needs_human": {"type": "noul", "noul": 0.10},
                "next_action": {"type": "choice", "choice": "CHECK_REPLACEMENT", "probabilities": {
                    "CHECK_REPLACEMENT": 0.90, "HUMAN_ESCALATION": 0.03,
                    "CONTINUE_TROUBLESHOOTING": 0.04, "REQUEST_EVIDENCE": 0.03,
                }},
            }},
        }

    monkeypatch.setattr(decision_engine, "ask_jev", fake_jev)
    monkeypatch.setattr(decision_engine, "typesafe_configured", lambda: True)
    messages = [
        {"message_id": "DEMO_CHAT_AGENT_1", "timestamp": "2026-05-07T09:41:00+08:00", "speaker": "AGENT", "text": "我会核实换货进度。", "source_kind": "DEMO_AUGMENTATION"},
        {"message_id": "DEMO_CHAT_CONSUMER_1", "timestamp": "2026-05-07T09:42:00+08:00", "speaker": "CONSUMER", "text": "我已经问了好几次，什么时候能有结果？", "source_kind": "DEMO_AUGMENTATION"},
    ]
    response = client.post("/api/demo/customer-state/refresh", json={"case_id": "DEMO_001", "challenge_mode": True, "messages": messages})
    assert response.status_code == 200
    refreshed = response.json()["data"]
    assert refreshed["decision_advisory"]["source"] == "JEV"
    assert refreshed["decision_advisory"]["emotion"]["trend"] == "WORSENING"
    assert refreshed["decision_advisory"]["customer_state_version"] != baseline["decision_advisory"]["customer_state_version"]
    assert seen[-1]["recent_messages"][-1]["text"] == messages[-1]["text"]
    assert seen[-1]["consumer_emotion_comparison"]["latest_consumer_message"] == messages[-1]["text"]
    assert seen[-1]["consumer_emotion_comparison"]["previous_consumer_message"]
    assert refreshed["emotion"]["source_evidence_ids"] == ["DEMO_AUG_MSG_001", "DEMO_CHAT_CONSUMER_1"]
    assert any(item["source_id"] == "DEMO_CHAT_CONSUMER_1" for item in refreshed["source_evidence"])
    assert states["DEMO_001"] == original_state

    duplicate = client.post("/api/demo/customer-state/refresh", json={"case_id": "DEMO_001", "challenge_mode": True, "messages": [messages[0], messages[0]]})
    assert duplicate.status_code == 400
    assert states["DEMO_001"] == original_state


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

    repeated_photo_reply = client.post("/api/actions/evaluate", json={
        **base,
        "draft_reply": "麻烦您再上传一次泵头破损照片，我收到后才能继续处理。",
    })
    assert repeated_photo_reply.status_code == 400
    assert repeated_photo_reply.json()["data"] is None
    assert repeated_photo_reply.json()["error"]["code"] == "P0_PROHIBITED_ACTION"
    assert "重复提交" in repeated_photo_reply.json()["error"]["message"]


def test_priority_order_is_p0_then_h1_then_e1() -> None:
    reset_service()
    source = analyze()["extracted_journey"]
    assert source["case_id"] == "DEMO_001"
    close = client.post("/api/actions/evaluate", json={"case_id": "DEMO_001", "prepared_action": hero_action("CLOSE_CASE")})
    assert close.status_code == 400
    assert close.json()["data"] is None
    assert close.json()["error"]["code"] == "P0_PROHIBITED_ACTION"
    wrapped_close = client.post("/api/decisions", json={
        "case_id": "DEMO_001",
        "prepared_action": hero_action("CLOSE_CASE"),
    })
    assert wrapped_close.status_code == 400
    assert wrapped_close.json()["data"] is None
    assert wrapped_close.json()["error"]["code"] == "P0_PROHIBITED_ACTION"

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


def test_adverse_reaction_case_routes_to_human_without_fake_image_or_promise() -> None:
    reset_service()
    from backend.main import find_case

    case_input = copy.deepcopy(find_case("DEMO_001"))
    case_input["case_id"] = "DEMO_003"
    case_input["data_provenance"]["source_session_id"] = "S00003"
    case_input["order"]["order_id"] = "6920185815517983398"
    case_input["order"]["items"] = [{
        "fulfillment_item_id": "6920185815517983398-EL-SUN40",
        "sku_id": "EL-SUN40",
        "product_name": "清爽防晒乳 SPF50+ 40ml",
        "item_role": "PRIMARY",
    }]
    case_input["current_issue"] = {
        "fulfillment_item_id": "6920185815517983398-EL-SUN40",
        "sku_id": "EL-SUN40",
        "issue_type": "ADVERSE_REACTION",
        "affected_component": "UNKNOWN",
    }
    case_input["conversation"] = [{
        "message_id": "S00003_MSG_001",
        "timestamp": "2026-05-05T10:14:00+08:00",
        "speaker": "CONSUMER",
        "text": "用了清爽防晒乳后脸有点泛红，能帮我确认下一步该怎么办吗？",
        "source_kind": "DEMO_AUGMENTATION",
    }]
    case_input["evidence_images"] = []
    case_input["service_tickets"] = []
    analyzed = client.post("/api/cases/analyze", json={
        "case_id": "DEMO_003", "challenge_mode": True, "case_input": case_input,
    }).json()["data"]

    state = analyzed["accountability_state"]
    assert state["current_scope"]["issue_type"] == "ADVERSE_REACTION"
    assert state["evidence_status"] == "NEED_HUMAN_REVIEW"
    assert state["active_commitments"] == []
    assert analyzed["extracted_journey"]["image_observations"] == []

    decision = client.post("/api/actions/evaluate", json={
        "case_id": "DEMO_003",
        "prepared_action": {
            "action_id": "ACT_ADVERSE",
            "action_type": "ASK_EVIDENCE",
            "requested_scope": state["current_scope"],
            "requires_human_approval": False,
        },
    }).json()["data"]
    assert decision["rule_id"] == "H1"
    assert "自动判断原因" in decision["reason"]
    assert "粉底液" not in decision["resolution_path"]["consumer_reply_draft"]

    safe_reply = client.post("/api/actions/evaluate", json={
        "case_id": "DEMO_003",
        "prepared_action": {
            "action_id": "ACT_ADVERSE_REPLY",
            "action_type": "ASK_EVIDENCE",
            "requested_scope": state["current_scope"],
            "requires_human_approval": False,
        },
        "draft_reply": "已记录您使用后泛红、刺痛的反馈，不用先上传面部照片。我会交给专人核实。",
    }).json()["data"]
    assert safe_reply["rule_id"] == "H1"
    assert safe_reply["draft_assessment"]["requires_confirmation"] is True

    customer = client.get("/api/customer-state/DEMO_003").json()["data"]
    assert "不要求提交健康图片" in customer["emotion"]["communication_guidance"]


def test_mismatched_gift_evidence_reply_names_the_current_product() -> None:
    reset_service()
    from backend.main import find_case

    case_input = copy.deepcopy(find_case("DEMO_001"))
    case_input["case_id"] = "DEMO_002"
    case_input["data_provenance"]["source_session_id"] = "S00002"
    case_input["order"]["order_id"] = "6920185815517983397"
    case_input["order"]["items"][0].update({
        "fulfillment_item_id": "6920185815517983397-EL-RS30",
        "sku_id": "EL-RS30",
        "product_name": "复颜修护精华 30ml",
    })
    case_input["order"]["items"][1]["fulfillment_item_id"] = "6920185815517983397-GIFT-01"
    case_input["current_issue"].update({
        "fulfillment_item_id": "6920185815517983397-EL-RS30",
        "sku_id": "EL-RS30",
        "affected_component": "BOTTLE",
    })
    case_input["evidence_images"] = [{
        "evidence_id": "S00002_GIFT_IMG",
        "file_name": "s00002-gift-evidence.jpg",
        "submitted_at": "2026-05-05T10:55:00+08:00",
        "declared_view_type": "PACKAGE_CONTEXT",
        "source_kind": "TEAM_SYNTHETIC_AUGMENTATION",
        "source_message_id": "S00002_MSG_003",
        "competition_reference_path": None,
    }]
    analyzed = client.post("/api/cases/analyze", json={
        "case_id": "DEMO_002", "challenge_mode": True, "case_input": case_input,
    }).json()["data"]
    state = analyzed["accountability_state"]
    gift = next(item for item in case_input["order"]["items"] if item["item_role"] == "GIFT")
    decision = client.post("/api/actions/evaluate", json={
        "case_id": "DEMO_002",
        "prepared_action": {
            "action_id": "ACT_GIFT_SCOPE",
            "action_type": "ASK_EVIDENCE",
            "requested_scope": state["current_scope"],
            "requires_human_approval": False,
        },
        "challenge_mode": True,
        "challenge_overrides": {"requested_scope": {
            **state["current_scope"],
            "fulfillment_item_id": gift["fulfillment_item_id"],
            "sku_id": gift["sku_id"],
        }},
    }).json()["data"]
    reply = decision["resolution_path"]["consumer_reply_draft"]
    assert decision["rule_id"] == "E2"
    assert "复颜修护精华" in reply

    scoped_reply = client.post("/api/actions/evaluate", json={
        "case_id": "DEMO_002",
        "prepared_action": {
            "action_id": "ACT_GIFT_REPLY", "action_type": "ASK_EVIDENCE",
            "requested_scope": state["current_scope"], "requires_human_approval": False,
        },
        "challenge_mode": True,
        "challenge_overrides": {"requested_scope": {
            **state["current_scope"],
            "fulfillment_item_id": gift["fulfillment_item_id"],
            "sku_id": gift["sku_id"],
        }},
        "draft_reply": "照片收到了。现有照片拍的是赠品面膜，不用重发订单；麻烦只补充一张精华瓶口裂痕的近照，我就按这件商品继续核实。",
    }).json()["data"]
    assert scoped_reply["rule_id"] == "E2"
    assert scoped_reply["draft_assessment"]["kind"] == "EVIDENCE_REQUEST"
    assert scoped_reply["draft_assessment"]["requires_confirmation"] is False
    assert "粉底液" not in reply


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
    assert first["data"]["accountability_state"]["open_obligation"]["next_check_at"] == "2026-05-07T10:10:00+08:00"
    conflict = client.post("/api/resolutions/approve", json={**payload, "approver_id": "ANOTHER"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_approval_accepts_existing_order_progress_reply_without_promising_new_fulfillment() -> None:
    reset_service()
    analyze()
    reply = "您之前提交的泵头照片已经收到，不用再发。我会先核实换货单是否已被物流揽收，并在约定更新时间前主动告诉您核实结果。"
    response = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001",
        "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT_ZHOU",
        "idempotency_key": "approve-existing-progress-001",
        "human_edits": {
            "executor": "WAREHOUSE",
            "next_check_at": "2026-05-07T10:10:00+08:00",
            "consumer_reply": reply,
        },
    })
    assert response.status_code == 200
    assert response.json()["data"]["approved_resolution"]["consumer_reply_draft"] == reply
    assert response.json()["data"]["accountability_state"]["open_obligation"]["milestone"] == "AWAITING_CARRIER_PICKUP"


def test_explicit_follow_up_approval_does_not_silently_become_reply_only() -> None:
    reset_service()
    analyze()
    response = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-explicit-follow-up",
        "human_edits": {"executor": "WAREHOUSE", "next_check_at": "2026-05-07T10:10:00+08:00",
                        "consumer_reply": "现有换货单已经记录，我们会继续处理。"},
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approved_resolution"]["creates_obligation"] is True
    assert data["accountability_state"]["open_obligation"]["next_check_at"] == "2026-05-07T10:10:00+08:00"


def test_follow_up_reply_preserves_pickup_stage_and_receipt() -> None:
    reset_service()
    analyze()
    first = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-before-pickup",
        "human_edits": {"executor": "WAREHOUSE", "next_check_at": "2026-05-07T10:10:00+08:00",
                        "consumer_reply": "我会先核实换货单是否被物流揽收，并主动告知进度。"},
    })
    assert first.status_code == 200
    pickup = client.post("/api/events/shipment", json={
        "case_id": "DEMO_001", "event_id": "PICKUP", "event_type": "SHIPMENT_PICKED_UP",
        "event_time": "2026-05-07T10:10:00+08:00", "idempotency_key": "pickup-before-reply",
    })
    assert pickup.status_code == 200
    before = pickup.json()["data"]["accountability_state"]
    follow_up = client.post("/api/resolutions/approve", json={
        "case_id": "DEMO_001", "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "approver_id": "AGENT_ZHOU", "idempotency_key": "approve-after-pickup",
        "human_edits": {"executor": "WAREHOUSE", "next_check_at": "2026-05-08T10:10:00+08:00",
                        "consumer_reply": "我会核实换货件的运输进度并主动告知您。"},
    })
    assert follow_up.status_code == 200
    after = follow_up.json()["data"]["accountability_state"]
    assert after["open_obligation"]["milestone"] == before["open_obligation"]["milestone"] == "IN_TRANSIT"
    assert after["open_obligation"]["executor"] == before["open_obligation"]["executor"] == "LOGISTICS_PROVIDER"
    assert after["open_obligation"]["deadline"] == before["open_obligation"]["deadline"]
    assert after["service_progress_receipt"]["brand_action"] == before["service_progress_receipt"]["brand_action"]
    assert after["service_progress_receipt"]["next_update_by"] == "2026-05-08T10:10:00+08:00"


def test_demo_service_side_cases_advance_without_reusing_wrong_evidence() -> None:
    reset_service()
    analyze("DEMO_002")
    evidence = client.post("/api/demo/events/service", json={
        "case_id": "DEMO_002", "event_type": "CURRENT_SCOPE_EVIDENCE_SUBMITTED",
        "idempotency_key": "serum-evidence-001",
    })
    assert evidence.status_code == 200
    state = evidence.json()["data"]["accountability_state"]
    assert state["evidence_status"] == "VALID"
    assert state["consumer_input_required"] is False
    assert "精华瓶口" in state["service_progress_receipt"]["received_evidence"][1]
    assert analyze("DEMO_002")["accountability_state"]["demo_service_event"] == "CURRENT_SCOPE_EVIDENCE_SUBMITTED"
    assert client.post("/api/demo/events/service", json={
        "case_id": "DEMO_002", "event_type": "CURRENT_SCOPE_EVIDENCE_SUBMITTED",
        "idempotency_key": "serum-evidence-002",
    }).status_code == 409

    analyze("DEMO_003")
    too_early = client.post("/api/demo/events/service", json={
        "case_id": "DEMO_003", "event_type": "SPECIALIST_FOLLOWED_UP",
        "idempotency_key": "specialist-early-001",
    })
    assert too_early.status_code == 409
    assigned = client.post("/api/demo/events/service", json={
        "case_id": "DEMO_003", "event_type": "SPECIALIST_ASSIGNED",
        "idempotency_key": "specialist-assigned-001",
    })
    assert assigned.status_code == 200
    assert assigned.json()["data"]["accountability_state"]["demo_specialist_status"] == "已接手"
    follow_up = client.post("/api/demo/events/service", json={
        "case_id": "DEMO_003", "event_type": "SPECIALIST_FOLLOWED_UP",
        "idempotency_key": "specialist-followed-up-001",
    })
    assert follow_up.status_code == 200
    assert follow_up.json()["data"]["accountability_state"]["demo_specialist_status"] == "已反馈"


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

    backdated_pickup = client.post("/api/events/shipment", json={
        "case_id": "DEMO_001", "event_id": "BACKDATED-PICKUP", "event_type": "SHIPMENT_PICKED_UP",
        "event_time": "2026-05-07T10:10:00+08:00", "idempotency_key": "shipment-backdated-pickup",
    })
    assert backdated_pickup.status_code == 409
    assert backdated_pickup.json()["error"]["code"] == "INVALID_EVENT_TRANSITION"

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
    assert states["DEMO_001"]["audit_trail"][-1]["at"] == "2026-05-07T11:00:00+08:00"
    assert states["DEMO_001"]["audit_trail"][-1]["action"] == "PROMISE_DEADLINE_ESCALATED"
    audit_count = len(states["DEMO_001"]["audit_trail"])

    second = client.post("/api/deadlines/run", json={"case_ids": ["DEMO_001"], "now": "2026-05-07T12:00:00+08:00"}).json()["data"]
    assert second["deadline_states"][0]["escalated_once"] is True
    assert len(states["DEMO_001"]["audit_trail"]) == audit_count + 1
    assert states["DEMO_001"]["audit_trail"][-1]["at"] == "2026-05-07T12:00:00+08:00"
    assert states["DEMO_001"]["audit_trail"][-1]["action"] == "DEADLINE_MONITOR_CLOCK_ADVANCED"
    assert sum(item["action"] == "PROMISE_DEADLINE_ESCALATED" for item in states["DEMO_001"]["audit_trail"]) == 1


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
