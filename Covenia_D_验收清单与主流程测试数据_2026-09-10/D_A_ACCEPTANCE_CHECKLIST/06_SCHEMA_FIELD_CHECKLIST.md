# 06｜Schema 字段验收清单

依据：`schemas/` 目录下九个 schema 文件。

结构看 `schemas/`，数值看 `fixtures/ground-truth.json`。两个维度都要过。

---

## 主链上每个 schema 的位置

```text
CaseInput → ExtractedJourney → AccountabilityState + PreparedAction → DecisionResult → AccountabilityState 更新
```

| Schema | 对应环节 | 谁产出 | D 验收什么 |
|---|---|---|---|
| `case-input.schema.json` | 输入 | A/B 准备 | 字段是否完整、来源是否标对 |
| `extracted-journey.schema.json` | AI 抽取 | B 的模型 | 图片观察、承诺、旅程理解是否结构化 |
| `prepared-action.schema.json` | 客服准备动作 | C 的界面触发 | 动作类型和请求范围 |
| `accountability-state.schema.json` | 责任账本 | B 的状态构建器 | 证据状态、责任方、禁止动作、回执 |
| `decision-result.schema.json` | 体验防线输出 | B 的规则引擎 | 三选一决策 + 规则 + 原因 + 解决路径 |
| `api-envelope.schema.json` | 所有响应外层 | B | `data` / `error` / `request_id` 三者关系 |

---

## 1. `case-input.schema.json`

| 字段 | 约束 | 检查动作 | 状态 |
|---|---|---|---|
| `data_provenance.source_dataset` | 固定 `TIANCHI_LOREAL_TRACK1_MOCK` | 核对三个案例 | 待测 |
| `data_provenance.source_session_id` | 非空 | 应为 `S00001` | 待测 |
| `data_provenance.augmentation_notes` | 数组，逐条说明扩充内容 | 核对三个案例 | 待测 |
| `conversation[].source_kind` | 只能 `COMPETITION_MOCK` 或 `DEMO_AUGMENTATION` | 核对每条消息 | 待测 |
| `conversation[].speaker` | 只能 `CONSUMER` / `AGENT` / `SYSTEM` | 核对 | 待测 |
| `order.channel` | 固定 `TIANCHI_MOCK_QIANNIU` | 核对 | 待测 |
| `order.items[].item_role` | `PRIMARY` / `GIFT` / `BUNDLE_COMPONENT` | 正装为 `PRIMARY`，面膜为 `GIFT` | 待测 |
| `service_tickets[].ticket_type` | 五类之一 | `BH919209358357` 为 `REPLACEMENT` | 待测 |
| `evidence_images[].source_kind` | 只能 `TEAM_SYNTHETIC_RECREATION` 或 `TEAM_SYNTHETIC_AUGMENTATION` | 核对三张图 | 待测 |
| `current_issue.issue_type` | P0 为 `PACKAGE_DAMAGE` | 核对 | 待测 |
| `current_issue.affected_component` | 枚举含 `PUMP` | 应为 `PUMP` | 待测 |
| `policy_requirement_id` | 固定 `DEMO_POLICY_PACKAGE_DAMAGE_V1` | 核对 | 待测 |
| 红线 | 输入中不得出现承诺结论、证据最终状态、责任方、防线结果 | 全文搜索 `expected_` | 待测 |

---

## 2. `extracted-journey.schema.json`

| 字段 | 检查动作 | 期望 | 状态 |
|---|---|---|---|
| `completed_actions.issue_explained` | 问题是否已解释 | `true` | 待测 |
| `completed_actions.order_verified` | 订单是否已验证 | 有订单关联 | 待测 |
| `completed_actions.evidence_submitted` | 证据是否已提交 | `true` | 待测 |
| `promise_events[].raw_text` | 承诺原文 | 含「换货单已创建，48小时内发出」 | 待测 |
| `promise_events[].commitment_class` | 五类之一 | `STANDARD_APPROVED`（改「尽快」后应变 `AMBIGUOUS`） | 待测 |
| `promise_events[].activation_recommendation` | AI 的建议值 | `ACTIVE` | 待测 |
| `promise_events[].deadline` | 截止时间 | `2026-05-07T10:27:37+08:00` | 待测 |
| `promise_events[].source_ids` | 至少一个来源 | 指向客服消息 `36199788469718.PNM` | 待测 |
| `image_observations[].readability` | `HIGH` / `LOW` / `UNKNOWN` | 清晰图 `HIGH`，模糊图 `LOW` | 待测 |
| `image_observations[].sku_match` | `MATCH` / `MISMATCH` / `UNKNOWN` | 正装图 `MATCH`，赠品图 `MISMATCH` | 待测 |
| `image_observations[].product_role` | `PRIMARY` / `GIFT` / … | 泵头图 `PRIMARY` | 待测 |
| `image_observations[].issue_visible` | 布尔 | 清晰图 `true` | 待测 |
| `image_observations[].affected_component` | 枚举 | `PUMP` | 待测 |
| `image_observations[].coverage` | 覆盖项数组 | 覆盖商品身份与受损部件 | 待测 |
| `image_observations[].integrity_concern` | 必填布尔 | 有值 | 待测 |
| `image_observations[].hygiene_risk_signal` | 必填枚举 | 有值 | 待测 |
| `journey_understanding.consumer_intent` | 非空 | 见 `ground-truth.json` | 待测 |
| `journey_understanding.cooperation_willingness` | 枚举 | `DEMO_001` 为 `DECLINING` | 待测 |
| `source_trace[]` | 每条结论可回指来源 | 字段 ↔ 来源成对出现 | 待测 |
| `model_metadata.model_id` | 固定 | `Qwen/Qwen2-VL-2B-Instruct` | 待测 |
| `model_metadata.cached_result` | 若为 `true`，界面必须标注 | 三处同时可见 | 待测 |

---

## 3. `prepared-action.schema.json`

| 字段 | 检查动作 | 期望 | 状态 |
|---|---|---|---|
| `action_type` | P0 主要验证 `ASK_EVIDENCE` | 三个案例均为 `ASK_EVIDENCE` | 待测 |
| `requested_scope` | `ASK_EVIDENCE` 时必填 | 含订单、履约项、SKU、问题类型四项 | 待测 |
| `requires_human_approval` | 布尔 | 有明确值 | 待测 |
| 变体用法 | 范围与历史证据不一致时应触发 `E2` | `DEMO_002` 走 `ALLOW` | 待测 |

---

## 4. `accountability-state.schema.json`

| 字段 | 允许值 | 检查动作 | 状态 |
|---|---|---|---|
| `case_status` | `WAITING_FOR_CONSUMER` / `READY_FOR_BRAND` / `ACTION_REVIEW` / `IN_FULFILLMENT` / `AT_RISK` / `RESOLVED` | 六个状态都能在界面上出现 | 待测 |
| `consumer_input_required` | 布尔 | `DEMO_001` 为 `false` | 待测 |
| `accountable_side` | `CONSUMER` / `BRAND` / `UNKNOWN` | `DEMO_001` 为 `BRAND` | 待测 |
| `evidence_status` | `VALID` / `MISMATCHED` / `NEED_HUMAN_REVIEW` | 三个案例各一种 | 待测 |
| `prohibited_actions` | 五项枚举 | `DEMO_001` 含 `ASK_SAME_EVIDENCE` | 待测 |
| `experience_gap_diagnosis` | 七个必填子字段 | 全部非空 | 待测 |
| `experience_gap_diagnosis.action_impacts` | 六项枚举 | `DEMO_001` 含 `BLOCK_REPEAT_EVIDENCE`、`CHECK_EXISTING_FULFILLMENT` 等 | 待测 |
| `open_obligation` | 对象或 `null` | 人工确认后非空；类型固定 `REPLACEMENT_FULFILLMENT`，责任方固定 `BRAND` | 待测 |
| `open_obligation.milestone` | `AWAITING_CARRIER_PICKUP` / `IN_TRANSIT` / `DELIVERED` | 随事件变化 | 待测 |
| `open_obligation.resolution_condition` | 固定 `REPLACEMENT_DELIVERED` | 核对 | 待测 |
| `service_progress_receipt` | 对象或 `null` | 人工确认后非空，含五个消费者可见要素 | 待测 |
| `service_progress_receipt` 隐私 | 不显示内部责任人、风险分数、情绪标签、推理过程 | 逐字段检查 | 待测 |
| `experience_risk` | `LOW` / `MEDIUM` / `HIGH` | 随事件变化 | 待测 |
| `audit_trail[]` | 每次变更留痕，含 `at` / `actor` / `action` / `changed_fields` / `request_id` | 每步操作后长度增加 | 待测 |

---

## 5. `decision-result.schema.json`

| 字段 | 检查动作 | 期望 | 状态 |
|---|---|---|---|
| `decision` | 三选一 | 三个案例各一种 | 待测 |
| `rule_id` | 五选一 | `E1` / `E2` / `H1` | 待测 |
| `rule_priority` | 五选一 | `300` / `100` / `200` | 待测 |
| 规则联动约束 | Schema 内 `allOf` 强制 | `E1→INTERVENE/300`、`E2→ALLOW/100`、`H1→HUMAN_REVIEW/200`、`P0→INTERVENE/400`、`E0→ALLOW/0` | 待测 |
| `accountability_state` | 服务端计算，随响应返回 | 不接受前端提交 | 待测 |
| `challenge_mode` | 布尔，变体时回显 `true` | 界面显示角标 | 待测 |
| `fact_trace` | 四个字段齐备 | 每字段可由本请求算出 | 待测 |
| `fact_trace.suppressed_rule_ids` | 被压制规则 | 多规则命中时非空 | 待测 |
| `reason` | 中文原因，说清为什么 | 不是模板套话 | 待测 |
| `resolution_path.candidate_type` | 三选一 | 与决策匹配 | 待测 |
| `resolution_path.policy_basis` | 非空 | 指向演示政策 | 待测 |
| `resolution_path.consumer_reply_draft` | 非空 | 可直接给客服使用 | 待测 |
| `resolution_path.task_prefill` | 四字段 | 含任务类型与摘要 | 待测 |
| `resolution_path.creates_obligation` | 布尔 | `DEMO_001` 为 `true` | 待测 |
| `compiled_service_responsibility` | 对象或 `null` | `DEMO_001` 非空 | 待测 |

---

## 6. `api-envelope.schema.json`

| 检查项 | 通过标准 | 状态 |
|---|---|---|
| 成功响应 | `data` 非空且 `error: null` | 待测 |
| 失败响应 | `data: null` 且 `error` 为对象 | 待测 |
| `request_id` | 成功和失败都必须有 | 待测 |
| `error.code` / `message` / `retryable` | 三字段齐全 | 待测 |
| 前端判定 | 只依据 `error.code`，不从自然语言消息里解析状态 | 待测 |
