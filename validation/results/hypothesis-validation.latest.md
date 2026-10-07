# Covenia H1–H4 当前可执行验证结果

生成时间：2026-10-07T01:07:01.728760+00:00

## 结论

| 假设 | 当前结论 | 本次能证明什么 | 仍不能证明什么 |
|---|---|---|---|
| H1 | MECHANISM_VERIFIED_EFFECT_NOT_VALIDATED | Customer State 在 3 个设计案例中完整、稳定恢复，记录本地读取耗时 | 真人客服上下文恢复时间是否下降 |
| H2 | SUPPORTED_ON_DESIGNED_CASES_ONLY | 3 个设计案例的决策与规则标签全部匹配 | 生产准确率与真实误拦截率 |
| H3 | GOVERNANCE_AND_TRACEABILITY_VERIFIED_ACCURACY_NOT_VALIDATED | 失败安全降级、信号可追溯、模型信号不改写服务状态 | JEV 准确率、提前量与阈值 |
| H4 | MONITOR_AND_DRAFT_GENERATION_VERIFIED_UPLIFT_NOT_VALIDATED | 承诺可调度、逾期只升级一次、物流异常生成需人工确认的主动通知草稿 | 真实主动更新率提升 |

## 可复现结果

- H1：Customer State 必填区块覆盖 8/8；40 次进程内读取 P50 1.122 ms，P95 1.275 ms。
- H2：规则与决策精确匹配 3/3；重复索证 Precision 1.0，Recall 1.0。
- H3：安全降级=True；新消息来源可追溯=True；服务状态未被模型信号改写=True。
- H4：逾期升级只写入一次=True；主动通知草稿生成=True；草稿仍需人工批准=True。

## 证据边界

本次使用赛事 Mock 数据和团队设计案例，只验证机制和安全边界。报告中的 Precision/Recall 仅对应 3 个设计案例，不能作为生产准确率。H1 的效率提升、H3 的模型表现和 H4 的业务提升需要真人或真实业务数据。
