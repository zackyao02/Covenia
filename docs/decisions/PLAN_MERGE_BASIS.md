# 计划合并依据表｜解冻前置（第 3 版）

**出具人**：审查方　**日期**：2026-09-29
**版本说明**：本版依第一段两轮指正修订。**修订处已逐条标注「更正」。**

---

## 〇、勘误记录（审查方自查）

| # | 审查方先前表述 | 实际情况 | 性质 |
|---|---|---|---|
| E1 | 「BATCH-14 依赖早已就绪，不是逻辑阻塞」 | BATCH-13 于 **09-28 18:12** 才完成集成，此前 14 被合法阻塞 | **抽样/时点误读** |
| E2 | 「allowed_paths 差异只有 requirements-dev.lock」 | 仅抽样 5 批；**BATCH-01 另差 **`docs/approvals/**`**，**BATCH-11 另差 **`docs/02-ai-extraction.md` | **抽样代替全量** |
| E3 | 「工作区版无逐批验证命令」 | 工作区有 **77** 条命令行；仓库 **142** 条。**不是"没有"，是"较少"** | **未核实即断言** |
| E4 | **完全未检查 **`forbidden_paths` | **34/34 批都存在漂移，且属安全相关** | **漏检** |
| E5 | X-A-MAPPING 改 ACCEPTED 的依据写作「三份交付物均已入库」 | 正确依据是**既有接收链**（`90c8359` 的 `ARCHIVE_REPORT.json` 记 `gate_status=ACCEPTED` + BATCH-05 独立验收已核验） | **证据强度不足** |
| E6 | V4 复核用 `git show --stat` | `--stat` 只给行数，不证语义保留 | **方法不足** |

**共同根因**：审查方多次以**抽样或间接证据**下结论，且**只对比了 `allowed_paths` 一个维度**。
已加入审核清单：**全量枚举、双向对比 `allowed_paths` 与 `forbidden_paths`、证据须用接收记录而非文件存在性**。

---

## 一、漂移量化

| | 工作区副本 | 集成分支 blob |
|---|---|---|
| 大小 | 284,034 B（4445 行） | 210,779 B（3933 行） |
| 独有段落 | 116 段 / 521 行 | 21 段 / 512 行 |
| 批次集合 | 34/34 一致 ✅ | |
| 依赖关系 | **0 差异** ✅ | |

### allowed_paths（逐批枚举）

| 模式 | 批次数 | 工作区版独有 | 仓库版独有 |
|---|---|---|---|
| 标准 | **31** | `backend/requirements-dev.lock` | — |
| **BATCH-01** | 1 | `backend/requirements-dev.lock` + **`docs/approvals/**`** | — |
| **BATCH-11** | 1 | `backend/requirements-dev.lock` + **`docs/02-ai-extraction.md`** | — |
| BATCH-02 | 1 | （无差异） | — |

**仓库版独有项 = 0** → 工作区版为**严格超集**，合并**不损失任何既有权限**。

### 🔴 forbidden_paths（第 2 版遗漏，安全相关）

| 项 | 工作区版 | 仓库版 |
|---|---|---|
| 不一致批次 | — | **34 / 34** |
| **`fixtures/**` 通配禁令** | **全部 34 批均有** | **全部 34 批均无** |
| 仓库版独有项 | — | **0** |

**仓库版只逐个禁止具体文件**（`fixtures/ground-truth.json`、`fixtures/demo-cases.json`、
`fixtures/synthetic-pattern-card.json`），**没有 `fixtures/**` 通配禁令**。

**后果**：若按"取仓库"合并，**将删除全部 34 批的 `fixtures/**` 防护**——
而这道禁令正是 X-A-FIXTURES 交付时产品负责人授予一次性例外的**前提**。
**必须保留工作区版的完整禁令。**

### 验证命令

| | 工作区 | 仓库 |
|---|---|---|
| MASTER_PLAN 命令行数 | 77 | **142** |
| batches.json 键 | `acceptance_commands` | `acceptance_commands` |

**更正**：两侧都有，仓库更多。合并应取**并集**，不得以仓库版覆盖工作区版而丢失 77 条。

---

## 二、逐项裁定（第 3 版）

### A. 内容类

| # | 内容 | 取 | 依据 |
|---|---|---|---|
| A1 | §5.1.1 常设线程与人工阻塞规则 | **仓库** | 集成提交 `14f3529` / `69d78e8`（09-28） |
| A2 | 逐批验证命令 | **并集** | 工作区 77 + 仓库 142，**不得替换**（依 E3 更正） |
| A3 | §5.5 全局环境与依赖约定 | **工作区** | **第一段已确认：已授权未集成**（2026-09-29） |
| A4 | 绝对隔离 venv 解释器 | **工作区** | 同上 |
| A5 | 条件性锁追加 + 独占锁 + 失效保护 | **工作区** | 同上 |
| A6 | 只读重载不依赖状态落盘 | **工作区** | 同上 |
| A7 | §4.1 X-A-FIXTURES 交接正文 | **保留历史正文 + 加「已完成 / ACCEPTED（2026-09-13）」** | 第一段已裁定 |
| **A8** | **`forbidden_paths`（含 `fixtures/**` 通配禁令）** | **工作区（全量保留）** | 34/34 漂移；仓库版无通配禁令；**安全相关** |

### B. 外部门状态

| # | 门 | 工作区 | 仓库 | 取 | 依据 |
|---|---|---|---|---|---|
| B1 | X-FREEZE | ACCEPTED | MISSING | **工作区** | `docs/approvals/b-decisions.json` 已在仓库，SHA256 `3ACAD4A1…71DA`，13 条批准；两边哈希逐字节一致 |
| B2 | X-A-FIXTURES | MISSING | ACCEPTED | **仓库** | 门回执 `GATE_ACCEPTANCE_RECEIPT.json` 已入库（1950 B，09-13） |
| B3 | **X-A-MAPPING** | MISSING | MISSING | **改为 ACCEPTED** | **更正（依 E5）**：依据是**既有接收链**——`90c8359` 归档的 `reports/batches/X-A-MAPPING/ARCHIVE_REPORT.json` 明记 `gate_status=ACCEPTED`；且 **BATCH-05 独立验收已核验**（其 `VERIFICATION_REPORT.json` 载明「X-A-MAPPING is ACCEPTED and its 74175-byte integrated raw Git blob has the required SHA-256」）。**不是"三份文件存在"。** 签发方式依第一段裁定：**集成协调者补登记、审查方独立复核**，无需产品负责人补签 |
| B4 | X-A-IMAGES | ACCEPTED | ACCEPTED | 一致 | 无冲突 |

> 📌 **附注（重要）**：**BATCH-05 的验收方在 2026-09-13 已发现并记录此漂移**，原文：
> 「Remaining governance risk: the dispatched X-A-MAPPING archive record is `ACCEPTED`,
> but the static external-gate fields in the supplied root plan and batches.json still state MISSING」，
> 并建议「coordination should reconcile the registry separately」。
> **该建议搁置 16 天未处理。** 这不是新发现的问题，是**未被执行的既有发现**。

### C. 写权限

| # | 项 | 取 | 依据 |
|---|---|---|---|
| C1 | `allowed_paths` 含 `backend/requirements-dev.lock` | **工作区** | 与 §5.5 配套；真实缺口前例（`jsonschema`/`referencing` 缺失）；不列入则 BATCH-18 必阻塞 |
| C2 | `docs/approvals/**`（BATCH-01） | **工作区** | 仅用于原样归档已提供的批准记录 |
| C3 | `docs/02-ai-extraction.md`（BATCH-11） | **工作区** | 对应既有裁定：该文件归 BATCH-11 |
| C4 | 条件性锁协议（独占锁 + 失效保护） | **工作区** | 含完整失效保护条款 |
| **C5** | **`forbidden_paths` 全量** | **工作区** | 见 A8 |

---

## 三、续跑裁定（第一段已定）

**选择 (b) 转人工决断。**上限保持 2。

- 再次中断**不得自动第三次续跑**，**换任务亦不得清零**
- 一次性人工恢复须另有真实授权，且经**额度、工作树、锁、记账**四项检查
- 模板已落：`docs/planning/b/RESUME_RECEIPT.template.json`

**审查方附注（实证）**：本轮 BATCH-08/09 的唤醒记录显示 `wake_trigger = 人工提示`，
`quota_recovery_at = NOT_OBSERVABLE`。**自动续跑至今从未真正触发过**，
故「开关已写入」不能作为「能力已验证」。第一段此点已由本次回执实证。

---

## 四、合并后的复核要求（依 E6 更正）

| # | 复核项 | 方法（**已更正**） |
|---|---|---|
| V1 | 依赖图未变 | 34 批 `depends_on` 逐项比对 |
| V2 | `allowed_paths` 收敛 | 应为 **34/34 一致**（当前 33/34） |
| V3 | **`forbidden_paths` 收敛** | 应为 **34/34 一致**，且**每批保留 `fixtures/**`**（当前 34/34 不一致） |
| V4 | **完整差异与语义保留** | **更正**：不得用 `git show --stat` 或"零删除行"代替。须做**逐文件完整内容比对**，确认：(a) 无既有集成分支内容被删除；(b) 新增内容确为工作区/仓库两版之并集；(c) §5.1.1、§5.5、§4.1 三节语义完整 |
| V5 | 四个外部门状态自洽 | 与各自**接收记录**（非文件存在性）一致 |

合并后记录 `plan_sha256`（取**提交内 blob**，不用工作副本）。

---

## 五、审查方声明

- 本表每项裁定**附可验证证据**（文件存在性、SHA256、提交号、**接收记录**），不采信任何一方自述。
- 审查方**不执行合并**：改计划是规划方职责。
- 本表**不涉及**任何批准内容的改写或补签。
- **A8 / C5（保留完整 `forbidden_paths`）是"维持现状"而非"扩权"**，但仍请第一段确认，
  因其影响全部 34 批的写入边界。
- 本版为第 3 版，修订处已逐条标注；勘误记录见第〇节。
