from fastapi.testclient import TestClient

from backend.main import app, idempotency, last_event_times, redact_for_model, shipment_stages, states


client = TestClient(app)


def reset_service() -> None:
    states.clear()
    shipment_stages.clear()
    last_event_times.clear()
    idempotency.clear()


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


def test_redacts_pii_before_the_extractor_receives_case_text() -> None:
    case = {"conversation": [{"text": "请寄到地址：上海市徐汇区，联系电话 13800138000；我有不良反应。"}]}
    redacted, count = redact_for_model(case)
    assert count >= 3
    assert "13800138000" not in redacted["conversation"][0]["text"]
    assert "[已脱敏]" in redacted["conversation"][0]["text"]
    assert "13800138000" in case["conversation"][0]["text"]
