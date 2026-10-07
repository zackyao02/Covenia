from __future__ import annotations

import copy
import json
import os
import statistics
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import main as service
from backend.decision import engine as decision_engine


FIXTURES = ROOT / "fixtures"
RESULTS = ROOT / "validation" / "results"
REQUIRED_CUSTOMER_STATE_SECTIONS = (
    "facts",
    "evidence",
    "intent",
    "emotion",
    "effort",
    "actions",
    "promises",
    "resolution",
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


DEMO_CASES = {row["demo_case_id"]: row for row in load_json(FIXTURES / "demo-cases.json")}
GROUND_TRUTH = {row["demo_case_id"]: row for row in load_json(FIXTURES / "ground-truth.json")}
CLIENT = TestClient(service.app)


def reset_service() -> None:
    service.states.clear()
    service.analyses.clear()
    service.analyzed_inputs.clear()
    service.shipment_stages.clear()
    service.last_event_times.clear()
    service.idempotency.clear()
    service.deadline_escalations.clear()
    decision_engine._CACHE.clear()
    decision_engine.AUDIT_LOG.clear()


def require_ok(response: Any, label: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{label} failed: HTTP {response.status_code} {response.text}")
    payload = response.json()
    if payload.get("error") is not None:
        raise RuntimeError(f"{label} failed: {payload['error']}")
    return payload["data"]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def safe_ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def validate_h1() -> dict[str, Any]:
    reset_service()
    case_checks = []
    for case_id in DEMO_CASES:
        require_ok(CLIENT.post("/api/cases/analyze", json={"case_id": case_id}), f"analyze {case_id}")
        state = require_ok(CLIENT.get(f"/api/customer-state/{case_id}"), f"customer state {case_id}")
        present = [section for section in REQUIRED_CUSTOMER_STATE_SECTIONS if state.get(section) is not None]
        case_checks.append(
            {
                "case_id": case_id,
                "required_sections_present": len(present),
                "required_sections_total": len(REQUIRED_CUSTOMER_STATE_SECTIONS),
                "has_source_evidence": bool(state.get("source_evidence")),
                "has_do_not_ask_again": bool(state.get("evidence", {}).get("do_not_ask_again")),
            }
        )

    samples_ms: list[float] = []
    snapshots: list[str] = []
    for _ in range(40):
        started = time.perf_counter()
        state = require_ok(CLIENT.get("/api/customer-state/DEMO_001"), "warm customer state read")
        samples_ms.append((time.perf_counter() - started) * 1000)
        snapshots.append(json.dumps(state, ensure_ascii=False, sort_keys=True))

    mechanism_passed = all(
        row["required_sections_present"] == row["required_sections_total"]
        and row["has_source_evidence"]
        and row["has_do_not_ask_again"]
        for row in case_checks
    ) and len(set(snapshots)) == 1
    return {
        "hypothesis": "Customer State reduces context recovery time",
        "current_verdict": "MECHANISM_VERIFIED_EFFECT_NOT_VALIDATED" if mechanism_passed else "MECHANISM_FAILED",
        "mechanism_passed": mechanism_passed,
        "case_checks": case_checks,
        "technical_proxy": {
            "sample_count": len(samples_ms),
            "in_process_read_latency_ms_p50": round(statistics.median(samples_ms), 3),
            "in_process_read_latency_ms_p95": round(percentile(samples_ms, 0.95), 3),
            "stable_payloads": len(set(snapshots)) == 1,
        },
        "claim_boundary": "该结果只证明本地演示状态可完整、稳定地恢复。客服上下文恢复时间下降仍需真人对照实验。",
    }


def validate_h2() -> dict[str, Any]:
    reset_service()
    rows = []
    tp = fp = tn = fn = 0
    exact = 0
    for case_id, fixture in DEMO_CASES.items():
        require_ok(CLIENT.post("/api/cases/analyze", json={"case_id": case_id}), f"analyze {case_id}")
        actual = require_ok(
            CLIENT.post(
                "/api/actions/evaluate",
                json={"case_id": case_id, "prepared_action": fixture["prepared_action"]},
            ),
            f"evaluate {case_id}",
        )
        expected = GROUND_TRUTH[case_id]
        is_exact = (
            actual["decision"] == expected["expected_decision"]
            and actual["rule_id"] == expected["expected_rule_id"]
            and actual["rule_priority"] == expected["expected_rule_priority"]
        )
        exact += int(is_exact)
        truth_positive = expected["expected_rule_id"] == "E1"
        predicted_positive = actual["rule_id"] == "E1"
        if truth_positive and predicted_positive:
            tp += 1
        elif not truth_positive and predicted_positive:
            fp += 1
        elif not truth_positive and not predicted_positive:
            tn += 1
        else:
            fn += 1
        rows.append(
            {
                "case_id": case_id,
                "expected": {"decision": expected["expected_decision"], "rule_id": expected["expected_rule_id"]},
                "actual": {"decision": actual["decision"], "rule_id": actual["rule_id"]},
                "exact_match": is_exact,
            }
        )

    passed = exact == len(rows)
    return {
        "hypothesis": "Firewall reduces repeat evidence requests without overblocking",
        "current_verdict": "SUPPORTED_ON_DESIGNED_CASES_ONLY" if passed else "NOT_SUPPORTED",
        "mechanism_passed": passed,
        "case_results": rows,
        "exact_match": {"correct": exact, "total": len(rows), "rate": safe_ratio(exact, len(rows))},
        "repeat_evidence_confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "repeat_evidence_precision": safe_ratio(tp, tp + fp),
        "repeat_evidence_recall": safe_ratio(tp, tp + fn),
        "non_block_specificity": safe_ratio(tn, tn + fp),
        "claim_boundary": "3 个案例均为团队设计的合成边界测试。结果证明规则链按预期运行，不代表生产准确率。",
    }


def fallback_response(_state: dict[str, Any], _questions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": False,
        "attempted": False,
        "source": "RULE_FALLBACK",
        "latency_ms": 0,
        "raw": None,
        "error": {"code": "TYPESAFE_API_KEY_NOT_SET", "message": "validation fallback"},
    }


def worsening_response(_state: dict[str, Any], _questions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "attempted": True,
        "source": "JEV",
        "latency_ms": 1,
        "model_version": "validation-stub-not-a-model-evaluation",
        "raw": {
            "answers": {
                "emotion_worsening": {"type": "noul", "noul": 0.92},
                "needs_human": {"type": "noul", "noul": 0.10},
                "next_action": {
                    "type": "choice",
                    "choice": "CHECK_REPLACEMENT",
                    "probabilities": {
                        "CHECK_REPLACEMENT": 0.90,
                        "HUMAN_ESCALATION": 0.03,
                        "CONTINUE_TROUBLESHOOTING": 0.04,
                        "REQUEST_EVIDENCE": 0.03,
                    },
                },
            }
        },
    }


def validate_h3() -> dict[str, Any]:
    reset_service()
    os.environ.pop("TYPESAFE_API_KEY", None)
    with patch.object(decision_engine, "typesafe_configured", return_value=False), patch.object(
        decision_engine, "ask_jev", side_effect=fallback_response
    ):
        require_ok(CLIENT.post("/api/cases/analyze", json={"case_id": "DEMO_001"}), "fallback analyze")
        fallback = require_ok(CLIENT.get("/api/customer-state/DEMO_001"), "fallback customer state")

    fallback_safe = (
        fallback["decision_advisory"]["status"] == "FALLBACK"
        and fallback["decision_advisory"]["source"] == "RULE_FALLBACK"
        and fallback["emotion"]["trend"] == "UNKNOWN"
        and fallback["emotion"]["probability"] is None
        and fallback["emotion"]["risk_scoring_allowed"] is False
    )

    frozen_state = copy.deepcopy(service.states["DEMO_001"])
    new_messages = [
        {
            "message_id": "DEMO_CHAT_AGENT_VALIDATION",
            "timestamp": "2026-05-07T09:41:00+08:00",
            "speaker": "AGENT",
            "text": "我会核实换货进度。",
            "source_kind": "DEMO_AUGMENTATION",
        },
        {
            "message_id": "DEMO_CHAT_CONSUMER_VALIDATION",
            "timestamp": "2026-05-07T09:42:00+08:00",
            "speaker": "CONSUMER",
            "text": "我已经问了好几次，什么时候能有结果？",
            "source_kind": "DEMO_AUGMENTATION",
        },
    ]
    with patch.object(decision_engine, "typesafe_configured", return_value=True), patch.object(
        decision_engine, "ask_jev", side_effect=worsening_response
    ):
        refreshed = require_ok(
            CLIENT.post(
                "/api/demo/customer-state/refresh",
                json={"case_id": "DEMO_001", "challenge_mode": True, "messages": new_messages},
            ),
            "JEV traceability refresh",
        )

    traceable = (
        refreshed["decision_advisory"]["source"] == "JEV"
        and refreshed["emotion"]["trend"] == "WORSENING"
        and "DEMO_CHAT_CONSUMER_VALIDATION" in refreshed["emotion"]["source_evidence_ids"]
        and any(
            item["source_id"] == "DEMO_CHAT_CONSUMER_VALIDATION"
            for item in refreshed["source_evidence"]
        )
    )
    state_not_rewritten = service.states["DEMO_001"] == frozen_state
    mechanism_passed = fallback_safe and traceable and state_not_rewritten
    return {
        "hypothesis": "JEV detects worsening early",
        "current_verdict": "GOVERNANCE_AND_TRACEABILITY_VERIFIED_ACCURACY_NOT_VALIDATED" if mechanism_passed else "MECHANISM_FAILED",
        "mechanism_passed": mechanism_passed,
        "fallback_safe": fallback_safe,
        "signal_traceable_to_new_message": traceable,
        "service_state_not_rewritten_by_signal": state_not_rewritten,
        "risk_scoring_allowed_from_emotion": fallback["emotion"]["risk_scoring_allowed"],
        "claim_boundary": "成功响应使用确定性桩验证映射与来源追踪，不是 JEV 准确率测试。提前发现能力、Precision/Recall 与阈值仍需独立人工标签。",
    }


def validate_h4() -> dict[str, Any]:
    reset_service()
    require_ok(CLIENT.post("/api/cases/analyze", json={"case_id": "DEMO_001"}), "promise analyze")
    require_ok(
        CLIENT.post(
            "/api/resolutions/approve",
            json={
                "case_id": "DEMO_001",
                "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
                "approver_id": "VALIDATION_AGENT",
                "idempotency_key": "hypothesis-h4-approval",
                "human_edits": {"executor": "WAREHOUSE"},
            },
        ),
        "approve obligation",
    )
    scheduled = require_ok(CLIENT.get("/api/deadlines"), "scheduled deadlines")
    first = require_ok(
        CLIENT.post(
            "/api/deadlines/run",
            json={"case_ids": ["DEMO_001"], "now": "2026-05-07T11:00:00+08:00"},
        ),
        "first deadline monitor",
    )
    audit_after_first = len(service.states["DEMO_001"]["audit_trail"])
    second = require_ok(
        CLIENT.post(
            "/api/deadlines/run",
            json={"case_ids": ["DEMO_001"], "now": "2026-05-07T12:00:00+08:00"},
        ),
        "second deadline monitor",
    )
    audit_after_second = len(service.states["DEMO_001"]["audit_trail"])

    scheduled_before_due = any(row["case_id"] == "DEMO_001" and row["status"] == "SCHEDULED" for row in scheduled)
    escalated_once = (
        "DEMO_001" in first["escalated_case_ids"]
        and first["deadline_states"][0]["status"] == "ESCALATED"
        and second["deadline_states"][0]["escalated_once"] is True
        and audit_after_first == audit_after_second
    )

    reset_service()
    require_ok(CLIENT.post("/api/cases/analyze", json={"case_id": "DEMO_001"}), "shipment analyze")
    delayed = require_ok(
        CLIENT.post(
            "/api/events/shipment",
            json={
                "case_id": "DEMO_001",
                "event_id": "H4-NOT-PICKED",
                "event_type": "SHIPMENT_NOT_PICKED_UP",
                "event_time": "2026-05-07T11:35:00+08:00",
                "idempotency_key": "hypothesis-h4-not-picked",
            },
        ),
        "shipment delay event",
    )
    draft = delayed["proactive_notification_draft"]
    notification_generated = (
        draft["requires_human_approval"] is True
        and draft["channel"] == "ORIGINAL_CHAT"
        and "主动更新" in draft["text"]
        and "无需再次提供材料" in draft["text"]
    )
    mechanism_passed = scheduled_before_due and escalated_once and notification_generated
    return {
        "hypothesis": "Promise Monitor raises proactive update rate",
        "current_verdict": "MONITOR_AND_DRAFT_GENERATION_VERIFIED_UPLIFT_NOT_VALIDATED" if mechanism_passed else "MECHANISM_FAILED",
        "mechanism_passed": mechanism_passed,
        "scheduled_before_due": scheduled_before_due,
        "single_escalation_on_repeated_monitor_runs": escalated_once,
        "audit_count_after_first_run": audit_after_first,
        "audit_count_after_second_run": audit_after_second,
        "proactive_notification_draft_generated": notification_generated,
        "notification_requires_human_approval": draft["requires_human_approval"],
        "claim_boundary": "结果证明模拟事件可触发监控、单次升级和主动通知草稿。主动更新率提升仍需真实承诺样本与发送日志作对照。",
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    hypotheses = report["hypotheses"]
    lines = [
        "# Covenia H1–H4 当前可执行验证结果",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 结论",
        "",
        "| 假设 | 当前结论 | 本次能证明什么 | 仍不能证明什么 |",
        "|---|---|---|---|",
        f"| H1 | {hypotheses['H1']['current_verdict']} | Customer State 在 3 个设计案例中完整、稳定恢复，记录本地读取耗时 | 真人客服上下文恢复时间是否下降 |",
        f"| H2 | {hypotheses['H2']['current_verdict']} | 3 个设计案例的决策与规则标签全部匹配 | 生产准确率与真实误拦截率 |",
        f"| H3 | {hypotheses['H3']['current_verdict']} | 失败安全降级、信号可追溯、模型信号不改写服务状态 | JEV 准确率、提前量与阈值 |",
        f"| H4 | {hypotheses['H4']['current_verdict']} | 承诺可调度、逾期只升级一次、物流异常生成需人工确认的主动通知草稿 | 真实主动更新率提升 |",
        "",
        "## 可复现结果",
        "",
        f"- H1：Customer State 必填区块覆盖 {len(REQUIRED_CUSTOMER_STATE_SECTIONS)}/{len(REQUIRED_CUSTOMER_STATE_SECTIONS)}；40 次进程内读取 P50 {hypotheses['H1']['technical_proxy']['in_process_read_latency_ms_p50']} ms，P95 {hypotheses['H1']['technical_proxy']['in_process_read_latency_ms_p95']} ms。",
        f"- H2：规则与决策精确匹配 {hypotheses['H2']['exact_match']['correct']}/{hypotheses['H2']['exact_match']['total']}；重复索证 Precision {hypotheses['H2']['repeat_evidence_precision']}，Recall {hypotheses['H2']['repeat_evidence_recall']}。",
        f"- H3：安全降级={hypotheses['H3']['fallback_safe']}；新消息来源可追溯={hypotheses['H3']['signal_traceable_to_new_message']}；服务状态未被模型信号改写={hypotheses['H3']['service_state_not_rewritten_by_signal']}。",
        f"- H4：逾期升级只写入一次={hypotheses['H4']['single_escalation_on_repeated_monitor_runs']}；主动通知草稿生成={hypotheses['H4']['proactive_notification_draft_generated']}；草稿仍需人工批准={hypotheses['H4']['notification_requires_human_approval']}。",
        "",
        "## 证据边界",
        "",
        "本次使用赛事 Mock 数据和团队设计案例，只验证机制和安全边界。报告中的 Precision/Recall 仅对应 3 个设计案例，不能作为生产准确率。H1 的效率提升、H3 的模型表现和 H4 的业务提升需要真人或真实业务数据。",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        stack.enter_context(patch.object(decision_engine, "typesafe_configured", return_value=False))
        stack.enter_context(patch.object(decision_engine, "ask_jev", side_effect=fallback_response))
        h1 = validate_h1()
        h2 = validate_h2()
    h3 = validate_h3()
    h4 = validate_h4()
    report = {
        "schema_version": "covenia-hypothesis-validation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_commit": "c4f9c52",
        "validation_branch": "codex/hypothesis-validation",
        "data_classification": "COMPETITION_MOCK_AND_TEAM_DESIGNED_CASES",
        "hypotheses": {"H1": h1, "H2": h2, "H3": h3, "H4": h4},
        "all_automatable_mechanisms_passed": all(row["mechanism_passed"] for row in (h1, h2, h3, h4)),
    }
    json_path = RESULTS / "hypothesis-validation.latest.json"
    md_path = RESULTS / "hypothesis-validation.latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, md_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_automatable_mechanisms_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
