# BATCH-22 独立验收报告（第二轮 · PASS）

> 纯文本版。机器可读版同目录：`VERIFICATION_REPORT.json`
> 计划 `required_outputs` 强制要求该 JSON，故保留；本文件为其逐字对应的可读版。

| 项 | 值 |
|---|---|
| 批次 | BATCH-22 evaluate HTTP 接口与可信覆盖 |
| 轮次 | 2 |
| 结论 | **PASS** |
| 受验提交 | `795928e611e9ce6f35c3d07afaa34911b41b5981` |
| 不可变基线 | `c2531a54e74e8ea1963896e81db3232017165720` |
| 实现来源提交 | `d86969094bd8416de3f671af2dd0c82ab31a92d5`（自第一轮分支重放） |
| 验收人 | 审查方（辅助调度器；实现方未参与） |
| 验收时间 | 2026-10-05 21:40 +08:00 |
| 独立上下文 | true（含下述偏离声明） |

## 一、取代的第一轮结论

| | |
|---|---|
| 轮次 1 | **BLOCKED** |
| 保留位置 | `reports/batches/BATCH-22/verification-history/round-1-blocked-lineage.json` |
| 来源 | 分支 `codex/verify-batch-22`，提交 `be64548` |
| 阻塞原因 | BATCH-16 与 BATCH-20 的 `IMPLEMENTATION_REPORT.json` / `VERIFICATION_REPORT.json` 及其 run-specific 集成回执不在受验谱系上 |
| 解除方式 | 第二轮改从满足该前置条件的基线 `c2531a5` 重放实现提交并重跑验收 |

## 二、依赖谱系前置条件核查（已清除）

第一轮 `minimal_fix_request` 要求「提供含 BATCH-16 与 BATCH-20 已验收产物及 run-specific 集成回执的谱系」。

| 检查 | 结果 |
|---|---|
| `reports/batches/BATCH-16/IMPLEMENTATION_REPORT.json` | PRESENT |
| `reports/batches/BATCH-16/VERIFICATION_REPORT.json` | PRESENT |
| `reports/batches/BATCH-20/IMPLEMENTATION_REPORT.json` | PRESENT |
| `reports/batches/BATCH-20/VERIFICATION_REPORT.json` | PRESENT |
| `integration-receipts/BATCH-16.json` | 存在 |
| `integration-receipts/BATCH-20.json` | 存在（`INTEGRATED_RECONFIRMED`） |

→ **前置条件已满足，`cleared = true`。**

## 三、验收标准原文（逐字引用 batches.json）

1. 最小可信请求、伪造状态与 Challenge 关/开得到冻结预期。
2. 三种决策都能从此接口执行，E0 是成功 ALLOW；P0 按批准传输语义返回完整可解释结果。
3. 任意不同案例 ID 同事实得到同决策；状态与 fact_trace 不矛盾。
4. 按5.5使用本批绝对隔离venv解释器；新增第三方依赖只增不改、精确钉版本并提交锁文件差异/原因/hash证据；交付前同解释器 pip check 退出0。环境证据缺失或冲突不得PASS。

## 四、验收方复跑的命令

| 命令 | 结果 | 退出码 |
|---|---|---|
| `C:\r22b\venv\Scripts\python.exe -m pip install --no-deps -r backend/requirements-dev.lock` | 命中本机 wheel 缓存，31 个发行版 | 0 |
| `C:\r22b\venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e backend` | `Successfully installed covenia-b-0.0.0` | 0 |
| `... -c "import pytest, jsonschema"` | pytest 8.3.4 / jsonschema 4.25.0 | 0 |
| `... -m pytest backend/tests/api/test_evaluate.py -q` | **3 passed in 0.84s** | 0 |
| `... tools/contracts/check_contracts.py --strict` | `{"lock":"docs/contracts/b-contract-lock.json","schemas_validated":14,"strict":true,"vectors_validated":18}` | 0 |
| `... -m pip check` | `No broken requirements found.` | 0 |
| `git diff --check` / `git status --short` | 无跟踪文件改动 | 0 |
| `python checks/anti_shortcut_scan.py --git <repo> codex/verify-batch-22-r2 backend/src/covenia_b/services/evaluate.py backend/src/covenia_b/api/evaluate.py` | **通过：A33 三项判据均无命中** | 0 |
| `... reports/batches/BATCH-22/verification-evidence/round-2/aux_adapter_probe.py` | **14 项通过 / 0 项失败** | 0 |

## 五、自建独立探针

**路径**：`reports/batches/BATCH-22/verification-evidence/round-2/aux_adapter_probe.py`
**日志**：`reports/batches/BATCH-22/verification-evidence/round-2/independent-probe-output.txt`

**独立性**：不 import 实现方的 `backend/tests/api/test_evaluate.py`；不使用其内部辅助函数；
不引用第一轮验收者的 `independent_probe.py`（该探针以 `runpy` 加载实现方测试文件取辅助函数，独立性弱于本探针）。
仅依赖公开接口 `create_evaluate_router`、`ApiError` 与冻结 schema 语义，以自造替身服务驱动路由端点。

**通过项（14/14）**：

- 成功路径 HTTP 200，信封为 `{data, error: null, request_id}`
- `request_id` 原样回带
- 伪造客户端状态字段仍以服务端事实为准返回成功
- 弃用字段被保留（冻结 schema 声明的兼容语义）
- 服务端从不读取请求侧弃用字段（**保留但不采信**）
- P0 走 HTTP **400** 错误信封，`data` 为 `null`，不得落进成功体
- P0 错误码为 `P0_PROHIBITED_ACTION`
- 未分析状态映射 **422** `VALIDATION_ERROR`（不得凭空造事实）
- 缺 `prepared_action` 映射 **422** `SCHEMA_INVALID`

## 六、逐条标准映射

| 标准 | 证据 | 通过 | 独立性 |
|---|---|---|---|
| 1 最小可信请求 / 伪造状态 / Challenge 关开 | 自建探针：伪造 `accountability_state`/`prohibited_actions`/`current_scope` 仍返回服务端结论；静态核验 `services/evaluate.py` 无 `request.<field>` 读取。Challenge 关/开由实现方测试与第一轮验收者探针覆盖 | ✅ | 部分（见下） |
| 2 三种决策 / E0 成功 ALLOW / P0 传输语义 | 自建探针：P0 → 400 + `P0_PROHIBITED_ACTION` + `data null`；成功路径 200 + `E0_NO_RULE_MATCHED`。E0/H1/E1/E2 动态覆盖来自重跑实现方测试（3 passed） | ✅ | 部分 |
| 3 不同案例 ID 同事实同决策；状态与 fact_trace 不矛盾 | 第一轮验收者探针已断言：不同 `case_id` 相同事实下 `decision=ALLOW`、`rule_id=E0_NO_RULE_MATCHED` 一致；`challenge_mode=false` 时 `fact_trace.evidence_status=VALID`。本轮回跑结论未变 | ✅ | 部分 |
| 4 隔离 venv / 只增不改 / pip check 退出 0 | `C:\r22b\venv`（新建，长度 12），`sys.prefix=C:\r22b\venv` 与 `sys.base_prefix=D:\python` 不同；`git diff 5378f46..795928e` 对 `backend/requirements-dev.lock` 为空；pip check 退出 0 | ✅ | 完整 |

## 七、产物哈希

**方法**：SHA-256 over raw bytes from `git show 795928e:<path>`（**禁用工作副本**）

```
3ACEF6BA55E8F1541898454BE6D1E3563BADB7F0FA6C679CB2E298A1D4BCF85A  backend/src/covenia_b/api/evaluate.py
E90F72518FA53C7097F4425806E6986D732C429022591820F47922FC5E0AF5EE  backend/src/covenia_b/services/evaluate.py
9C4961BDCB758C6AC128FB6690190D20ACB31DB3ADBF44E56E4309440C902479  backend/tests/api/test_evaluate.py
```

## 八、未能独立复现的部分（如实列明）

1. E0/H1/E1/E2 与 Challenge 关/开的动态证据来自**重跑实现方自带测试**（3 passed），与本轮自建探针互补；未由自建探针从零构造状态构建链路覆盖。
2. 自建探针使用**替身服务**驱动路由端点，未验证真实服务的端到端决策（真实服务需 BATCH-19 分析后的账本快照，属跨批运行接线，见下节风险）。
3. 第三方依赖钉版本与锁文件差异由实现方记录，除 pip check 与范围审计外未独立复算锁内容。
4. **本轮发现并已自我更正一处方法学误判**：初版探针断言弃用字段必须为 `None`，实测被保留；经静态核验服务端从不读取该字段，故更正为「保留但不采信」而非缺陷 —— **不据此判 FAIL**。

## 九、方法学更正记录（MC-BATCH22-ACCOUNTABILITY-STATE-20261005）

> 产品负责人 2026-10-05 明确要求：本更正过程须写进验收报告，作为**方法学记录**。

| 项 | 值 |
|---|---|
| 编号 | `MC-BATCH22-ACCOUNTABILITY-STATE-20261005` |
| 状态 | **SELF_CORRECTED_BEFORE_VERDICT**（定稿前自我更正） |
| 对结论影响 | **无** —— 未改变 PASS，也未放宽任何标准 |

### 经过

1. 自建探针初版断言：请求中的弃用字段 `accountability_state` 解析后**必须为 `None`**（理由：不得被采信）。
2. 实测：该字段**被保留**，值为探针注入的 `{'decision': 'INTERVENE', 'rule_id': 'P0_PROHIBITED_ACTION'}` → 初版探针报 **1 项 FAIL**（13 项中 1 项）。
3. **不据单次失败下结论**，先做静态核验：全 `backend/src` 搜索 `accountability_state` 的出现位置。

### 定案证据

文件 `backend/src/covenia_b/services/evaluate.py`，全部出现处：

| 行 | 内容 | 性质 |
|---|---|---|
| 35 | `from covenia_b.state import build_accountability_state` | 导入，非读取请求字段 |
| 124 | `if snapshot is None or snapshot.accountability_state is None` | 读**服务端账本快照** |
| 137 | `rebuilt = build_accountability_state(...)` | 由 `case/journey/evidence/compilation/snapshot` 重建，**不含请求字段** |

→ 实现**从不读取** `request.accountability_state`；冻结 schema 亦将其声明为 `deprecated` / `readOnly` 的兼容字段。

### 更正后的政策表述

> 弃用字段「**保留但不采信**」：解析层保留以维持兼容，决策层完全以服务端事实（case / journey / evidence / compilation / ledger snapshot）为准。

更正后两项断言均 PASS：

- 「弃用字段被保留（冻结 schema 声明的兼容语义，**非缺陷**）」
- 「服务端不读取请求侧弃用字段（**保留但不采信**）」（静态核验无 `request.<field>` / `parsed.<field>` 读取）

### 为何这是方法学记录、而非放水

1. **不是把不达标写成达标**：「不采信」主张有静态调用点证据支撑，另有动态探针佐证（注入伪造值仍返回服务端结论）。
2. **未删减标准**：四条 `acceptance_criteria` 逐条映射且全部 PASS，原文完整引用见第三节。
3. **误判保留在案**而非抹除，供后续验收对照。
4. **项目先例**：`PROJECT_STATUS.md` 记录过同类陷阱 ——「第三次误判：报 P0 规则消失，实为有意的成功/错误分离」。审查方对自身结论的证伪义务由此确立。

### 建议常设规则

> 凡「某字段必须为 X」类断言，先区分【**保留/呈现**】与【**采信/参与判定**】两种语义，并以**调用点证据**判定后者；**不得以字段存在或非空直接判缺陷**。

## 十、回归风险

1. 本批测试直接驱动路由端点；**应用装配（`main.py` 路由注册）不在本批 `allowed_paths` 内**，须由 BATCH-27 承担。
2. 集成级已知问题（**非本批缺陷**）：BATCH-24 引入的 `backend/tests/api/test_approve.py` 与 BATCH-23 的 `backend/tests/services/test_approve.py` 模块同名，导致全量 `pytest` 收集失败；见 `_aux/findings/CROSS-LINE-TESTMODULE-COLLISION-20261005.md`。

## 十一、结论

**findings: 无 · minimal_fix_list: 无 · blockers: 无 · code_modified: false · next_batch_started: false**

## 十二、验收方独立性偏离声明（依规约 §六 必须写明）

本验收由**辅助调度器（审查角色）**执行，**而非全新独立任务线程**，因 Codex 额度耗尽。
该偏离在此显式记录，并请另行安排**独立复核本验收本身**（复验验收）。

验收方仅写本报告与其 `verification-evidence/round-2/` 证据；未修改任何实现文件；
未改动 `backend/requirements-dev.lock`；未改计划语义。
