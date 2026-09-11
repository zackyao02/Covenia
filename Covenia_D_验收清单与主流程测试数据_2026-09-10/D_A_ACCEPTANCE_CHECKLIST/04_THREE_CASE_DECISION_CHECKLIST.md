# 04｜三案例决策验收清单

依据：`fixtures/demo-cases.json`（输入）、`fixtures/ground-truth.json`（标准答案）、`docs/03-firewall-rules.md`（规则）、`schemas/decision-result.schema.json`（结构）。

这是 D 线最核心的一张表。主 Demo 只讲 `DEMO_001`，`DEMO_002` / `DEMO_003` 用于 Challenge Mode 和答辩验证。

---

## 1. 三个案例做什么

| 案例 | 场景 | 输入要点 | 想证明什么 |
|---|---|---|---|
| `DEMO_001` | 第二次进线，客服准备再次索证 | 已有三张泵头测试图、订单、换货工单、48 小时承诺 | 系统拦住重复索证，改为查询补发进度 |
| `DEMO_002` | 范围变化 | 赠品面膜外盒压坏的图片，问题是正装泵头 | 系统识别范围不一致，放行最小必要的重新索证 |
| `DEMO_003` | 图片模糊 | 同一商品，但照片没对上焦 | 系统不假装确定，转人工复核 |

---

## 2. 标准答案对照表（逐格打勾）

| 验收项 | DEMO_001 | DEMO_002 | DEMO_003 | 实际值 | 通过 |
|---|---|---|---|---|---|
| `evidence_status` | `VALID` | `MISMATCHED` | `NEED_HUMAN_REVIEW` | | ☐ |
| `decision` | `INTERVENE` | `ALLOW` | `HUMAN_REVIEW` | | ☐ |
| `rule_id` | `E1` | `E2` | `H1` | | ☐ |
| `rule_priority` | `300` | `100` | `200` | | ☐ |
| `resolution_path.candidate_type` | `CHECK_REPLACEMENT_FULFILLMENT` | `ASK_CURRENT_SCOPE_EVIDENCE` | `HUMAN_EVIDENCE_REVIEW` | | ☐ |
| `resolution_path.creates_obligation` | `true` | `false` | `false` | | ☐ |
| `accountability_state.prohibited_actions` 含 `ASK_SAME_EVIDENCE` | 是 | 否 | 否 | | ☐ |
| `accountability_state.open_obligation` | 人工确认后非空 | 空（`null`） | 空（`null`） | | ☐ |
| `accountability_state.service_progress_receipt` | 人工确认后非空 | 空（`null`） | 空（`null`） | | ☐ |
| `compiled_service_responsibility.commitment_class` | `STANDARD_APPROVED` | 无 | 无 | | ☐ |
| `compiled_service_responsibility.activation_status` | `ACTIVE` | 无 | 无 | | ☐ |
| `compiled_service_responsibility.deadline` | `2026-05-07T10:27:37+08:00` | 无 | 无 | | ☐ |
| `fact_trace.evidence_status` 与本行一致 | ☐ | ☐ | ☐ | | ☐ |
| `fact_trace.prepared_action` = `ASK_EVIDENCE` | ☐ | ☐ | ☐ | | ☐ |
| `fact_trace.scope_match` | `true` | `false` | 不允许为空（应可判定） | | ☐ |

说明：`DEMO_001` 的 `open_obligation` 与 `service_progress_receipt` 在**分析阶段**为 `null` 属于正常 —— 只有人工确认之后才会出现。这一点在对照 C 线发出的 `01-analyze-case.json` 样例时容易误判为「漏了」。

---

## 3. 每个案例单独检查

### DEMO_001｜主拦截

- ☐ 决策是 `INTERVENE`，规则 `E1`，优先级 `300`
- ☐ 推荐路径是「查询补发进度」，不是「重新索证」
- ☐ 原因里指出：证据有效、范围一致、已有有效承诺
- ☐ `prohibited_actions` 含 `ASK_SAME_EVIDENCE`
- ☐ 承诺原文含「48小时内发出」，分类 `STANDARD_APPROVED`
- ☐ `evaluation_time` 早于 `deadline`（承诺尚未到期）
- ☐ 人工确认后创建 `REPLACEMENT_FULFILLMENT` 责任
- ☐ 人工确认后生成消费者可见回执，`consumer_action_required: false`
- ☐ 截图：防线拦截提示、已有证据卡片、推荐查询补发进度

### DEMO_002｜范围变化放行

- ☐ 决策是 `ALLOW`，规则 `E2`，优先级 `100`
- ☐ 证据状态是 `MISMATCHED`
- ☐ 原因明确指出「哪一项变化了」：商品货号 / 正装与赠品 / 问题组件 / 证据类型
- ☐ 只请求当前缺失的证据（不是重复索取已有证据）
- ☐ `creates_obligation = false`，不创建责任
- ☐ 截图：系统允许重新索证并指出范围不一致

### DEMO_003｜图片模糊人工复核

- ☐ 决策是 `HUMAN_REVIEW`，规则 `H1`，优先级 `200`
- ☐ 证据状态是 `NEED_HUMAN_REVIEW`
- ☐ 模型没有给出确定性的证据结论
- ☐ `creates_obligation = false`
- ☐ 截图：人工复核提示

---

## 4. 同一规则链的验证口径

原文要求（`docs/03` 决策约束、`PRODUCT-FREEZE.md` A33）：

> 三个案例使用同一状态构建器和规则实现。禁止根据 `case_id` 返回固定结果。

三种合法的验证路径：

| 路径 | 做法 | 依据 | 状态 |
|---|---|---|---|
| 路径 1（主 Demo 用） | 全部对 `DEMO_001` 发起 `evaluate`，用 `challenge_mode: true` + `challenge_overrides` 造出 `ALLOW` 与 `HUMAN_REVIEW` | `PRODUCT-FREEZE.md` P0-8、A22 | 待测 |
| 路径 2（对照 ground-truth 用） | 分别对 `DEMO_001` / `DEMO_002` / `DEMO_003` 发起 `evaluate` | `fixtures/demo-cases.json` | 待测 |
| 路径 3（答辩抗演员） | 现场改图片清晰度、商品范围或承诺时间，看结论是否跟着变 | `docs/06` §5 | 待测 |

**D 要问 B 的一句话**：`DEMO_001/002/003` 是不是走同一套 `evaluate` 规则实现？如果 B 说「是」，就按路径 2 分别跑三遍，对答案。

---

## 5. 两条针对本表的红线

| 红线 | 检查动作 | 状态 |
|---|---|---|
| `ground-truth.json` 不得进入模型、状态构建器或体验防线 | 检查请求体与模型输入中无 `expected_decision`、`expected_rule_id`、`expected_evidence_status` | 待测 |
| 规则实现中不得出现案例编号字面量 | 静态扫描规则、状态构建器、Prompt：不得含 `DEMO_001`、`DEMO_002`、`DEMO_003`、`S00001` | 待测 |

注：`PRODUCT-FREEZE.md` 说明「按 `case_id` 装载事实」是允许的 —— 装载事实不等于直接返回结论。区别在于：**装事实可以，跳过计算直接返回结论不行**。
