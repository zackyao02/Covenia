"""辅助调度器 · BATCH-22 第二轮独立验收：适配器边界自建探针

独立性声明：
  · 不 import 实现方的 backend/tests/api/test_evaluate.py，不使用其内部辅助函数；
  · 不引用上一轮验收者的 independent_probe.py；
  · 仅依赖 BATCH-22 的公开接口（create_evaluate_router）与冻结 schema 语义；
  · 用自造替身服务驱动路由端点，验证传输层契约 —— HTTP 状态、信封形状、
    P0 不得落进成功体、弃用客户端字段不得被采信。

用法：<RUN_DIR>/venv/Scripts/python.exe reports/batches/BATCH-22/verification-evidence/round-2/aux_adapter_probe.py
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from types import SimpleNamespace

from covenia_b.api.base import ApiError
from covenia_b.api.evaluate import create_evaluate_router  # noqa: F401  (imported for existence check)
from covenia_b.domain.validation import ContractValidationError
from covenia_b.rules import ProhibitedActionError
from covenia_b.services.evaluate import EvaluateNotAnalyzed

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print("%-4s %-58s %s" % ("PASS" if ok else "FAIL", name, detail))


class _FakeRequest:
    def __init__(self, request_id: str) -> None:
        self.state = SimpleNamespace(request_id=request_id)


class _FakeResult:
    def to_contract(self):
        return {
            "decision": "ALLOW",
            "rule_id": "E0_NO_RULE_MATCHED",
            "experience_risk": "LOW",
            "action_impacts": [],
            "fact_trace": {"evidence_status": "VALID"},
        }


class _OkService:
    """最小替身：记录收到的已解析请求，返回一个 E0 成功结果。"""

    def __init__(self) -> None:
        self.seen: list[object] = []

    def evaluate_with_trace(self, parsed, *, request_id=None):
        self.seen.append(parsed)
        return SimpleNamespace(result=_FakeResult(), request_id=request_id, evidence=None)


class _P0Service:
    def evaluate_with_trace(self, parsed, *, request_id=None):
        raise ProhibitedActionError(
            SimpleNamespace(rule_id="P0_PROHIBITED_ACTION", reason="prohibited action present")
        )


class _NotAnalyzedService:
    def evaluate_with_trace(self, parsed, *, request_id=None):
        raise EvaluateNotAnalyzed("case must be analysed first", request_id=request_id)


BODY_OK = {
    "case_id": "case-aux-001",
    "prepared_action": {
        "action_id": "act-aux-1",
        "action_type": "CHECK_REPLACEMENT_PROGRESS",
        "requires_human_approval": False,
    },
}


def endpoint_for(service):
    return create_evaluate_router(service).routes[0].endpoint


def call(service, body, request_id="aux-rid-0001"):
    ep = endpoint_for(service)
    return asyncio.run(ep(_FakeRequest(request_id), body))


def main() -> int:
    print("== BATCH-22 适配器边界自建探针 ==")

    # 1) 成功路径：200 + {data, error: None, request_id}
    svc = _OkService()
    resp = call(svc, BODY_OK, "aux-rid-0001")
    body = json.loads(resp.body)
    check("成功路径 HTTP 200", resp.status_code == 200, "status=%s" % resp.status_code)
    check("成功信封 error 为 None", body.get("error") is None, json.dumps(body.get("error")))
    check("成功信封 data 为服务端结果", (body.get("data") or {}).get("rule_id") == "E0_NO_RULE_MATCHED")
    check("成功信封回带 request_id", body.get("request_id") == "aux-rid-0001", str(body.get("request_id")))

    # 2) 弃用的客户端字段不得被采信
    svc2 = _OkService()
    poisoned = dict(BODY_OK)
    poisoned.update(
        {
            "accountability_state": {"decision": "INTERVENE", "rule_id": "P0_PROHIBITED_ACTION"},
            "prohibited_actions": [],
            "current_scope": {"order_id": "forged"},
            "evidence_status": "VALID",
        }
    )
    resp2 = call(svc2, poisoned, "aux-rid-0002")
    parsed = svc2.seen[0]
    check("伪造客户端状态仍返回成功（服务端为准）", resp2.status_code == 200)
    check(
        "弃用字段被保留（冻结 schema 声明的兼容语义，非缺陷）",
        getattr(parsed, "accountability_state", "missing") == poisoned["accountability_state"],
        "accountability_state=%r" % (getattr(parsed, "accountability_state", "missing"),),
    )

    # 2b) 关键政策：保留 ≠ 采信。静态核验服务端从不读取请求侧的弃用状态字段。
    from covenia_b.services import evaluate as _evaluate_module

    _src = open(inspect.getsourcefile(_evaluate_module), encoding="utf-8").read()
    _forbidden_reads = [
        "request.accountability_state",
        "parsed.accountability_state",
        "request.prohibited_actions",
        "parsed.prohibited_actions",
        "request.current_scope",
        "parsed.current_scope",
        "request.evidence_status",
        "request.active_commitments",
    ]
    _hit = [t for t in _forbidden_reads if t in _src]
    check(
        "服务端不读取请求侧弃用字段（保留但不采信）",
        not _hit,
        "services/evaluate.py 命中读取: %s" % (_hit or "无"),
    )

    # 3) P0：必须走 400 错误信封，不得落进成功体
    try:
        call(_P0Service(), BODY_OK, "aux-rid-0003")
        check("P0 抛出 ApiError", False, "未抛出任何异常")
    except ApiError as err:
        payload = err.as_payload("aux-rid-0003")
        check("P0 HTTP 状态为 400", err.status_code == 400, "status=%s" % err.status_code)
        check("P0 错误码为 P0_PROHIBITED_ACTION", err.code == "P0_PROHIBITED_ACTION", err.code)
        check("P0 信封 data 为 None（不在成功体）", payload.get("data") is None)
        check("P0 信封 error.code 非空", bool((payload.get("error") or {}).get("code")))

    # 4) 未分析：不得凭空造事实，应映射为 422 VALIDATION_ERROR
    try:
        call(_NotAnalyzedService(), BODY_OK, "aux-rid-0004")
        check("未分析路径抛 ApiError", False, "未抛出任何异常")
    except ApiError as err:
        check("未分析映射为 422", err.status_code == 422, "status=%s" % err.status_code)
        check("未分析错误码为 VALIDATION_ERROR", err.code == "VALIDATION_ERROR", err.code)

    # 5) schema 非法：缺 prepared_action 必须被拒
    try:
        call(_OkService(), {"case_id": "case-aux-001"}, "aux-rid-0005")
        check("非法请求被拒", False, "未抛出任何异常")
    except ApiError as err:
        check("非法请求映射为 422 SCHEMA_INVALID", err.status_code == 422 and err.code == "SCHEMA_INVALID",
              "status=%s code=%s" % (err.status_code, err.code))
    except ContractValidationError:
        check("非法请求映射为 422 SCHEMA_INVALID", False, "未包成 ApiError，直接抛出 ContractValidationError")

    failed = [r for r in RESULTS if not r[1]]
    print("\n合计 %d 项，失败 %d 项" % (len(RESULTS), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
