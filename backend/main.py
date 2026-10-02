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

from backend.decision import decision_advisory_for
from backend.draft_review import assess_draft


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "frontend" / "src" / "api" / "examples"
FIXTURES = ROOT / "fixtures"
SERVICE_CLOCK = "2026-05-07T09:42:00+08:00"
logger = logging.getLogger("covenia.governance")

app = FastAPI(title="Covenia local API", version="0.8.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:4174",
        "http://localhost:5173",
        "http://localhost:4174",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-Id"],
)

states: dict[str, dict[str, Any]] = {}
analyses: dict[str, dict[str, Any]] = {}
analyzed_inputs: dict[str, dict[str, Any]] = {}
shipment_stages: dict[str, str] = {}
last_event_times: dict[str, datetime] = {}
idempotency: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
deadline_escalations: set[str] = set()


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


def service_time_for(case_id: str) -> str:
    baseline = parse_time(SERVICE_CLOCK)
    latest = last_event_times.get(case_id, baseline)
    return max(baseline, latest).isoformat()


def find_case(case_id: str) -> dict[str, Any] | None:
    source = next((item["case_input"] for item in DEMO_CASES if item["demo_case_id"] == case_id), None)
    return clone(source) if source is not None else None


def demo_case_ids() -> list[str]:
    return [item["demo_case_id"] for item in DEMO_CASES]


def demo_record(case_id: str) -> dict[str, Any] | None:
    return next((item for item in DEMO_CASES if item["demo_case_id"] == case_id), None)


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
    analyses[case_id] = clone(response)
    analyzed_inputs[case_id] = clone(case_input)
    shipment_stages.setdefault(case_id, "AWAITING_PICKUP")
    return response


def state_for(case_id: str, rid: str) -> dict[str, Any] | None:
    if case_id in states:
        return states[case_id]
    source = find_case(case_id)
    if source is None:
        return None
    first = (source.get("evidence_images") or [{}])[0]
    variant = first.get("declared_view_type") == "PACKAGE_CONTEXT" or "blur" in first.get("file_name", "").lower()
    return analyze(case_id, source, source.get("evaluation_time", SERVICE_CLOCK), rid, variant)["accountability_state"]


def analysis_for(case_id: str, rid: str) -> dict[str, Any] | None:
    if case_id in analyses:
        return analyses[case_id]
    source = find_case(case_id)
    if source is None:
        return None
    challenge_mode = case_id != "DEMO_001"
    return analyze(case_id, source, source.get("evaluation_time", SERVICE_CLOCK), rid, challenge_mode)


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
    draft_assessment = None
    draft_actions: list[str] = []
    if isinstance(body.get("draft_reply"), str):
        draft_assessment = assess_draft(body["draft_reply"])
        draft_actions = draft_assessment.pop("_detected_actions", [])
        action = "CHECK_REPLACEMENT_PROGRESS"
        if "EVIDENCE_REQUEST" in draft_actions:
            action = "ASK_EVIDENCE"
        if "CLOSE_CASE" in draft_actions:
            action = "CLOSE_CASE"
        elif draft_assessment["kind"] == "PROGRESS_UPDATE":
            action = "CHECK_PROGRESS"
        elif draft_assessment["kind"] == "NEW_COMMITMENT":
            action = "MAKE_COMMITMENT"
    requested_scope = body["prepared_action"].get("requested_scope")
    if draft_assessment is not None:
        requested_scope = state["current_scope"]
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
    draft_evidence_request = "EVIDENCE_REQUEST" in draft_actions
    draft_close = "CLOSE_CASE" in draft_actions
    e1 = (action == "ASK_EVIDENCE" or draft_evidence_request) and evidence_status == "VALID" and scope_match is True
    h1 = evidence_status == "NEED_HUMAN_REVIEW" or state["current_scope"]["issue_type"] == "ADVERSE_REACTION"
    p0 = (action == "CLOSE_CASE" or draft_close) and "CLOSE_BEFORE_RESOLUTION" in state["prohibited_actions"]
    if draft_assessment and draft_assessment["kind"] == "UNCLASSIFIED" and draft_actions:
        action = "+".join(draft_actions)
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
    result = {"case_id": state["case_id"], "decision": decision, "rule_id": rule_id, "rule_priority": priority, "accountability_state": clone(state),
            "challenge_mode": challenge_mode, "fact_trace": {"evidence_status": evidence_status, "prepared_action": action, "scope_match": scope_match, "active_promise_count": len(state["active_commitments"]), "suppressed_rule_ids": suppressed},
            "reason": {"P0_PROHIBITED_ACTION": "当前不能结案，已有未完成的服务责任。", "H1": "当前证据存在不确定性，需要人工复核。", "E1": "已有与当前范围一致的有效证据，不能重复索取。", "E2": "现有证据属于不同范围，可以补充当前范围所需材料。", "E0_NO_RULE_MATCHED": "当前动作未命中阻断规则。"}[rule_id],
            "resolution_path": resolution(state, candidate, rule_id), "runtime_metrics": {"input_tokens": 238, "output_tokens": 74, "inference_latency_ms": 36, "rule_substitution_count": 1}}
    if draft_assessment is not None:
        result["draft_assessment"] = draft_assessment
        if draft_assessment["requires_confirmation"]:
            result["resolution_path"]["requires_human_approval"] = True
            if draft_assessment["kind"] == "UNCLASSIFIED" and "NEW_COMMITMENT" not in draft_actions:
                result["resolution_path"]["creates_obligation"] = False
                result["resolution_path"]["compiled_service_responsibility"] = None
        elif draft_assessment["kind"] == "PROGRESS_UPDATE" and decision == "ALLOW":
            result["resolution_path"]["requires_human_approval"] = False
    return result


async def body_or_error(request: Request, rid: str) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        body = await request.json()
    except Exception:
        return None, error("SCHEMA_INVALID", "请求体必须是 JSON 对象。", rid, 400)
    if not isinstance(body, dict):
        return None, error("SCHEMA_INVALID", "请求体必须是 JSON 对象。", rid, 400)
    return body, None


def source_evidence(case_input: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for message in case_input.get("conversation", []):
        evidence.append({
            "source_id": message["message_id"],
            "source_type": "CHAT",
            "source_label": "聊天消息",
            "observed_at": message.get("timestamp"),
            "claim": message.get("text", ""),
            "field_path": "conversation[]",
            "confidence": 1,
            "derived_time": False,
        })
    for image in case_input.get("evidence_images", []):
        evidence.append({
            "source_id": image["evidence_id"],
            "source_type": "IMAGE",
            "source_label": image.get("file_name", "图片证据"),
            "observed_at": image.get("submitted_at"),
            "claim": f"{image.get('declared_view_type', 'OTHER')} evidence",
            "field_path": "evidence_images[]",
            "confidence": 1,
            "derived_time": False,
        })
    order = case_input.get("order", {})
    if order.get("order_id"):
        evidence.append({
            "source_id": order["order_id"],
            "source_type": "ORDER",
            "source_label": "订单",
            "observed_at": case_input.get("evaluation_time"),
            "claim": "订单与当前商品范围",
            "field_path": "order",
            "confidence": 1,
            "derived_time": True,
        })
    for ticket in case_input.get("service_tickets", []):
        evidence.append({
            "source_id": ticket["ticket_id"],
            "source_type": "TICKET",
            "source_label": ticket.get("source_sheet", "工单"),
            "observed_at": ticket.get("created_at"),
            "claim": f"{ticket.get('ticket_type')} · {ticket.get('status')}",
            "field_path": "service_tickets[]",
            "confidence": 1,
            "derived_time": False,
        })
    for audit in state.get("audit_trail", []):
        evidence.append({
            "source_id": audit["request_id"],
            "source_type": "SYSTEM_EVENT" if audit.get("actor") != "SIMULATOR" else "LOGISTICS",
            "source_label": audit.get("action", "审计事件"),
            "observed_at": audit.get("at"),
            "claim": "状态由服务端事件更新",
            "field_path": "accountability_state.audit_trail[]",
            "confidence": 1,
            "derived_time": False,
        })
    return evidence


def deadline_state_for(case_id: str, state: dict[str, Any]) -> dict[str, Any]:
    obligation = state.get("open_obligation") or {}
    commitment = state.get("active_commitments", [{}])[0] if state.get("active_commitments") else {}
    deadline = obligation.get("deadline") or commitment.get("deadline")
    next_check = obligation.get("next_check_at") or deadline
    now = parse_time(service_time_for(case_id))
    due = parse_time(deadline) if deadline else None
    if state.get("case_status") == "RESOLVED" or obligation.get("status") == "COMPLETED":
        status, monitor_status = "CLOSED", "CLOSED"
    elif state.get("case_status") == "AT_RISK" or obligation.get("status") == "AT_RISK":
        status, monitor_status = "ESCALATED", "RUNNING"
    elif due is not None and now >= due:
        status, monitor_status = "OVERDUE", "RUNNING"
    elif obligation or commitment:
        status, monitor_status = "SCHEDULED", "WAITING"
    else:
        status, monitor_status = "CLOSED", "CLOSED"
    return {
        "case_id": case_id,
        "promise_id": commitment.get("promise_type") or obligation.get("obligation_type") or "NO_ACTIVE_PROMISE",
        "status": status,
        "deadline": deadline or SERVICE_CLOCK,
        "next_check_at": next_check or SERVICE_CLOCK,
        "monitor_status": monitor_status,
        "escalated_once": case_id in deadline_escalations or status == "ESCALATED",
        "risk_state_id": f"RISK_{case_id}",
        "priority_state_id": f"PRIORITY_{case_id}",
        "audit_event_id": state.get("audit_trail", [{}])[-1].get("request_id") if state.get("audit_trail") else None,
    }


def effort_for(case_input: dict[str, Any]) -> dict[str, Any]:
    contact_count = len(case_input.get("conversation", []))
    image_count = len(case_input.get("evidence_images", []))
    score = min(100, 34 + contact_count * 8 + image_count * 6)
    level = "HIGH" if score >= 76 else "MEDIUM" if score >= 52 else "LOW"
    signals = []
    if contact_count >= 3:
        signals.append("多轮沟通")
    if image_count:
        signals.append("已经提交证据")
    if any("重新" in item.get("text", "") or "还要" in item.get("text", "") for item in case_input.get("conversation", [])):
        signals.append("重复说明压力")
    return {"score": score, "level": level, "signals": signals or ["单次沟通"]}


def risk_state_for(case_id: str, state: dict[str, Any], case_input: dict[str, Any]) -> dict[str, Any]:
    factors: list[dict[str, Any]] = []

    def add(factor_type: str, weight: int, reason: str, source_ids: list[str]) -> None:
        factors.append({"factor_type": factor_type, "weight": weight, "reason": reason, "source_evidence_ids": source_ids})

    facts = state.get("experience_gap_diagnosis", {}).get("traceable_service_facts", [])
    fact_sources = [source for fact in facts for source in fact.get("source_ids", [])]
    if state.get("case_status") == "AT_RISK":
        add("PROMISE_OVERDUE", 60, "服务承诺或物流节点已经进入风险状态。", fact_sources)
    if len(case_input.get("conversation", [])) >= 3:
        add("REPEAT_CONTACT", 18, "消费者已多轮沟通或二次进线。", [case_input["conversation"][-1]["message_id"]])
    if state.get("evidence_status") == "MISMATCHED":
        add("EVIDENCE_CONFLICT", 26, "证据与当前商品范围不一致。", [img["evidence_id"] for img in case_input.get("evidence_images", [])])
    if state.get("evidence_status") == "NEED_HUMAN_REVIEW":
        add("HUMAN_REVIEW_REQUIRED", 32, "证据不足以支持自动判断，需要人工复核。", [img["evidence_id"] for img in case_input.get("evidence_images", [])])
    if state.get("open_obligation") or state.get("active_commitments"):
        add("FULFILLMENT_STALLED", 24, "已有承诺或责任尚未完成，需要继续跟踪。", fact_sources)
    effort = effort_for(case_input)
    if effort["level"] == "HIGH":
        add("EFFORT_HIGH", 16, "消费者已经付出较高沟通和举证成本。", [msg["message_id"] for msg in case_input.get("conversation", [])[-2:]])
    score = 40 + sum(item["weight"] for item in factors)
    level = "CRITICAL" if score >= 120 else "HIGH" if score >= 92 else "MEDIUM" if score >= 64 else "LOW"
    return {
        "case_id": case_id,
        "score": min(score, 200),
        "level": level,
        "factors": factors,
        "prediction": False,
        "source_evidence_ids": sorted({source for item in factors for source in item["source_evidence_ids"]}),
    }


def customer_decision_for(case_id: str, state: dict[str, Any]) -> dict[str, Any]:
    prepared = demo_record(case_id).get("prepared_action") if demo_record(case_id) else None
    if not prepared:
        prepared = {"action_id": f"DECISION_{case_id}", "action_type": "ASK_EVIDENCE", "requested_scope": state["current_scope"], "requires_human_approval": False}
    decision = evaluate(state, {"case_id": case_id, "prepared_action": prepared})
    case_input = find_case(case_id) or {"conversation": [], "evidence_images": [], "service_tickets": [], "order": {}, "evaluation_time": SERVICE_CLOCK}
    advisory = decision_advisory_for(case_id, state, case_input, deadline_state_for(case_id, state), now=SERVICE_CLOCK)
    return {
        "case_id": case_id,
        "decision": decision["decision"],
        "reason": decision["reason"],
        "rule_id": decision["rule_id"],
        "jev_assessment_id": advisory["assessment_id"],
        "decision_advisory": advisory,
        "source_evidence_ids": decision["resolution_path"]["evidence_basis"],
        "next_action": decision["resolution_path"]["task_prefill"]["summary"],
        "human_review_required": decision["decision"] == "HUMAN_REVIEW" or decision["resolution_path"]["requires_human_approval"],
    }


def customer_state_for(case_id: str, rid: str) -> dict[str, Any] | None:
    analysis = analysis_for(case_id, rid)
    if analysis is None:
        return None
    state = states.get(case_id, analysis["accountability_state"])
    case_input = analyzed_inputs.get(case_id) or find_case(case_id) or {"conversation": [], "evidence_images": [], "service_tickets": [], "order": {}, "evaluation_time": SERVICE_CLOCK}
    journey = analysis["extracted_journey"]
    source = source_evidence(case_input, state)
    risk = risk_state_for(case_id, state, case_input)
    deadline = deadline_state_for(case_id, state)
    prepared = demo_record(case_id).get("prepared_action") if demo_record(case_id) else None
    prepared = prepared or {"action_id": f"STATE_{case_id}", "action_type": "CHECK_PROGRESS", "requested_scope": state["current_scope"]}
    lightweight_decision = evaluate(state, {"case_id": case_id, "prepared_action": prepared})
    advisory = decision_advisory_for(case_id, state, case_input, deadline, now=service_time_for(case_id))
    probability = advisory["emotion"]["probability"]
    trend = advisory["emotion"]["trend"]
    next_action = lightweight_decision["resolution_path"]["task_prefill"]["summary"]
    if state.get("case_status") == "RESOLVED":
        next_action = "服务已完成，保留回执供消费者查看。"
        guidance = "先确认处理已经完成，再提供服务回执，无需消费者继续操作。"
    elif state["evidence_status"] == "MISMATCHED":
        guidance = "说明已有图片覆盖的商品范围，仅补充当前问题缺少的证据。"
    elif state["evidence_status"] == "NEED_HUMAN_REVIEW":
        guidance = "先说明已收到图片并安排人工复核，不直接要求重复上传。"
    else:
        guidance = "先承认已收到材料，再说明品牌侧的下一步处理与更新时间。"
    if trend == "WORSENING":
        guidance = "先回应消费者已经付出的沟通成本，避免要求重复解释。" + guidance
    facts = [
        {"fact_id": f"FACT_{index+1}", "statement": fact["statement"], "source_evidence_ids": fact.get("source_ids", [])}
        for index, fact in enumerate(state.get("experience_gap_diagnosis", {}).get("traceable_service_facts", []))
    ]
    if not facts:
        facts.append({"fact_id": "FACT_SCOPE", "statement": "已恢复订单、商品和当前问题范围。", "source_evidence_ids": [case_input.get("order", {}).get("order_id", case_id)]})
    evidence_known = [fact["statement"] for fact in state.get("experience_gap_diagnosis", {}).get("traceable_service_facts", [])]
    missing = []
    if state.get("evidence_status") == "MISMATCHED":
        missing.append("当前正装粉底液泵头近照。")
    elif state.get("evidence_status") == "NEED_HUMAN_REVIEW":
        missing.append("人工复核结论。")
    return {
        "case_id": case_id,
        "service_clock": service_time_for(case_id),
        "facts": facts,
        "evidence": {
            "status": state["evidence_status"],
            "known": evidence_known or ["已恢复当前服务上下文。"],
            "missing": missing or ["暂无待消费者补充证据。"],
            "do_not_ask_again": ["不要再次索取相同破损图片"] if state["evidence_status"] == "VALID" else ["不要要求消费者重复解释历史问题"],
        },
        "intent": {
            "current_goal": journey["journey_understanding"]["consumer_intent"],
            "constraints": [state["experience_gap_diagnosis"]["latent_need"]],
            "accepted_solutions": ["由品牌继续核实并主动更新"],
            "rejected_solutions": state.get("prohibited_actions", []),
            "source_evidence_ids": journey["journey_understanding"].get("source_ids", []),
        },
        "emotion": {
            "current_label": "UNKNOWN",
            "trend": trend,
            "cause": journey["journey_understanding"]["service_cause"],
            "communication_guidance": guidance,
            "source_evidence_ids": [item["source_id"] for item in source if item["source_type"] == "CHAT"],
            "confidence": max(probability, 1 - probability) if probability is not None and trend != "UNKNOWN" else 0,
            "probability": probability,
            "risk_scoring_allowed": False,
        },
        "effort": effort_for(case_input),
        "actions": {
            "next_best_action": next_action,
            "blocked_actions": state.get("prohibited_actions", []),
            "allowed_actions": ["CHECK_REPLACEMENT_PROGRESS", "CREATE_FOLLOW_UP_TASK"],
            "human_review_actions": ["HUMAN_EVIDENCE_REVIEW"] if state.get("evidence_status") == "NEED_HUMAN_REVIEW" else [],
        },
        "promises": {
            "active": [item["raw_text"] for item in state.get("active_commitments", [])],
            "deadline_state": deadline,
        },
        "risk": risk,
        "decision": {"case_id": case_id, "decision": lightweight_decision["decision"], "reason": lightweight_decision["reason"], "rule_id": lightweight_decision["rule_id"], "jev_assessment_id": advisory.get("assessment_id"), "decision_advisory": advisory, "source_evidence_ids": lightweight_decision["resolution_path"]["evidence_basis"], "next_action": next_action, "human_review_required": lightweight_decision["decision"] == "HUMAN_REVIEW" or lightweight_decision["resolution_path"]["requires_human_approval"]},
        "decision_advisory": advisory,
        "resolution": {
            "status": "RESOLVED" if state.get("case_status") == "RESOLVED" else "AT_RISK" if state.get("case_status") == "AT_RISK" else "IN_PROGRESS" if state.get("open_obligation") else "DRAFTED",
            "current_path": state.get("experience_gap_diagnosis", {}).get("reply_strategy", "先恢复事实，再决定动作。"),
            "consumer_reply_draft": (state.get("service_progress_receipt") or {}).get("brand_action", state.get("experience_gap_diagnosis", {}).get("reply_strategy", "")),
            "service_progress_receipt_id": (state.get("service_progress_receipt") or {}).get("receipt_id"),
        },
        "source_evidence": source,
    }


def priority_states(rid: str) -> list[dict[str, Any]]:
    rows = []
    for case_id in demo_case_ids():
        state = state_for(case_id, rid)
        case_input = find_case(case_id)
        if state is None or case_input is None:
            continue
        if state.get("case_status") == "RESOLVED":
            continue
        risk = risk_state_for(case_id, state, case_input)
        deadline = deadline_state_for(case_id, state)
        score = risk["score"] + (25 if deadline["status"] in ("OVERDUE", "ESCALATED") else 0)
        band = "RED" if score >= 120 else "ORANGE" if score >= 92 else "YELLOW" if score >= 64 else "NORMAL"
        rows.append({
            "case_id": case_id,
            "rank": 0,
            "band": band,
            "priority_score": score,
            "queue_reasons": [factor["reason"] for factor in risk["factors"][:3]] or ["当前无高风险信号"],
            "next_best_action": evaluate(state, {"case_id": case_id, "prepared_action": (demo_record(case_id) or {}).get("prepared_action") or {"action_type": "CHECK_PROGRESS", "requested_scope": state["current_scope"]}})["resolution_path"]["task_prefill"]["summary"],
        })
    rows.sort(key=lambda item: item["priority_score"], reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def emerging_issues(rid: str) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for case_id in demo_case_ids():
        case_input = find_case(case_id)
        if not case_input:
            continue
        issue = case_input["current_issue"]
        key = (issue["sku_id"], issue.get("affected_component", "UNKNOWN"), issue["issue_type"])
        bucket = buckets.setdefault(key, {"case_ids": [], "source_ids": []})
        bucket["case_ids"].append(case_id)
        bucket["source_ids"].extend([msg["message_id"] for msg in case_input.get("conversation", [])[:1]])
    result = []
    for index, ((sku_id, component, issue_type), bucket) in enumerate(buckets.items(), start=1):
        count = len(set(bucket["case_ids"]))
        result.append({
            "issue_id": f"EMERGING_{index:03d}",
            "fingerprint": {"sku_id": sku_id, "affected_component": component, "issue_type": issue_type},
            "window": {"started_at": "2026-05-05T00:00:00+08:00", "ended_at": SERVICE_CLOCK},
            "independent_consumer_count": count,
            "status": "EMERGING_CANDIDATE" if count >= 3 else "WATCHING",
            "requires_human_confirmation": True,
            "prediction": False,
            "source_evidence_ids": bucket["source_ids"],
        })
    return result


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
    if case_id in states and case_id in analyses and analyzed_inputs.get(case_id) == case_input:
        data = clone(analyses[case_id])
        data["accountability_state"] = clone(states[case_id])
    else:
        data = analyze(case_id, case_input, evaluation_time, rid, challenge_mode)
    data["risk_state"] = risk_state_for(case_id, data["accountability_state"], case_input)
    data["deadline_state"] = deadline_state_for(case_id, data["accountability_state"])
    data["customer_state"] = customer_state_for(case_id, rid)
    return envelope(data, rid)


@app.get("/api/customer-state/{case_id}")
async def get_customer_state_by_path(case_id: str, request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_CUSTOMER_STATE")
    state = customer_state_for(case_id, rid)
    if state is None:
        return error("VALIDATION_ERROR", "未找到案例事实。", rid, 400)
    return envelope(state, rid)


@app.get("/api/customer-state")
async def get_customer_state(case_id: str, request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_CUSTOMER_STATE")
    state = customer_state_for(case_id, rid)
    if state is None:
        return error("VALIDATION_ERROR", "未找到案例事实。", rid, 400)
    return envelope(state, rid)


@app.get("/api/risk")
async def get_risk(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_RISK")
    rows = []
    for case_id in demo_case_ids():
        state = state_for(case_id, rid)
        case_input = find_case(case_id)
        if state is not None and case_input is not None:
            rows.append(risk_state_for(case_id, state, case_input))
    rows.sort(key=lambda item: item["score"], reverse=True)
    return envelope(rows, rid)


@app.get("/api/priority")
async def get_priority(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_PRIORITY")
    return envelope(priority_states(rid), rid)


@app.get("/api/emerging-issues")
async def get_emerging_issues(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_EMERGING")
    return envelope(emerging_issues(rid), rid)


@app.get("/api/deadlines")
async def get_deadlines(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_DEADLINES")
    rows = []
    for case_id in demo_case_ids():
        state = state_for(case_id, rid)
        if state is not None:
            rows.append(deadline_state_for(case_id, state))
    return envelope(rows, rid)


@app.post("/api/deadlines/run")
async def run_deadline_monitor(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_DEADLINE_RUN")
    body, problem = await body_or_error(request, rid)
    if problem:
        return problem
    case_ids = body.get("case_ids") if isinstance(body.get("case_ids"), list) else demo_case_ids()
    updated: list[dict[str, Any]] = []
    for case_id in case_ids:
        if not isinstance(case_id, str):
            continue
        state = state_for(case_id, rid)
        if state is None:
            continue
        deadline = deadline_state_for(case_id, state)
        if state.get("open_obligation") and deadline["status"] == "SCHEDULED":
            due = parse_time(deadline["deadline"])
            now = parse_time(body.get("now") or SERVICE_CLOCK)
            if now >= due and case_id not in deadline_escalations:
                changed = clone(state)
                changed["case_status"] = "AT_RISK"
                changed["experience_risk"] = "HIGH"
                if changed.get("open_obligation"):
                    changed["open_obligation"]["status"] = "AT_RISK"
                changed["active_commitments"] = [
                    {**commitment, "status": "AT_RISK"}
                    for commitment in changed.get("active_commitments", [])
                ]
                changed["audit_trail"] = [*changed.get("audit_trail", []), {
                    "at": body.get("now") or SERVICE_CLOCK,
                    "actor": "DEADLINE_MONITOR",
                    "action": "PROMISE_DEADLINE_ESCALATED",
                    "changed_fields": ["case_status", "open_obligation", "active_commitments"],
                    "request_id": rid,
                }]
                states[case_id] = changed
                deadline_escalations.add(case_id)
                state = changed
        updated.append(deadline_state_for(case_id, state))
    return envelope({"deadline_states": updated, "escalated_case_ids": sorted(deadline_escalations)}, rid)


@app.post("/api/decisions")
async def create_decision(request: Request) -> JSONResponse:
    rid = request_id(request, "REQ_DECISION")
    body, problem = await body_or_error(request, rid)
    if problem:
        return problem
    if not isinstance(body.get("case_id"), str):
        return error("SCHEMA_INVALID", "case_id 为必填字段。", rid, 400)
    state = state_for(body["case_id"], rid)
    if state is None:
        return error("VALIDATION_ERROR", "未找到案例事实。", rid, 400)
    if isinstance(body.get("prepared_action"), dict):
        full = evaluate(state, body)
        case_input = find_case(body["case_id"]) or {"conversation": [], "evidence_images": [], "service_tickets": [], "order": {}, "evaluation_time": SERVICE_CLOCK}
        advisory = decision_advisory_for(body["case_id"], state, case_input, deadline_state_for(body["case_id"], state), now=SERVICE_CLOCK)
        data = {
            "case_id": full["case_id"],
            "decision": full["decision"],
            "reason": full["reason"],
            "rule_id": full["rule_id"],
            "jev_assessment_id": advisory["assessment_id"],
            "decision_advisory": advisory,
            "source_evidence_ids": full["resolution_path"]["evidence_basis"],
            "next_action": full["resolution_path"]["task_prefill"]["summary"],
            "human_review_required": full["decision"] == "HUMAN_REVIEW" or full["resolution_path"]["requires_human_approval"],
            "decision_result": full,
        }
    else:
        data = customer_decision_for(body["case_id"], state)
    return envelope(data, rid)


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
    if "draft_reply" in body and (not isinstance(body["draft_reply"], str) or not body["draft_reply"].strip() or len(body["draft_reply"]) > 5000):
        return error("SCHEMA_INVALID", "draft_reply 必须是 1 到 5000 字符的非空文本。", rid, 400)
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
    edits = body["human_edits"]
    if "consumer_reply" in edits and (not isinstance(edits["consumer_reply"], str) or not edits["consumer_reply"].strip() or len(edits["consumer_reply"]) > 5000):
        return error("SCHEMA_INVALID", "consumer_reply 必须是 1 到 5000 字符的非空文本。", rid, 400)
    if "executor" in edits and edits["executor"] not in ("BRAND", "WAREHOUSE", "LOGISTICS_PROVIDER"):
        return error("SCHEMA_INVALID", "executor 不在允许范围。", rid, 400)
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
    draft = edits.get("consumer_reply", approved["consumer_reply_draft"])
    draft_review = assess_draft(draft)
    guard = evaluate(state, {"prepared_action": {"action_type": "CHECK_REPLACEMENT_PROGRESS", "requested_scope": state["current_scope"]}, "draft_reply": draft})
    if guard["decision"] == "INTERVENE":
        return error("P0_PROHIBITED_ACTION", guard["reason"], rid, 409)
    if re.search(r"退款|退钱|原路退", draft):
        return error("VALIDATION_ERROR", "当前演示不支持批准退款承诺。", rid, 409)
    if re.search(r"(保证|承诺|一定|确保|最晚|将|会).{0,16}(换货|补发|重新发货|送达)", draft):
        return error("VALIDATION_ERROR", "当前演示不支持新增换货或送达保证，请确认查询进度的回复。", rid, 409)
    if "next_check_at" in edits:
        try:
            edited_time = parse_time(edits["next_check_at"])
            if edited_time.tzinfo is None or edited_time <= parse_time(service_time_for(body["case_id"])):
                raise ValueError
        except (TypeError, ValueError):
            return error("VALIDATION_ERROR", "下次更新时间必须带时区且晚于当前服务时间。", rid, 400)
    if "NEW_COMMITMENT" in draft_review.get("_detected_actions", []) and not edits.get("next_check_at"):
        return error("VALIDATION_ERROR", "新的更新时间承诺需要填写下次更新时间。", rid, 400)
    if edits.get("executor"):
        approved["executor"] = edits["executor"]
    if candidate == "ASK_CURRENT_SCOPE_EVIDENCE":
        if state.get("evidence_status") == "VALID":
            return error("VALIDATION_ERROR", "已有有效证据，不能批准重复索取材料。", rid, 409)
    if candidate in ("ASK_CURRENT_SCOPE_EVIDENCE", "HUMAN_EVIDENCE_REVIEW"):
        edits = body["human_edits"]
        if edits.get("executor"):
            approved["executor"] = edits["executor"]
        if edits.get("consumer_reply"):
            approved["consumer_reply_draft"] = edits["consumer_reply"]
        updated = clone(state)
        audit = {"at": SERVICE_CLOCK, "actor": body["approver_id"].strip(), "action": "RESOLUTION_APPROVED", "changed_fields": sorted(edits.keys()), "request_id": rid}
        updated["audit_trail"] = [*updated.get("audit_trail", []), audit]
        states[body["case_id"]] = updated
        data = {"accountability_state": updated, "approved_resolution": approved, "audit_trail": updated["audit_trail"]}
        response = {"data": data, "error": None, "request_id": rid}
        idempotency[key] = (fingerprint, response)
        return JSONResponse(response)
    if draft_review["kind"] == "UNCLASSIFIED" and "NEW_COMMITMENT" not in draft_review.get("_detected_actions", []):
        approved.update({"consumer_reply_draft": draft, "creates_obligation": False, "compiled_service_responsibility": None, "requires_human_approval": True})
        updated = clone(state)
        audit = {"at": SERVICE_CLOCK, "actor": body["approver_id"].strip(), "action": "RESOLUTION_APPROVED", "changed_fields": sorted(edits.keys()), "request_id": rid}
        updated["audit_trail"] = [*updated.get("audit_trail", []), audit]
        states[body["case_id"]] = updated
        data = {"accountability_state": updated, "approved_resolution": approved, "audit_trail": updated["audit_trail"]}
        response = {"data": data, "error": None, "request_id": rid}
        idempotency[key] = (fingerprint, response)
        return JSONResponse(response)
    valid_commitments = [c for c in state.get("active_commitments", []) if c.get("deadline")]
    deadline = (state.get("open_obligation") or {}).get("deadline") or (valid_commitments[0]["deadline"] if valid_commitments else None)
    next_check = edits.get("next_check_at")
    existing_obligation = state.get("open_obligation") or {}
    prior_replacement_promise = any(re.search(r"换货|补发|重新发货", str(item.get("raw_text", ""))) for item in valid_commitments)
    if existing_obligation.get("obligation_type") != "REPLACEMENT_FULFILLMENT" and not prior_replacement_promise:
        return error("VALIDATION_ERROR", "没有既有换货履约承诺，不能创建新的换货义务。", rid, 409)
    if not deadline:
        return error("VALIDATION_ERROR", "没有有效的既有承诺或义务，不能新建换货履约期限。", rid, 409)
    draft_kind = draft_review["kind"]
    if not next_check and draft_kind == "NEW_COMMITMENT":
        return error("VALIDATION_ERROR", "批准新的进度更新时间承诺必须提供 next_check_at。", rid, 400)
    next_check = next_check or (approved.get("compiled_service_responsibility") or {}).get("next_check_at")
    if not next_check:
        return error("VALIDATION_ERROR", "请填写下次更新时间。", rid, 400)
    try:
        next_dt = parse_time(next_check)
        service_dt = parse_time(service_time_for(body["case_id"]))
        if next_dt.tzinfo is None or next_dt <= service_dt:
            raise ValueError
    except (TypeError, ValueError):
        return error("VALIDATION_ERROR", "next_check_at 必须带时区且晚于服务时钟。", rid, 400)
    recovery = edits.get("recovery_if_missed") or "若仍未确认揽收，品牌将升级催办并主动通知新的处理时间。"
    updated = clone(state)
    updated.update({"case_status": "IN_FULFILLMENT", "open_obligation": {"obligation_type": "REPLACEMENT_FULFILLMENT", "status": "ON_TRACK", "accountable_side": "BRAND", "executor": approved["executor"], "deadline": deadline, "next_check_at": next_check, "milestone": "AWAITING_CARRIER_PICKUP", "resolution_condition": "REPLACEMENT_DELIVERED"},
                    "service_progress_receipt": {"receipt_id": f"RECEIPT_{body['case_id']}_001", "status": "ACTIVE", "received_evidence": ["粉底液泵头损坏图片", "订单和商品货号", "换货工单"], "brand_action": draft, "latest_update_at": SERVICE_CLOCK, "next_update_by": next_check, "consumer_action_required": False, "recovery_if_missed": recovery}})
    approved["consumer_reply_draft"] = draft
    compiled = approved.get("compiled_service_responsibility")
    if compiled is not None:
        compiled.update({"deadline": deadline, "next_check_at": next_check, "recovery_if_missed": recovery})
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
    if kind == "SHIPMENT_NOT_PICKED_UP" and stage != "AWAITING_PICKUP":
        return error("INVALID_EVENT_TRANSITION", "物流已揽收，不能再登记为未揽收。", rid, 409)
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
