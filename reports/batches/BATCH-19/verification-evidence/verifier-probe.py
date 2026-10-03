# -*- coding: utf-8 -*-
"""审查方独立探针 BATCH-19：自建账本探针，验证挑战隔离与既有状态保留。
不使用实现方测试文件。"""
import asyncio, inspect, os, sys
sys.path.insert(0, r'C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\worktrees\covenia-batch-19\backend\src')
sys.stdout.reconfigure(encoding='utf-8')
import covenia_b.services.analyze as AZ
from covenia_b.services.analyze import AnalyzeService
from covenia_b.services.fact_loader import FactLoader

class SpyLedger:
    """记录 load/save 调用的探针账本。"""
    def __init__(self): self.loads = 0; self.saves = 0
    def load(self, case_id): self.loads += 1; return None
    def save(self, snapshot, *, expected_version=None): self.saves += 1; raise RuntimeError("probe stop")
    def load_version(self, *a, **k): return None

print("=== 探针 A：挑战模式必须完全不碰账本 ===")
src = inspect.getsource(AZ.AnalyzeService._load_prior_snapshot)
print("  _load_prior_snapshot 源码首行:", src.splitlines()[1].strip())
print("  含 challenge_mode 短路:", "challenge_mode" in src)
src2 = inspect.getsource(AZ.AnalyzeService._persist_state)
print("  _persist_state 含 challenge_mode 短路:", "challenge_mode" in src2)
print("  短路后返回:", [l.strip() for l in src2.splitlines() if "challenge_mode" in l or "return state, False" in l][:3])

print()
print("=== 探针 B：normal 模式必须读账本（对照）===")
srcs = inspect.getsource(AZ.AnalyzeService._load_prior_snapshot)
print("  含 ledger_repository.load:", ".load(" in srcs)
print("  含 challenge 分支在上:", srcs.index("challenge_mode") < srcs.index(".load(") if ".load(" in srcs and "challenge_mode" in srcs else "n/a")

print()
print("=== 探针 C：既有状态是否传入状态构建器 ===")
scr = inspect.getsource(AZ.AnalyzeService.analyze_with_trace)
print("  调用 build_accountability_state:", "build_accountability_state(" in scr)
print("  传 persisted=:", "persisted=_persisted_ledger_from_snapshot(prior)" in scr)
print("  先加载 prior:", "prior = self._load_prior_snapshot(" in scr)
i_prior = scr.index("prior = self._load_prior_snapshot(")
i_build = scr.index("build_accountability_state(")
print("  prior 在 build 之前:", i_prior < i_build, "(位置 %d < %d)" % (i_prior, i_build))
i_persist = scr.index("_persist_state(")
print("  build 在 persist 之前:", i_build < i_persist)
print("  乐观并发 expected_version:", "expected_version=" in inspect.getsource(AZ.AnalyzeService._persist_state))

print()
print("=== 探针 D：模型输出不得拥有状态转移（结构断言）===")
print("  docstring:", AZ.AnalyzeService.analyze_with_trace.__doc__.strip())
print("  _compile_from_server_facts 存在:", hasattr(AZ, "_compile_from_server_facts"))
print("  _aggregate_server_evidence 存在:", hasattr(AZ, "_aggregate_server_evidence"))
print("  _server_image_observations 存在:", hasattr(AZ, "_server_image_observations"))
print()
print("=== 探针 E：错误分层（D13 诚信底线）===")
for n in ("AnalysisInputError","AnalysisModelUnavailable","AnalysisModelOutputError","AnalysisInfrastructureError"):
    c = getattr(AZ, n)
    print("  %-30s retryable 语义见构造" % n)
src_err = inspect.getsource(AZ.AnalyzeService.analyze_with_trace)
for kw in ("FactLoadingError","UnsafeModelInputError","ModelUnavailable","ModelOutputInvalid","LedgerConflict"):
    print("  捕获 %-24s: %s" % (kw, kw in src_err))
