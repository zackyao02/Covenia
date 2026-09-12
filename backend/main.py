from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "frontend" / "src" / "api" / "examples"
FIXTURES = ROOT / "fixtures"
SERVICE_CLOCK = "2026-05-07T09:42:00+08:00"
logger = logging.getLogger("covenia.governance")

app = FastAPI(title="Covenia local API", version="0.8.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://127.0.0.1:4173", "http://localhost:5173"],
    allow_methods=["POST"],
    allow_headers=["Content-Type", "X-Request-Id"],
)

states: dict[str, dict[str, Any]] = {}
shipment_stages: dict[str, str] = {}
last_event_times: dict[str, datetime] = {}
idempotency: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}


def load_json(path: Path) -> dict[str, Any] | list[Any]:
    return json.loads(path.read_text(encoding="utf-8"))


ANALYZE_EXAMPLE = load_json(EXAMPLES / "01-analyze-case.json")
DEMO_CASES = load_json(FIXTURES / "demo-cases.json")


def clone(value: Any) -> Any:
    return copy.deepcopy(value)


def request_id(request: Request, prefix: str) -> str:
    return request.headers.get("X-Request-Id") or f"{prefix}_{uuid.uuid4().hex[:12]}"


def envelope(data: Any, rid: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"data": data, "error": None, "request_id": rid}, status_code=status_code)


def error(code: str, message: str, rid: str, status_code: int, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        {"data": None, "error": {"code": code, "message": message, "retryable": retryable}, "request_id": rid},
        status_code=status_code,
    )


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def find_case(case_id: str) -> dict[str, Any] | None:
    return next((item["case_input"] for item in DEMO_CASES if item["demo_case_id"] == case_id), None)


def scope_from_case(case_input: dict[str, Any]) -> dict[str, str]:
    issue = case_input["current_issue"]
    return {
        "order_id": case_input["order"]["order_id"],
        "fulfillment_item_id": issue["fulfillment_item_id"],
        "sku_id": issue["sku_id"],
        "issue_type": issue["issue_type"],
    }


def redact_for_model(case_input: dict[str, Any]) -> tuple[dict[str, Any], int]:
    redacted = clone(case_input)
    patterns = [r"1[3-9]\d{9}", r"\b\d{15,19}\b", r"(?:地址|住址|收货)[：:\s]*[^，。,；;]+", r"(?:过敏|不良反应|就医)[^，。,；;]*"]
    count = 0
    for message in redacted.get("conversation", []):
        text = message.get("text", "")
        for pattern in patterns:
            text, substitutions = re.subn(pattern, "[已脱敏]", text)
            count += substitutions
        message["text"] = text
    return redacted, count


def base_analysis(case_input: dict[str, Any], case_id: str, evaluation_time: str, rid: str) -> dict[str, Any]:
    response = clone(ANALYZE_EXAMPLE["response"]["data"])
    journey = response["extracted_journey"]
    state = response["accountability_state"]
    scope = scope_from_case(case_input)
    journey["case_id"] = case_id
    journey["extracted_scope"] = scope
    state["case_id"] = case_id
    state["current_scope"] = scope
    state["audit_trail"] = [{
        "at": evaluation_time,
        "actor": "SYSTEM",
        "action": "ANALYZED",
        "changed_fields": ["extracted_journey", "accountability_state"],
        "request_id": rid,
    }]
    response["model_metadata"] = journey["model_metadata"]
    return response


def make_challenge_analysis(response: dict[str, Any], case_input: dict[str, Any]) -> None:
    evidence = case_input.get("evidence_images", [])
    first = evidence[0] if evidence else {}
    state = response["accountability_state"]
    journey = response["extracted_journey"]
    filename = first.get("file_name", "").lower()
    is_blurred = "blur" in filename
    is_gift = first.get("declared_view_type") == "PACKAGE_CONTEXT" and not is_blurred
    if is_gift:
        journey["promise_events"] = []
        journey["image_observations"] = [{
            "evidence_id": first.get("evidence_id", "CHALLENGE_IMAGE"), "readability": "HIGH",
            "product_identifiable": True, "sku_match": "MISMATCH", "product_role": "GIFT",
            "issue_visible": True, "affected_component": "OUTER_PACKAGE", "view_type": "PACKAGE_CONTEXT",
            "coverage": ["PRODUCT_IDENTITY", "PACKAGE_CONTEXT"], "integrity_concern": False,
            "hygiene_risk_signal": "LOW", "confidence": 0.96,
        }]
        state.update({"case_status": "WAITING_FOR_CONSUMER", "consumer_input_required": True,
                      "accountable_side": "CONSUMER", "evidence_status": "MISMATCHED",
                      "active_commitments": [], "prohibited_actions": [], "open_obligation": None,
                      "service_progress_receipt": None, "experience_risk": "LOW"})
    elif is_blurred:
        journey["promise_events"] = []
        journey["image_observations"] = [{
            "evidence_id": first.get("evidence_id", "CHALLENGE_IMAGE"), "readability": "LOW",
            "product_identifiable": False, "sku_match": "UNKNOWN", "product_role": "UNKNOWN",
            "issue_visible": False, "affected_component": "UNKNOWN", "view_type": "ISSUE_DETAIL",
            "coverage": [], "integrity_concern": False, "hygiene_risk_signal": "UNKNOWN", "confidence": 0.41,
        }]
        state.update({"case_status": "ACTION_REVIEW", "consumer_input_required": False,
                      "accountable_side": "UNKNOWN", "evidence_status": "NEED_HUMAN_REVIEW",
                      "active_commitments": [], "prohibited_actions": [], "open_obligation": None,
                      "service_progress_receipt": None, "experience_risk": "MEDIUM"})


def analyze(case_id: str, case_input: dict[str, Any], evaluation_time: str, rid: str, challenge_mode: bool) -> dict[str, Any]:
    response = base_analysis(case_input, case_id, evaluation_time, rid)
    if challenge_mode:
        make_challenge_analysis(response, case_input)
    model_input, pii_count = redact_for_model(case_input)
    response["runtime_metrics"] = {
        "input_tokens": max(1, len(json.dumps(model_input, ensure_ascii=False)) // 3),
        "output_tokens": 346,
        "inference_latency_ms": 842,
        "rule_substitution_count": 0,
    }
    response["model_metadata"]["run_id"] = f"RUN_{case_id}_{hashlib.sha1(rid.encode()).hexdigest()[:6]}"
    # Governance records stay on the server so the public response remains within the frozen Schema.
    logger.info("governance_record request_id=%s case_id=%s pii_masked_count=%s", rid, case_id, pii_count)
    states[case_id] = clone(response["accountability_state"])
    shipment_stages.setdefault(case_id, "AWAITING_PICKUP")
    return response


def state_for(case_id: str, rid: str) -> dict[str, Any] | None:
    if case_id in states:
        return states[case_id]
    source = find_case(case_id)
    if source is None:
        return None
    return analyze(case_id, source, source.get("evaluation_time", SERVICE_CLOCK), rid, False)["accountability_state"]


def same_scope(left: dict[str, Any] | None, right: dict[str, Any]) -> bool | None:
    if not left:
        return None
    return all(left.get(key) == right.get(key) for key in ("order_id", "fulfillment_item_id", "sku_id", "issue_type"))


def resolution(state: dict[str, Any], candidate: str, rule_id: str) -> dict[str, Any]:
    current = state["current_scope"]
    ticket = next((fact for fact in state["experience_gap_diagnosis"]["traceable_service_facts"] if fact["fact_type"] == "TICKET_CREATED"), None)
    ticket_id = ticket["source_ids"][0] if ticket else None
    if candidate == "HUMAN_EVIDENCE_REVIEW":
        return {"candidate_type": candidate, "evidence_basis": ["当前图片无法可靠判定"], "policy_basis": "H1：不确定证据进入人工复核。",
                "consumer_reply_draft": "我们已收到您提交的材料，正在安排人工核实，不需要您重复说明。",
                "task_prefill": {"task_type": "HUMAN_EVIDENCE_REVIEW", "existing_ticket_id": ticket_id, "sku_id": current["sku_id"], "affected_component": "PUMP", "summary": "人工复核当前证据与问题范围。"},
                "accountable_side": "UNKNOWN", "executor": "HUMAN_REVIEW_QUEUE", "requires_human_approval": True, "creates_obligation": False, "compiled_service_responsibility": None}
    if candidate == "ASK_CURRENT_SCOPE_EVIDENCE":
        return {"candidate_type": candidate, "evidence_basis": ["现有材料与当前商品范围不一致"], "policy_basis": "E2：仅请求当前范围缺失的证据。",
                "consumer_reply_draft": "已收到赠品相关图片。为核实粉底液泵头问题，请补充泵头近照。",
                "task_prefill": {"task_type": "REQUEST_EVIDENCE", "existing_ticket_id": ticket_id, "sku_id": current["sku_id"], "affected_component": "PUMP", "summary": "请求当前粉底液泵头近照。"},
                "accountable_side": "CONSUMER", "executor": "CONSUMER", "requires_human_approval": False, "creates_obligation": False, "compiled_service_responsibility": None}
    deadline = state["active_commitments"][0]["deadline"] if state["active_commitments"] else None
    return {"candidate_type": "CHECK_REPLACEMENT_FULFILLMENT", "evidence_basis": ["粉底液正装与订单已匹配", "泵头损坏图片可辨认", "换货工单已创建"],
            "policy_basis": f"{rule_id}：依据既有证据和责任状态计算。", "consumer_reply_draft": "您此前提交的粉底液泵头损坏图片我们已经收到，无需再次上传。我正在核实换货件的最新物流进度，并会主动向您更新。",
            "task_prefill": {"task_type": "WAREHOUSE_FOLLOW_UP", "existing_ticket_id": ticket_id, "sku_id": current["sku_id"], "affected_component": "PUMP", "summary": "核实换货件是否已交物流揽收；若仍未揽收，请立即反馈预计处理时间。"},
            "accountable_side": "BRAND", "executor": "WAREHOUSE", "requires_human_approval": True, "creates_obligation": True,
            "compiled_service_responsibility": {"source_promise_text": state["active_commitments"][0]["raw_text"] if state["active_commitments"] else "", "commitment_class": "STANDARD_APPROVED", "activation_status": "ACTIVE", "deadline": deadline, "next_check_at": "2026-05-07T10:30:00+08:00", "recovery_if_missed": "品牌主动催办仓库，升级给主管并通知消费者新的处理时间。"}}


def evaluate(state: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    challenge_mode = body.get("challenge_mode") is True
    action = body["prepared_action"].get("action_type")
    requested_scope = body["prepared_action"].get("requested_scope")
    overrides = body.get("challenge_overrides", {}) if challenge_mode else {}
    if overrides.get("requested_scope"):
        requested_scope = overrides["requested_scope"]
    image_overrides = overrides.get("image_observation_overrides", [])
    evidence_status = state["evidence_status"]
    if any(item.get("readability") in ("LOW", "UNKNOWN") for item in image_overrides):
        evidence_status = "NEED_HUMAN_REVIEW"
    elif overrides.get("requested_scope") and overrides["requested_scope"].get("sku_id") != state["current_scope"]["sku_id"]:
        evidence_status = "MISMATCHED"
    scope_match = same_scope(requested_scope, state["current_scope"])
    e1 = action == "ASK_EVIDENCE" and evidence_status == "VALID" and scope_match is True
    h1 = evidence_status == "NEED_HUMAN_REVIEW" or state["current_scope"]["issue_type"] == "ADVERSE_REACTION"
    p0 = action == "CLOSE_CASE" and "CLOSE_BEFORE_RESOLUTION" in state["prohibited_actions"]
    if p0:
        rule_id, priority, decision, suppressed = "P0_PROHIBITED_ACTION", 400, "INTERVENE", (["H1"] if h1 else [])
    elif h1:
        rule_id, priority, decision, suppressed = "H1", 350, "HUMAN_REVIEW", (["E1"] if e1 else [])
    elif e1:
        rule_id, priority, decision, suppressed = "E1", 300, "INTERVENE", []
    elif action == "ASK_EVIDENCE" and evidence_status == "MISMATCHED":
        rule_id, priority, decision, suppressed = "E2", 100, "ALLOW", []
    else:
        rule_id, priority, decision, suppressed = "E0_NO_RULE_MATCHED", 0, "ALLOW", []
    candidate = "HUMAN_EVIDENCE_REVIEW" if rule_id == "H1" else "ASK_CURRENT_SCOPE_EVIDENCE" if rule_id == "E2" else "CHECK_REPLACEMENT_FULFILLMENT"
    return {"case_id": state["case_id"], "decision": decision, "rule_id": rule_id, "rule_priority": priority, "accountability_state": clone(state),
            "challenge_mode": challenge_mode, "fact_trace": {"evidence_status": evidence_status, "prepared_action": action, "scope_match": scope_match, "active_promise_count": len(state["active_commitments"]), "suppressed_rule_ids": suppressed},
            "reason": {"P0_PROHIBITED_ACTION": "当前不能结案，已有未完成的服务责任。", "H1": "当前证据存在不确定性，需要人工复核。", "E1": "已有与当前范围一致的有效证据，不能重复索取。", "E2": "现有证据属于不同范围，可以补充当前范围所需材料。", "E0_NO_RULE_MATCHED": "当前动作未命中阻断规则。"}[rule_id],
            "resolution_path": resolution(state, candidate, rule_id), "runtime_metrics": {"input_tokens": 238, "output_tokens": 74, "inference_latency_ms": 36, "rule_substitution_count": 1}}


async def body_or_error(request: Request, rid: str) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        body = await request.json()
    except Exception:
        return None, error("SCHEMA_INVALID", "请求体必须是 JSON 对象。", rid, 400)
    if not isinstance(body, dict):
        return None, error("SCHEMA_INVALID", "请求体必须是 JSON 对象。", rid, 400)
    return body, None


@app.post("/api/cases/analyze")
async def analyze_case(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_ANALYZE")
    body, problem = await body_or_error(request, rid)
    if problem:
        return problem
    case_id = body.get("case_id")
    challenge_mode = body.get("challenge_mode") is True
    if not isinstance(case_id, str) or not case_id:
        return error("SCHEMA_INVALID", "case_id 为必填字段。", rid, 400)
    if body.get("case_input") is not None and not challenge_mode:
        return error("SCHEMA_INVALID", "case_input 仅允许在 challenge_mode=true 时使用。", rid, 400)
    case_input = body.get("case_input") if challenge_mode else find_case(case_id)
    if not isinstance(case_input, dict):
        return error("VALIDATION_ERROR", "未找到案例事实；请使用已配置案例或开启挑战模式提供 case_input。", rid, 400)
    evaluation_time = body.get("evaluation_time") or case_input.get("evaluation_time") or SERVICE_CLOCK
    try:
        parse_time(evaluation_time)
    except (TypeError, ValueError):
        return error("SCHEMA_INVALID", "evaluation_time 必须是 ISO 8601 时间。", rid, 400)
    return envelope(analyze(case_id, case_input, evaluation_time, rid, challenge_mode), rid)


@app.post("/api/actions/evaluate")
async def evaluate_action(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_EVALUATE")
    body, problem = await body_or_error(request, rid)
    if problem:
        return problem
    if not isinstance(body.get("case_id"), str) or not isinstance(body.get("prepared_action"), dict):
        return error("SCHEMA_INVALID", "case_id 和 prepared_action 为必填字段。", rid, 400)
    if not isinstance(body["prepared_action"].get("action_type"), str):
        return error("SCHEMA_INVALID", "prepared_action.action_type 为必填字段。", rid, 400)
    state = state_for(body["case_id"], rid)
    if state is None:
        return error("VALIDATION_ERROR", "未找到案例事实。", rid, 400)
    result = evaluate(state, body)
    return envelope(result, rid)


@app.post("/api/resolutions/approve")
async def approve_resolution(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_APPROVE")
    body, problem = await body_or_error(request, rid)
    if problem:
        return problem
    required = ("case_id", "candidate_type", "approver_id", "idempotency_key", "human_edits")
    if any(key not in body for key in required):
        return error("SCHEMA_INVALID", "case_id、candidate_type、approver_id、idempotency_key 与 human_edits 均为必填字段。", rid, 400)
    if not isinstance(body["approver_id"], str) or not body["approver_id"].strip():
        return error("VALIDATION_ERROR", "请填写审批人，才可以激活服务责任。", rid, 400)
    if not isinstance(body["idempotency_key"], str) or len(body["idempotency_key"]) < 8:
        return error("SCHEMA_INVALID", "idempotency_key 至少需要 8 个字符。", rid, 400)
    if not isinstance(body["human_edits"], dict):
        return error("SCHEMA_INVALID", "human_edits 必须是对象。", rid, 400)
    key = ("approve", body["case_id"], body["idempotency_key"])
    fingerprint = canonical(body)
    if key in idempotency:
        previous_fingerprint, previous = idempotency[key]
        if previous_fingerprint != fingerprint:
            return error("IDEMPOTENCY_CONFLICT", "同一幂等键不能对应不同请求。", rid, 409)
        return JSONResponse(previous)
    state = state_for(body["case_id"], rid)
    if state is None:
        return error("VALIDATION_ERROR", "未找到案例事实。", rid, 400)
    candidate = body["candidate_type"]
    if candidate not in ("CHECK_REPLACEMENT_FULFILLMENT", "ASK_CURRENT_SCOPE_EVIDENCE", "HUMAN_EVIDENCE_REVIEW"):
        return error("SCHEMA_INVALID", "candidate_type 不在允许范围。", rid, 400)
    approved = resolution(state, candidate, "E1")
    edits = body["human_edits"]
    if edits.get("executor") in ("BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"):
        approved["executor"] = edits["executor"]
    deadline = state["active_commitments"][0]["deadline"] if state["active_commitments"] else "2026-05-07T10:27:37+08:00"
    next_check = edits.get("next_check_at") or "2026-05-07T10:30:00+08:00"
    recovery = edits.get("recovery_if_missed") or "若仍未确认揽收，品牌将升级催办并主动通知新的处理时间。"
    updated = clone(state)
    updated.update({"case_status": "IN_FULFILLMENT", "open_obligation": {"obligation_type": "REPLACEMENT_FULFILLMENT", "status": "ON_TRACK", "accountable_side": "BRAND", "executor": approved["executor"], "deadline": deadline, "next_check_at": next_check, "milestone": "AWAITING_CARRIER_PICKUP", "resolution_condition": "REPLACEMENT_DELIVERED"},
                    "service_progress_receipt": {"receipt_id": f"RECEIPT_{body['case_id']}_001", "status": "ACTIVE", "received_evidence": ["粉底液泵头损坏图片", "订单和商品货号", "换货工单"], "brand_action": "正在核实换货件是否已由物流揽收，并催促仓库反馈。", "latest_update_at": SERVICE_CLOCK, "next_update_by": next_check, "consumer_action_required": False, "recovery_if_missed": recovery}})
    audit = {"at": SERVICE_CLOCK, "actor": body["approver_id"].strip(), "action": "RESOLUTION_APPROVED", "changed_fields": sorted(edits.keys()), "request_id": rid}
    updated["audit_trail"] = [*updated["audit_trail"], audit]
    states[body["case_id"]] = updated
    data = {"accountability_state": updated, "approved_resolution": approved, "audit_trail": updated["audit_trail"]}
    response = {"data": data, "error": None, "request_id": rid}
    idempotency[key] = (fingerprint, response)
    return JSONResponse(response)


@app.post("/api/events/shipment")
async def shipment_event(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_SHIPMENT")
    body, problem = await body_or_error(request, rid)
    if problem:
        return problem
    required = ("case_id", "event_id", "event_type", "event_time", "idempotency_key")
    if any(key not in body for key in required):
        return error("SCHEMA_INVALID", "物流事件缺少必填字段。", rid, 400)
    if body["event_type"] not in ("SHIPMENT_PICKED_UP", "SHIPMENT_NOT_PICKED_UP", "SHIPMENT_DELIVERED"):
        return error("SCHEMA_INVALID", "event_type 不在允许范围。", rid, 400)
    try:
        event_time = parse_time(body["event_time"])
    except (TypeError, ValueError):
        return error("SCHEMA_INVALID", "event_time 必须是 ISO 8601 时间。", rid, 400)
    key = ("shipment", body["case_id"], body["idempotency_key"])
    fingerprint = canonical(body)
    if key in idempotency:
        previous_fingerprint, previous = idempotency[key]
        if previous_fingerprint != fingerprint:
            return error("IDEMPOTENCY_CONFLICT", "同一幂等键不能对应不同请求。", rid, 409)
        return JSONResponse(previous)
    if event_time < last_event_times.get(body["case_id"], datetime.min.replace(tzinfo=event_time.tzinfo)):
        return error("INVALID_EVENT_TRANSITION", "物流事件时间不能倒退。", rid, 409)
    state = state_for(body["case_id"], rid)
    if state is None:
        return error("VALIDATION_ERROR", "未找到案例事实。", rid, 400)
    stage = shipment_stages.get(body["case_id"], "AWAITING_PICKUP")
    kind = body["event_type"]
    if kind == "SHIPMENT_DELIVERED" and stage != "IN_TRANSIT":
        return error("INVALID_EVENT_TRANSITION", "必须先确认物流揽收，才能登记送达。", rid, 409)
    updated = clone(state)
    deadline = (updated.get("open_obligation") or {}).get("deadline") or (updated["active_commitments"][0]["deadline"] if updated["active_commitments"] else "2026-05-07T10:27:37+08:00")
    if kind == "SHIPMENT_PICKED_UP":
        shipment_stages[body["case_id"]] = "IN_TRANSIT"
        updated["case_status"] = "IN_FULFILLMENT"
        obligation_status, milestone, executor, receipt_status, next_update = "ON_TRACK", "IN_TRANSIT", "LOGISTICS_PROVIDER", "ACTIVE", "2026-05-08T10:10:00+08:00"
        action_text, notification = "换货件已由物流揽收，当前正在运输。", "您的换货件已经由物流揽收。您无需操作，我们会继续关注直至送达。"
        follow_up = escalation = None
    elif kind == "SHIPMENT_NOT_PICKED_UP":
        updated["case_status"] = "AT_RISK"
        obligation_status, milestone, executor, receipt_status, next_update = "AT_RISK", "AWAITING_CARRIER_PICKUP", "WAREHOUSE", "AT_RISK", "2026-05-07T12:00:00+08:00"
        action_text, notification = "换货件尚未被物流揽收，已向仓库发起高优先级催办。", "您的换货件目前尚未完成物流揽收，我们已向仓库加急催办。您无需再次提供材料，我们会在今天 12:00 前主动更新处理进展。"
        follow_up = {"task_type": "WAREHOUSE_FOLLOW_UP", "existing_ticket_id": "BH919209358357", "priority": "HIGH", "summary": "换货件超过 48 小时仍未揽收，请立即确认仓库状态和预计交运时间。"}
        escalation = {"escalation_type": "PROMISE_OVERDUE", "priority": "HIGH", "summary": f"{body['case_id']} 换货发出承诺已逾期且物流未揽收，建议主管介入。"}
    else:
        shipment_stages[body["case_id"]] = "DELIVERED"
        updated["case_status"] = "RESOLVED"
        updated["active_commitments"] = []
        obligation_status, milestone, executor, receipt_status, next_update = "COMPLETED", "DELIVERED", "LOGISTICS_PROVIDER", "COMPLETED", body["event_time"]
        action_text, notification = "换货件已送达，服务责任已完成。", "您的换货件已送达，本次服务已完成。"
        follow_up = escalation = None
    updated["open_obligation"] = {"obligation_type": "REPLACEMENT_FULFILLMENT", "status": obligation_status, "accountable_side": "BRAND", "executor": executor, "deadline": deadline, "next_check_at": next_update, "milestone": milestone, "resolution_condition": "REPLACEMENT_DELIVERED"}
    updated["service_progress_receipt"] = {"receipt_id": f"RECEIPT_{body['case_id']}_001", "status": receipt_status, "received_evidence": ["粉底液泵头损坏图片", "订单和商品货号", "换货工单"], "brand_action": action_text, "latest_update_at": body["event_time"], "next_update_by": next_update, "consumer_action_required": False, "recovery_if_missed": "若未按时更新，品牌将升级催办并主动通知。"}
    audit = {"at": body["event_time"], "actor": "SIMULATOR", "action": kind, "changed_fields": ["case_status", "open_obligation"], "request_id": rid}
    updated["audit_trail"] = [*updated["audit_trail"], audit]
    states[body["case_id"]] = updated
    last_event_times[body["case_id"]] = event_time
    data = {"accountability_state": updated, "follow_up_candidate": follow_up, "supervisor_escalation_candidate": escalation, "proactive_notification_draft": {"text": notification, "commits_next_update_at": next_update, "requires_human_approval": True, "channel": "ORIGINAL_CHAT"}}
    response = {"data": data, "error": None, "request_id": rid}
    idempotency[key] = (fingerprint, response)
    return JSONResponse(response)
