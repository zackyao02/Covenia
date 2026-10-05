# -*- coding: utf-8 -*-
"""审查方独立探针 BATCH-26：真实 SQLite 账本 + 真实服务，不使用实现方测试文件。"""
import inspect, json, os, shutil, sys
sys.path.insert(0, r'C:\a26\v\backend\src')
sys.stdout.reconfigure(encoding='utf-8')
from covenia_b.domain.types import AccountabilityState, LedgerSnapshot, CompiledCommitments, ShipmentEventRequest
from covenia_b.storage import SQLiteLedgerRepository
from covenia_b.services.shipment import ShipmentEventService
print("=== ShipmentEventRequest 字段 ===")
for n, f in ShipmentEventRequest.model_fields.items():
    print("   %-22s %s" % (n, str(f.annotation)[:60]))

DEADLINE="2030-01-01T10:00:00+00:00"; NEXT="2030-01-01T10:05:00+00:00"
CASE="CASE-PROBE-26"
def state(c):
    return AccountabilityState.model_validate({
        "case_id": c, "case_status": "IN_FULFILLMENT", "consumer_input_required": False,
        "accountable_side": "BRAND", "evidence_status": "VALID",
        "current_scope": {"order_id": "O-"+c, "fulfillment_item_id": "I-"+c, "sku_id": "S-"+c, "issue_type": "PACKAGE_DAMAGE"},
        "active_commitments": [{"promise_type":"REPLACEMENT_FULFILLMENT","raw_text":"A replacement will be dispatched.","status":"ACTIVE","deadline":DEADLINE,"source_ids":["SRC-"+c]}],
        "prohibited_actions": ["SHIFT_FOLLOW_UP_TO_CONSUMER","CLOSE_BEFORE_RESOLUTION"],
        "experience_gap_diagnosis": {"consumer_expression":"A promised progress update is pending.","traceable_service_facts":[{"fact_type":"PROMISE_ACTIVE","statement":"pending","source_ids":["SRC-"+c]},{"fact_type":"TICKET_CREATED","statement":"ticket","source_ids":["T-"+c]}],"deterioration_cause":"pending","latent_need":"update","responsibility_judgment":{"consumer_input_complete":True,"accountable_side":"BRAND"},"action_impacts":["START_PROACTIVE_UPDATE"],"reply_strategy":"draft"},
        "open_obligation": {"obligation_type":"REPLACEMENT_FULFILLMENT","status":"ON_TRACK","accountable_side":"BRAND","executor":"WAREHOUSE","deadline":DEADLINE,"next_check_at":NEXT,"milestone":"AWAITING_CARRIER_PICKUP","resolution_condition":"REPLACEMENT_DELIVERED"},
        "service_progress_receipt": {"receipt_id":"R-"+c,"status":"ACTIVE","received_evidence":["facts"],"brand_action":"monitoring","latest_update_at":"2030-01-01T09:00:00+00:00","next_update_by":NEXT,"consumer_action_required":False,"recovery_if_missed":"another update"},
        "experience_risk":"MEDIUM",
        "audit_trail":[{"at":"2030-01-01T09:00:00+00:00","actor":"APPROVAL_SERVICE","action":"RESOLUTION_APPROVED","changed_fields":["open_obligation"],"request_id":"req-init"}],
    })

WORK=r'C:\a26\probe'; shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK, exist_ok=True)
repo = SQLiteLedgerRepository(os.path.join(WORK,'ledger.db'))
s0 = state(CASE)
snap = LedgerSnapshot(case_id=CASE, version=0, event_high_watermark=None, accountability_state=s0,
                      compiled_commitments=CompiledCommitments(commitments=(), compiled_from_evidence=False))
saved = repo.save(snap, expected_version=None)
print()
print("=== 初始账本 ===")
print("  版本:", saved.version, "| audit_trail 条数:", len(saved.accountability_state.audit_trail))

svc = ShipmentEventService(repository=repo)
def mk(key, eid, etype, etime):
    return ShipmentEventRequest.model_validate({
        "case_id": CASE, "idempotency_key": key, "event_id": eid,
        "event_type": etype, "event_time": etime})

print()
print("=== 标准3：相同请求重放，首个 response/request_id 不变，audit_trail 不增 ===")
r1 = svc.record_event_with_trace(mk("K-APPROVE-1","EV-P1","SHIPMENT_PICKED_UP","2030-01-01T10:10:00+00:00"), request_id="REQ-PROBE-1")
a1 = len(repo.load(CASE).accountability_state.audit_trail)
print("  第1次: replayed=%s status=%s request_id=%s audit=%d" % (r1.replayed, r1.status_code, r1.request_id, a1))
r2 = svc.record_event_with_trace(mk("K-APPROVE-1","EV-P1","SHIPMENT_PICKED_UP","2030-01-01T10:10:00+00:00"), request_id="REQ-PROBE-2")
a2 = len(repo.load(CASE).accountability_state.audit_trail)
print("  第2次: replayed=%s status=%s request_id=%s audit=%d" % (r2.replayed, r2.status_code, r2.request_id, a2))
same_resp = json.dumps(r1.response, sort_keys=True, ensure_ascii=False) == json.dumps(r2.response, sort_keys=True, ensure_ascii=False)
same_reqid = r1.request_id == r2.request_id
print("  响应完全相同:", same_resp, "| request_id 相同:", same_reqid, "| audit 未增:", a1 == a2)
ok3 = same_resp and same_reqid and (a1 == a2)
print("  判定:", "通过 ✓" if ok3 else "未通过 ✗")

print()
print("=== 标准2：相同 event_id 异体必须冲突 ===")
ok2 = False
try:
    svc.record_event_with_trace(mk("KEY-CONFLICT-1","EV-P1","SHIPMENT_DELIVERED","2030-01-01T11:00:00+00:00"))
    print("  未抛冲突 ✗")
except Exception as e:
    print("  抛出 %s:" % type(e).__name__)
    print("  完整错误:", str(e)[:400])
    ok2 = 'Conflict' in type(e).__name__ or 'conflict' in str(e).lower()
    a3 = len(repo.load(CASE).accountability_state.audit_trail)
    print("  audit 未因冲突增长:", a3 == a2)
    ok2 = ok2 and (a3 == a2)
print("  判定:", "通过 ✓" if ok2 else "未通过 ✗")
print()
print("=== 标准2b：相同幂等键但内容不同必须冲突 ===")
ok5 = False
try:
    svc.record_event_with_trace(mk("K-APPROVE-1","EV-P2","SHIPMENT_PICKED_UP","2030-01-01T10:15:00+00:00"))
    print("  未抛冲突 ✗")
except Exception as e:
    print("  抛出", type(e).__name__, "|", str(e)[:110])
    ok5 = "Conflict" in type(e).__name__
    print("  audit 未增:", len(repo.load(CASE).accountability_state.audit_trail) == a2)
    ok5 = ok5 and len(repo.load(CASE).accountability_state.audit_trail) == a2
print("  判定:", "通过 ✓" if ok5 else "未通过 ✗")

print()
print("="*60)
print("BATCH-26 独立探针:", "关键项通过 ✓" if (ok3 and ok2) else "存在未通过项 ✗")
print("  标准3 幂等重放不增审计:", "✓" if ok3 else "✗")
print("  标准2 相同event_id异体冲突:", "✓" if ok2 else "✗")
