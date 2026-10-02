# -*- coding: utf-8 -*-
"""审查方独立探针：BATCH-18 SQLite 事务/幂等/审计 —— 不使用实现方测试。"""
import io, os, shutil, sys, tempfile, traceback
sys.path.insert(0, r'C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\worktrees\covenia-batch-18\backend\src')
sys.stdout.reconfigure(encoding='utf-8')
from covenia_b.domain.types import LedgerSnapshot, CompiledCommitments
from covenia_b.storage import SQLiteLedgerRepository, Mutation, StoredResponse
from covenia_b.storage.models import IdempotencyConflict

WORK = r'C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\_scratch\b18-probe'
shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK, exist_ok=True)
DB = os.path.join(WORK, 'ledger.db')

def snap(case, ver, tag=""):
    return LedgerSnapshot(case_id=case, version=ver, event_high_watermark=None,
                          accountability_state=None,
                          compiled_commitments=CompiledCommitments(commitments=(), compiled_from_evidence=False))

def body(case, key, extra=None):
    b = {"case_id": case, "idempotency_key": key}
    if extra: b.update(extra)
    return b

repo = SQLiteLedgerRepository(DB)
CASE = "CASE-PROBE-1"
calls = {"n": 0}
def mutate(cur):
    calls["n"] += 1
    v = 0 if cur is None else cur.version
    env = {"data": None, "error": {"code": "VALIDATION_ERROR", "message": "probe", "retryable": False}, "request_id": "req-%d" % calls["n"]}
    return Mutation(snapshot=snap(CASE, v), response=StoredResponse(body=env))

print("=== 判据 1：相同请求十次重放只有一次变更 ===")
results = []
for i in range(10):
    r = repo.execute(case_id=CASE, operation="approve", idempotency_key="KEY-AAA",
                     request_body=body(CASE, "KEY-AAA"), mutate=mutate)
    results.append(r)
versions = [r.snapshot.version for r in results]
bodies = [dict(r.response.body) for r in results]
print("  版本序列:", versions)
print("  回调实际执行次数:", calls["n"], "（应为 1）")
print("  replayed 序列:", [r.replayed for r in results])
print("  响应体是否全同:", len({str(b) for b in bodies}) == 1)
ok1 = (calls["n"] == 1 and versions == [1]*10 and len({str(b) for b in bodies}) == 1
       and [r.replayed for r in results] == [False] + [True]*9)
print("  判定:", "通过 ✓" if ok1 else "未通过 ✗")

print()
print("=== 判据 2：同键不同内容必须冲突且状态不动 ===")
before = repo.load(CASE).version
ok2 = False
try:
    repo.execute(case_id=CASE, operation="approve", idempotency_key="KEY-AAA",
                 request_body=body(CASE, "KEY-AAA", {"different": "content"}), mutate=mutate)
    print("  未抛冲突 ✗")
except IdempotencyConflict as e:
    after = repo.load(CASE).version
    print("  抛出 IdempotencyConflict ✓  code=%s" % getattr(e, 'code', '?'))
    print("  状态版本 before=%s after=%s 不变=%s" % (before, after, before == after))
    ok2 = (before == after)
except Exception as e:
    print("  抛了别的异常 %s: %s ✗" % (type(e).__name__, str(e)[:70]))
print("  判定:", "通过 ✓" if ok2 else "未通过 ✗")

print()
print("=== 判据 3：异常注入不留半成品 ===")
before = repo.load(CASE).version
def boom(cur):
    raise RuntimeError("injected failure")
ok3 = False
try:
    repo.execute(case_id=CASE, operation="shipment", idempotency_key="KEY-BBB",
                 request_body=body(CASE, "KEY-BBB"), mutate=boom)
    print("  未抛异常 ✗")
except Exception as e:
    after = repo.load(CASE).version
    print("  注入异常被传播: %s" % type(e).__name__)
    print("  状态版本 before=%s after=%s 不变=%s" % (before, after, before == after))
    ok3 = (before == after)
print("  判定:", "通过 ✓" if ok3 else "未通过 ✗")

print()
print("=== 判据 4：保留事件历史便于重建 ===")
from covenia_b.storage import EventRecord
ev_body = body(CASE, "KEY-CCC")
ev_body.update({"event_id": "EV-PROBE-1", "event_type": "SHIPMENT_PICKED_UP",
                "event_time": "2026-05-07T10:10:00+08:00"})
ev = EventRecord(event_id="EV-PROBE-1", event_type="SHIPMENT_PICKED_UP",
                 event_time="2026-05-07T10:10:00+08:00")
def mutate2(cur):
    v = 0 if cur is None else cur.version
    env = {"data": None, "error": {"code": "VALIDATION_ERROR", "message": "probe2", "retryable": False}, "request_id": "req-ev"}
    return Mutation(snapshot=snap(CASE, v), response=StoredResponse(body=env))
try:
    repo.execute(case_id=CASE, operation="shipment", idempotency_key="KEY-CCC",
                 request_body=ev_body, mutate=mutate2, event=ev)
    print("  带事件写入成功")
except Exception as e:
    print("  带事件写入失败: %s: %s" % (type(e).__name__, str(e)[:90]))

events = repo.event_history(CASE)
print("  event_history 条数:", len(events))
for e in events[:3]:
    print("     %s | %s | %s" % (e.event_id, e.event_type, e.event_time))
hist = repo.audit_history(CASE)
print("  audit_history 条数:", len(hist))
print("  load_version(1) 可取回历史:", repo.load_version(CASE, 1) is not None)
print("  当前版本:", repo.load(CASE).version)
ok4 = (len(events) >= 1 and repo.load_version(CASE, 1) is not None)
print("  判定:", "通过 ✓" if ok4 else "未通过 ✗")

print()
print("=" * 60)
allok = ok1 and ok2 and ok3 and ok4
print("BATCH-18 独立探针结论:", "四项全过 ✓" if allok else "存在未通过项 ✗")
for n, o in (("幂等十次一次变更", ok1), ("同键异内容冲突", ok2), ("异常注入无半成品", ok3), ("事件历史保留", ok4)):
    print("  %-24s %s" % (n, "✓" if o else "✗"))
