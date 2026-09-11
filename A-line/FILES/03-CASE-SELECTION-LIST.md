# A-03｜标注字段定义与标注规范

对应任务：`TEAM_AND_TIMELINE.md` 9/5–9/11「首批标注」
上游依据：`docs/06-evaluation-and-research.md` 第 3 节（30 例标注要求）、`docs/03-firewall-rules.md`（规则与优先级）、`schemas/`
标注产物：`03-首批标注-20例.json`、`03-首批标注-20例.csv`、`03-案例选择清单.json`

---

## 1. 使用边界（先读这一节）

标注文件是 **Ground Truth**，只用于运行完成后的评测。

```text
✅ 允许：D 线比对运行结果、Claude 独立验收、团队复盘错误案例
❌ 禁止：传入模型 Prompt、传入状态构建器、传入体验防线规则、作为任何接口的运行输入
```

依据：`docs/06-evaluation-and-research.md` 第 6 节「Ground Truth 不进入模型或运行输入」，以及 `fixtures/README.md` 对 `ground-truth.json` 的同类约束。本标注集与 `fixtures/ground-truth.json` 是**两个独立文件**：后者只覆盖 `DEMO_001`–`DEMO_003` 三个演示案例，前者覆盖 20 个赛事原始会话。二者不要合并。

---

## 2. 标注单元与文件结构

### 2.1 标注单元

一个标注单元 = 一个赛事会话 = 一个 `case_id`。

不跨会话合并，不把一个会话拆成多条。原因：赛事数据保证「一个会话最多一笔订单、最多一张工单」，会话是唯一稳定的一对一锚点。

### 2.2 文件结构

```json
{
  "annotation_set_id": "A_FIRST_BATCH_20",
  "version": "0.1.0",
  "generated_at": "2026-09-10",
  "ground_truth_notice": "…",
  "labeling_rules_version": "A-LABELING-1.0.0",
  "data_labels": { },
  "coverage_summary": { },
  "cases": [ { } ]
}
```

### 2.3 单例结构（字段顺序即推荐阅读顺序）

```json
{
  "annotation_id": "ANN_DEV_01",
  "case_id": "S00001",
  "split": "DEV_REGRESSION | HELD_OUT",
  "is_hero": true,
  "scene": { "major": "…", "minor": "…" },
  "source_trace": { },
  "known_facts": { },
  "existing_evidence": { },
  "evidence_coverage": { },
  "promise_annotations": [ ],
  "journey_annotation": { },
  "responsibility": { },
  "prohibited_actions": [ ],
  "recommended_resolution": { },
  "reference_prepared_action": { },
  "expected_decision": { },
  "challenge_variants": [ ],
  "annotation_meta": { }
}
```

---

## 3. 字段字典

### 3.1 来源追踪 `source_trace`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source_trace.dataset` | const | 是 | `TIANCHI_LOREAL_TRACK1_MOCK` |
| `source_trace.session_id` | string | 是 | 赛事会话 ID |
| `source_trace.chat_rows` | string | 是 | 如 `聊天记录!A2:R7`（含表头行号） |
| `source_trace.order_rows` | string \| null | 否 | 如 `订单!A45:S45`；无订单为 null |
| `source_trace.ticket_rows` | string \| null | 否 | 如 `补发换货工单!A10:S10`；无工单为 null |
| `source_trace.image_reference_paths` | string[] | 是 | 原始 `image_path` 字符串，无图片则空数组 |

### 3.2 已知事实 `known_facts`

对应 `docs/06` 第 3 节「已知事实与已有证据」，也对应第一屏「已经知道什么」。

| 字段 | 类型 | 取值 | 判定依据 |
|---|---|---|---|
| `known_facts.order_verified` | boolean | — | 会话能关联到订单表记录 |
| `known_facts.issue_explained` | boolean | — | 消费者在聊天中说明了问题类型 |
| `known_facts.evidence_submitted` | boolean | — | 该会话存在图片消息 **或** 工单已记录证据事实 |
| `known_facts.statements` | string[] | — | 从聊天原文摘录的客观事实，**不得包含推断** |
| `known_facts.system_facts` | string[] | — | 来自订单表与工单表的事实，**优先级最高** |

写法要求：`statements` 只写消费者或客服说过的、可回指到具体消息的内容；`system_facts` 只写订单与工单字段值。

### 3.3 已有证据 `existing_evidence`

对应「已有证据」，回答「消费者已经交过什么」。

| 字段 | 类型 | 说明 |
|---|---|---|
| `existing_evidence.has_image` | boolean | 该会话是否有图片消息 |
| `existing_evidence.evidence_items` | object[] | 每条含 `evidence_ref`、`source_message_id`、`image_path_category`、`submitted_at` |
| `existing_evidence.evidence_closed` | boolean | 证据链是否已闭合到可支撑当前动作 |

`evidence_items[].image_path_category` 取 `image_path` 的目录名，只作粗分类线索，见 3.4 的说明。

### 3.4 证据覆盖 `evidence_coverage`

对应「证据覆盖范围和缺失项」。

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| `coverage.annotation_level` | enum | `PATH_REFERENCE_ONLY` / `TEAM_IMAGE_OBSERVED` | 首批标注一律为 `PATH_REFERENCE_ONLY` |
| `coverage.covered` | enum[] | `PRODUCT_IDENTITY`、`AFFECTED_COMPONENT`、`DAMAGE_DETAIL`、`PACKAGE_CONTEXT`、`BATCH_LABEL` | 已覆盖项 |
| `coverage.missing` | enum[] | 同上 | 缺失项 |
| `coverage.scope_consistency` | enum | `IN_SCOPE` / `OUT_OF_SCOPE` / `UNDETERMINED` | 证据范围与当前问题是否一致 |
| `coverage.expected_evidence_status` | enum | `VALID` / `MISMATCHED` / `NEED_HUMAN_REVIEW` | 规则输入的目标值 |
| `coverage.note` | string | — | 判定理由，必须能回指消息或路径 |

**标注级别说明（重要）：** 赛事工作簿只有 `image_path` 引用、没有图片文件。因此首批标注**不能**声称知道图片里有什么。`PATH_REFERENCE_ONLY` 表示：覆盖项由「聊天文本说明 + 路径目录线索」推定，属于待验证假设；团队合成素材就绪后，由多模态模型产出 `ImageObservation`，再由标注人复核并升级为 `TEAM_IMAGE_OBSERVED`。

### 3.5 承诺 `promise_annotations[]`

对应「承诺原文、承诺类型和生效状态」。**只允许来自 `角色 = 客服` 的消息。**

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| `raw_text` | string | — | 客服消息原文，逐字摘录 |
| `source_message_id` | string | — | 对应 `message_id` |
| `committed_at` | date-time | — | 消息发送时间 + `+08:00` |
| `promise_type` | string | 如 `REPLACEMENT_FULFILLMENT`、`REFUND_OFFLINE_PAYMENT`、`RETURN_ACCEPTANCE`、`POLICY_STATEMENT`、`GOODWILL_GIFT`、`SERVICE_UPDATE_TIMING` | 自由文本，但同一含义必须用同一写法 |
| `commitment_class` | enum | `STANDARD_APPROVED` / `APPROVAL_REQUIRED` / `CONDITIONAL` / `ERRONEOUS_OR_UNAUTHORIZED` / `AMBIGUOUS` | 与 Schema 一致 |
| `activation_status` | enum | `ACTIVE` / `PENDING_APPROVAL` / `BLOCKED` / `IGNORED` | **规则与人工确认后的编译结果** |
| `deadline` | date-time \| null | — | 仅 `ACTIVE` 且原文给出确定时间时填写 |
| `conditions` | string[] | — | `CONDITIONAL` 必须至少一项 |
| `confidence` | number | 0–1 | 标注人对该分类的确信度 |

分类判定表：

| 判据 | `commitment_class` | `activation_status` |
|---|---|---|
| 有工单或标准动作支撑的确定承诺 | `STANDARD_APPROVED` | `ACTIVE` |
| 涉及退款 / 赔偿 / 医疗费用 / 越权让利 | `APPROVAL_REQUIRED` | `PENDING_APPROVAL` |
| 带「若…就…」「核实后…」条件 | `CONDITIONAL` | `PENDING_APPROVAL` |
| 与系统事实冲突或明显越权 | `ERRONEOUS_OR_UNAUTHORIZED` | `BLOCKED` |
| 「尽快」「第一时间」「马上」等无确定时间 | `AMBIGUOUS` | `IGNORED`，`deadline` 必须为 null |

易错点，标注时必须检查：

1. **句内自我更正**：`S00023` 第 7 条先写「顺丰到付」再改为「顺丰包邮」，以最终语义为准，不得整句判为越权。
2. **消费者消息中的承诺**：消费者转述或伪造的承诺**不产生** `promise_annotations` 条目（对应验收 A25）。
3. **`CONDITIONAL` 与 `AMBIGUOUS` 的区分**：有明确触发条件的是 `CONDITIONAL`；只有模糊时间词的是 `AMBIGUOUS`。二者可以同时出现在同一条消息的不同承诺里。
4. **同一会话多条承诺**：逐条标注，不合并。

### 3.6 旅程理解 `journey_annotation`

对应「消费者意图、体验成因与潜在需求」，字段与 `ExtractedJourney.journey_understanding` 同名同义。

| 字段 | 类型 | 取值 |
|---|---|---|
| `consumer_intent` | string | 消费者想达成什么 |
| `experience_expression` | string | 体验表达的原文摘录 |
| `service_cause` | string | 引发体验恶化的服务事件（不是情绪描述） |
| `latent_need` | string | 未说出口但可推断的需求 |
| `cooperation_willingness` | enum | `STABLE` / `DECLINING` / `LOW` / `UNKNOWN` |
| `action_impact` | string | 对优先级与下一动作的影响 |
| `source_ids` | string[] | 支撑上述判断的 `message_id` |

判定 `cooperation_willingness` 的口径：

| 取值 | 触发信号 |
|---|---|
| `STABLE` | 无明显负面情绪，配合说明 |
| `DECLINING` | 出现抱怨、质疑、催促、要求重复说明 |
| `LOW` | 明确提出投诉、平台介入、监管渠道 |
| `UNKNOWN` | 会话过短，无法判断 |

### 3.7 服务责任 `responsibility`

对应「待履行责任」。

| 字段 | 类型 | 取值 |
|---|---|---|
| `creates_obligation` | boolean | 是否产生可追踪服务责任 |
| `obligation_type` | enum \| null | **标注层**取值：`REPLACEMENT_FULFILLMENT` / `OFFLINE_PAYMENT` / `RETURN_HANDLING` / `ADVERSE_REACTION_HANDOFF` / null |
| `responsible_party` | enum \| null | `BRAND` / null |
| `executor` | string \| null | 赛事工单中的仓库或执行方 |
| `current_milestone` | enum \| null | `AWAITING_CARRIER_PICKUP` / `IN_TRANSIT` / `DELIVERED` / null |
| `next_check_at` | date-time \| null | 下次检查时间 |
| `completion_condition` | string \| null | 真正的完成条件（不是工单创建） |

硬约束：`工单创建 ≠ 已发出 ≠ 已揽收 ≠ 已送达`。`completion_condition` 不得写成「工单已创建」或「已生成物流单号」。

**与契约的差异（必须知道）：** `schemas/accountability-state.schema.json` 的 `open_obligation.obligation_type` 是 `const: "REPLACEMENT_FULFILLMENT"`，`resolution_condition` 是 `const: "REPLACEMENT_DELIVERED"`，`executor` 枚举只有 `BRAND` / `WAREHOUSE` / `LOGISTICS_PROVIDER`。也就是说 **P0 账本只支持补发换货一类的责任**；标注层的 `OFFLINE_PAYMENT`、`RETURN_HANDLING`、`ADVERSE_REACTION_HANDOFF` 描述的是案例中实际存在的服务责任种类，写回契约时需要产品负责人确认扩展口径。本批处理方式：这类案例的 `case_status` 取最接近的 P0 口径（多为 `ACTION_REVIEW`），并在 `expected_ledger_assertions.note` 中标注。

### 3.7.1 预期账本断言 `expected_ledger_assertions`

**本字段用于关闭 `CLAUDE-REVIEW-1.md` 的 B17 缺口**：原 `fixtures/ground-truth.json` 未断言 `case_status`、`prohibited_actions`、`next_check_at`、`consumer_input_required`，这些字段缺少验收基线。本批 20 例全部补齐。

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| `case_status` | enum | 六个业务状态之一 | 见 `docs/00-product-p0.md` 第 6 节 |
| `consumer_input_required` | boolean | — | 消费者是否还需要继续输入 |
| `next_check_at` | date-time \| null | — | 与 `responsibility.next_check_at` 必须一致 |
| `prohibited_actions` | enum[] | 同 3.8 | 与案例的 `prohibited_actions` 必须一致 |
| `note` | string | — | 跨类型责任的口径说明 |

### 3.8 禁止动作 `prohibited_actions[]`

以 `schemas/accountability-state.schema.json` 的**五值枚举**为准：

| 取值 | 含义 | `docs/03` 映射表是否列出 |
|---|---|---|
| `ASK_SAME_EVIDENCE` | 同一范围下重复索证 | 是 |
| `ASK_REPEAT_EXPLANATION` | 要求消费者重新说明已知问题 | 是 |
| `SHIFT_FOLLOW_UP_TO_CONSUMER` | 把履约跟进推回消费者 | 是 |
| `MAKE_UNTRACKABLE_PROMISE` | 未经审批、与系统事实冲突或无法跟踪的新承诺 | **否** |
| `CLOSE_BEFORE_RESOLUTION` | 完成条件未满足时结案 | 是 |

**契约缺口（需产品负责人统一）：** `docs/03-firewall-rules.md` 的「禁止动作拦截」表只列了 4 项，Schema 有 5 项。本标注集按 Schema 的 5 值枚举使用；`MAKE_UNTRACKABLE_PROMISE` 目前没有对应的受阻动作映射。

### 3.9 参考动作 `reference_prepared_action`

**这是让 `expected_decision` 具备唯一解的必要字段。** 规则输出取决于「证据状态」与「待执行动作」的组合，只给证据状态无法确定决策。

| 字段 | 类型 | 取值 |
|---|---|---|
| `action_type` | enum | **`ASK_EVIDENCE` / `CHECK_REPLACEMENT_PROGRESS` / `CREATE_FOLLOW_UP_TASK` / `CLOSE_CASE`**（与 `schemas/prepared-action.schema.json` 完全一致，不得新增取值） |
| `requested_scope_sku_id` | string | 该动作针对的商品货号 |
| `requested_scope_issue_type` | enum | `PACKAGE_DAMAGE` / `LOGISTICS_STALLED` / `ADVERSE_REACTION` |
| `requires_human_approval` | boolean | — |
| `rationale` | string | 为什么用这个参考动作来测该案例 |

**范围展开规则：** 标注中为简化只写 `requested_scope_sku_id` 与 `requested_scope_issue_type`；使用时按确定性规则展开为完整 `requested_scope`：

```text
requested_scope = {
  order_id:            该案例的 order.order_id,
  fulfillment_item_id: "{order_id}-{sku_id}",
  sku_id:              requested_scope_sku_id,
  issue_type:          requested_scope_issue_type
}
```

依据：`schemas/prepared-action.schema.json` 规定 `action_type = ASK_EVIDENCE` 时 `requested_scope` 必填。

默认口径：**对适合索证的案例统一使用「客服准备再次索取同一范围的证据」（`ASK_EVIDENCE`，范围 = `current_issue`）**，这样案例之间可以直接比较，也最贴近 `S00001` 的真实痛点。对不适合该动作的案例（咨询、退款、退货流程类）使用 `CHECK_REPLACEMENT_PROGRESS`，并在 `rationale` 中说明。

### 3.10 预期决策 `expected_decision`

| 字段 | 类型 | 取值 |
|---|---|---|
| `decision` | enum | `INTERVENE` / `ALLOW` / `HUMAN_REVIEW` |
| `rule_id` | enum | `P0_PROHIBITED_ACTION` / `E1` / `H1` / `E2` / `E0_NO_RULE_MATCHED` |
| `rule_priority` | int | `400` / `300` / `200` / `100` / `0` |
| `suppressed_rule_ids` | enum[] | 同时命中的较低优先级规则 |
| `evidence_status` | enum | `VALID` / `MISMATCHED` / `NEED_HUMAN_REVIEW` |
| `reason_zh` | string | 中文原因，界面可直接引用 |

**推荐解决路径 `recommended_resolution.candidate_type` 的取值说明：** 标注层使用更细的建议类型（便于人读懂该案例该做什么）；`schemas/decision-result.schema.json` 的 `resolution_path.candidate_type` 只有三个合法值。使用时按下表映射：

| 标注层 `candidate_type` | 契约值 |
|---|---|
| `CHECK_REPLACEMENT_FULFILLMENT` | `CHECK_REPLACEMENT_FULFILLMENT` |
| `CHECK_REPLACEMENT_PROGRESS` | `CHECK_REPLACEMENT_FULFILLMENT` |
| `ASK_CURRENT_SCOPE_EVIDENCE` | `ASK_CURRENT_SCOPE_EVIDENCE` |
| `RETURN_FLOW_GUIDANCE` | `ASK_CURRENT_SCOPE_EVIDENCE` |
| `HUMAN_EVIDENCE_REVIEW` | `HUMAN_EVIDENCE_REVIEW` |
| `HUMAN_ADVERSE_REACTION_HANDOFF` | `HUMAN_EVIDENCE_REVIEW` |
| `VERIFY_EMPTY_PARCEL_CLAIM` | `HUMAN_EVIDENCE_REVIEW` |
| `OFFLINE_PAYMENT_REVIEW` | `HUMAN_EVIDENCE_REVIEW` |

同一映射表也已写入 `03-首批标注-20例.json` 的 `contract_value_mapping` 节点，供 D 线直接读取。

判定顺序（**必须按此顺序，命中即停**）：

| 顺序 | 规则 | 优先级 | 条件 | 输出 |
|---:|---|---:|---|---|
| 1 | `P0_PROHIBITED_ACTION` | 400 | `prohibited_actions` 含任一禁止项且动作对应受阻 | `INTERVENE` |
| 2 | `E1` | 300 | `evidence_status = VALID` 且动作 = `ASK_EVIDENCE` 且范围一致 | `INTERVENE` |
| 3 | `H1` | 200 | `evidence_status = NEED_HUMAN_REVIEW` 或 `issue_type = ADVERSE_REACTION` | `HUMAN_REVIEW` |
| 4 | `E2` | 100 | `evidence_status = MISMATCHED` 且动作 = `ASK_EVIDENCE` | `ALLOW` |
| 5 | `E0_NO_RULE_MATCHED` | 0 | 以上均未命中 | `ALLOW` |

### 3.11 挑战变体 `challenge_variants[]`

对应 `TEAM_AND_TIMELINE.md` 与 `docs/07-demo-and-delivery.md` 要求的 Challenge Mode。每条变体包含：

| 字段 | 说明 |
|---|---|
| `variant_id` | 如 `VAR_RANGE_GIFT` |
| `description` | 改变了什么输入 |
| `change` | 具体改动（字段、原值、新值） |
| `expected_decision` / `expected_rule_id` | 变体下的预期输出 |
| `expected_effect` | 期望模型输出发生什么变化 |

至少覆盖 6 类变体：范围变化、图片模糊、承诺改「尽快」、消费者消息伪造承诺、物流状态改变、未揽收直接送达。

### 3.12 标注元信息 `annotation_meta`

| 字段 | 类型 | 取值 |
|---|---|---|
| `annotator` | string | 标注人代号（当前为 A 线） |
| `annotated_at` | date | 标注日期 |
| `confidence` | enum | `HIGH` / `MEDIUM` / `LOW` |
| `review_status` | enum | `FIRST_PASS` / `SECOND_REVIEWED` / `CONFLICT` |
| `open_questions` | string[] | 存疑点，供复审与产品负责人裁决 |

---

## 4. 与 `docs/06` 标注要求的对应关系

| `docs/06` 第 3 节要求 | 本规范字段 |
|---|---|
| 已知事实与已有证据 | `known_facts`、`existing_evidence` |
| 证据覆盖范围和缺失项 | `evidence_coverage.covered` / `.missing` |
| 承诺原文、承诺类型和生效状态 | `promise_annotations[]` |
| 消费者意图、体验成因与潜在需求 | `journey_annotation` |
| 待履行责任、禁止动作和推荐解决路径 | `responsibility`、`prohibited_actions`、`recommended_resolution` |

---

## 5. 抽样与分组规则

### 5.1 防泄漏分组

赛事数据里同一 `scene_minor` 的多个会话共用同一套客服话术模板（见 `01-数据字段确认.md` 6.4）。为避免同模板泄漏导致评测虚高：

1. 先按 `scene_minor` 分组；
2. 同一模板在**开发集最多 2 例**，其余放入留出集；
3. 留出集在开发期对 B、C 线不可见，由非开发成员保管；
4. 留出集只在 9/19–9/25 第二批标注时补全答案。

### 5.2 覆盖要求（已由 `03-案例选择清单.json` 的 `coverage_matrix` 逐项核验）

| 维度 | 要求 |
|---|---|
| 工单类型 | 五类各至少 2 例 |
| 工单状态 | 已完结与非完结都要有 |
| 决策 | `INTERVENE`、`ALLOW`、`HUMAN_REVIEW` 三值全覆盖 |
| 规则 | `E1`、`E2`、`H1`、`E0_NO_RULE_MATCHED` 全覆盖；`P0_PROHIBITED_ACTION` 由变体覆盖 |
| 承诺分类 | 五类全覆盖 |
| 图片目录 | 10 个类别全覆盖 |
| 会话结构 | 含无订单会话、无工单会话各至少 1 例 |

### 5.3 留出集纪律

- 留出集案例 ID 已锁定（见 `03-案例选择清单.json` 的 `held_out`），但不提供答案。
- 留出集不得用于调 Prompt、调规则、调阈值。
- 留出集答案在第二批标注完成后单独存放，并在 D 线验收时与开发集分开统计。

---

## 6. 质检与复审

### 6.1 第一遍标注（本批）

标注人：A 线。
产出：`review_status = FIRST_PASS`。
已知限制：证据覆盖为路径级推定，`confidence` 对依赖图片的案例最高只给 `MEDIUM`。

### 6.2 第二遍复审（9/12–9/18）

由**非标注人**执行，逐例检查：

| 检查项 | 通过标准 |
|---|---|
| 来源定位 | 每个 `source_trace` 能在工作簿中命中 |
| 承诺来源 | 所有 `promise_annotations[].source_message_id` 的 `角色` 均为客服 |
| 决策推演 | 用 `evidence_coverage.expected_evidence_status` + `reference_prepared_action` 按 3.10 的表重推，结果与 `expected_decision` 一致 |
| 责任口径 | `completion_condition` 不是「工单创建」或「已生成单号」 |
| 标签一致性 | 同一 `scene_minor` 的同类案例使用同一 `promise_type` 写法 |
| 来源分离 | `COMPETITION_MOCK` 与 `DEMO_AUGMENTATION` 未混用 |

复审后 `review_status` 改为 `SECOND_REVIEWED`；有分歧的改为 `CONFLICT` 并写入 `open_questions`，提交产品负责人裁决。

### 6.3 与运行结果的比对（9/26 之后）

按 `docs/06` 第 4 节的核心指标统计：

- 证据复用判断正确率
- 合理重新索证放行率
- 承诺抽取与类型分类正确率
- 禁止动作判断正确率
- 物流事件后的状态与动作正确率

小样本逐案例展示，**不得**包装为生产准确率。

---

## 7. 版本与变更记录

| 版本 | 日期 | 变更 | 影响 |
|---|---|---|---|
| A-LABELING-1.0.0 | 2026-09-10 | 首版：字段字典、判定顺序、抽样规则、质检流程 | 首批 20 例标注依据 |

字段若需变更，必须同步更新 `03-首批标注-20例.json` 的 `labeling_rules_version`，并在群内同步后再修改，符合 `TEAM_AND_TIMELINE.md` 第 5 节协作约定。
