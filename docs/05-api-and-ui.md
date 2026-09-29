# 05｜接口与千牛右侧插件

## 1. 契约基线

v0.8 BC Core 保留四个写入/评估接口；v1.1 为 Customer Extension 与独立运营态增加六个只读或受控执行 API。`schemas/` 中的请求 Schema、领域 Schema 和本文件共同构成唯一实现基线。

所有响应使用统一外层：`{data, error, request_id}`。成功时 `error: null`；失败时 `data: null`，并给出机器可读的 `error.code`、面向开发的 `error.message` 与 `error.retryable`。`request_id` 在成功和失败时都必填，用于日志与审计关联。

| 接口 | 请求 Schema | 成功 `data` | 关键错误 |
|---|---|---|---|
| `POST /api/cases/analyze` | `analyze-case-request.schema.json` | `ExtractedJourney`、`AccountabilityState`、`model_metadata`、`runtime_metrics` | `SCHEMA_INVALID`、`MODEL_UNAVAILABLE`、`MODEL_OUTPUT_INVALID` |
| `POST /api/actions/evaluate` | `evaluate-action-request.schema.json` | `DecisionResult`（含 `runtime_metrics`） | `SCHEMA_INVALID`、`E0_NO_RULE_MATCHED` |
| `POST /api/resolutions/approve` | `approve-resolution-request.schema.json` | 更新后的账本、`approved_resolution`、`audit_trail` | `VALIDATION_ERROR`、`IDEMPOTENCY_CONFLICT` |
| `POST /api/events/shipment` | `shipment-event-request.schema.json` | 更新后的账本、催办候选、通知草稿 | `INVALID_EVENT_TRANSITION`、`IDEMPOTENCY_CONFLICT` |

错误、幂等和时序的完整定义见 `docs/08-idempotency-and-ordering.md`。

## 1.1 v1.1 新增 API

新增 API 统一使用 `{data, error, request_id}` 外层，且不得让前端提交最终风险、优先级或决策结论。

| API | 方法 | 返回/作用 | 主要消费者 |
|---|---:|---|---|
| `/api/customer-state/:case_id` 或 `/customer-state` | GET | Customer Extension：`CustomerState`，含 Intent/Emotion/Effort/Risk/Decision/Deadline | Customer Workspace、Handoff |
| `/api/risk` 或 `/risk` | GET | Customer Extension：`RiskState[]`，单个消费者风险状态，非预测 | Risk Radar、Priority |
| `/api/priority` 或 `/priority` | GET | Aggregate / Operational State：`PriorityState[]` | Priority Queue、Customer Switching |
| `/api/emerging-issues` 或 `/emerging-issues` | GET | Aggregate / Operational State：`EmergingIssue[]`，固定 `requires_human_confirmation` 与 `prediction:false` | Risk Radar、管理区 |
| `/api/decisions` 或 `/decisions` | POST | Customer Extension：对动作返回轻量 `Decision` 或完整 `DecisionResult` | 发送前防线、人工确认 |
| `/api/deadlines` 或 `/deadlines` | GET/POST | Customer Extension：查询 DeadlineState；演示环境可手动触发一次 Monitor | Promise-to-Action、主管跟踪 |

推荐兼容路径为 `/api/*`；文档中的短路径用于产品表达。生产实现应保留鉴权、租户、审计和来源限制，本地比赛 Demo 可使用 Mock。

### `/customer-state`

输入：`case_id`。输出：`CustomerState`。

它消费 Raw Sources、ExtractedJourney、AccountabilityState、RiskState、Decision 和 DeadlineState。前端只读，不允许提交完整 CustomerState。PriorityState、EmergingIssue 和 Risk Radar 不嵌入 CustomerState。

### `/risk`

输出：按 `score` 降序的 `RiskState[]`。情绪标签不进入分数；展示时必须说明“运营分流，非投诉/流失/质量预测”。

### `/priority`

输出：`PriorityState[]`。排序依据为 Risk、Deadline、等待时间、承诺状态和人工复核需求。Priority 只决定先处理谁，不改变业务事实。

### `/emerging-issues`

输出：`EmergingIssue[]`。指纹为 `sku_id + affected_component + issue_type`；同一消费者重复上报不能增加独立消费者数。

### `/decisions`

输入：`case_id + prepared_action`。它可以复用 `POST /api/actions/evaluate` 的实现，也可以返回轻量 `Decision`。最终决策仍由规则、Jev 受限判断和人工确认共同约束，前端不得自行判定。

### `/deadlines`

`GET` 返回当前 DeadlineState；`POST /run` 在演示或测试中触发一次 Deadline Monitor。Monitor 只处理已经人工确认进入运行态的 Promise。

## 2. 分析案例

`POST /api/cases/analyze`

可信输入为 `{case_id, evaluation_time?, challenge_mode?, case_input?}`。后端按 `case_id` 从赛事数据装载事实；仅在 `challenge_mode: true` 时允许 `case_input` 作为演示变体。承诺候选仅来自 `speaker: AGENT` 的消息，敏感字段先掩码再送入模型。

模型失败时可返回缓存结果，但必须在响应的 `model_metadata.cached_result`、界面角标和治理记录三处同时可见。

每个 `analyze` 与 `evaluate` 成功响应还必须返回服务端生成的 `runtime_metrics`：`input_tokens`、`output_tokens`、`inference_latency_ms`、`rule_substitution_count`。右下成本条只展示这些响应值，不在前端估算。

## 3. 评估动作

`POST /api/actions/evaluate`

可信输入为 `{case_id, prepared_action, evaluation_time?, challenge_mode?, challenge_overrides?}`。服务端按 `case_id` 装载事实，并自行计算 `evidence_status`、`active_commitments`、`prohibited_actions` 与 `current_scope`。

请求中出现 `accountability_state`、`evidence_status`、`active_commitments`、`prohibited_actions` 或 `current_scope` 时，兼容层记录为忽略字段，不参与规则计算。变体只能通过受限的 `challenge_overrides` 给出，且必须显式启用 `challenge_mode: true`；成功响应回显该标志，右栏显示“Challenge Mode”角标。

按 `case_id` 装载事实不等于按案例编号返回固定结果：规则函数、状态推导与 Prompt 模板中不得出现案例编号分支。

## 4. 人工确认解决路径

`POST /api/resolutions/approve`

请求必须含 `case_id`、`candidate_type`、`approver_id`、`idempotency_key` 与受限的 `human_edits`。后端使用服务端时间写 `approved_at`，从允许的编辑字段合并出 `approved_resolution`，并追加 `audit_trail`。前端提交的 `approved_at`、完整责任账本或最终解决路径均不采信。

主动通知草稿由字段模板渲染，`text` 内的下次更新时间必须等于 `commits_next_update_at`；不允许模型自由生成第二个时间承诺。

## 5. 推送物流事件

`POST /api/events/shipment`

请求必须含 `case_id`、`event_id`、`event_type`、`event_time` 与 `idempotency_key`。只有 `PICKED_UP → DELIVERED` 能结案；未揽收直接送达、事件倒序和冲突重放均返回错误。状态转移定义见 `docs/04-responsibility-loop.md`。

接口数量不因服务进度回执增加；回执是账本的派生视图。

## 6. UI：Conversation + Customer Workspace

赛事说明中的右侧辅助区是插件目标区域。BC line 保留三栏工作台：左侧会话队列、中部 Conversation、右侧 Covenia Customer Workspace。插件不覆盖消费者对话，也不要求客服跳转独立系统。

v1.1 UI 从单一 sidebar 升级为：

```text
Conversation + Customer Workspace
Card → Focus View
Customer Switching
Priority Queue
Risk Radar
```

右侧工作区分两层：

1. 第一屏仍只回答“已经知道什么、现在不能做什么、下一步做什么”。
2. 新版工作区以明显视觉分区承载四层内容：BC Core 摘要、Customer Extension、Aggregate / Operational State、Model Governance 状态，避免与旧版 BC 区域混淆。

## 7. 第一屏只回答三个问题

### 已经知道什么

- 粉底液正装、商品货号与订单。
- 泵头损坏图片已提交，客服已确认包装破损。
- 换货工单已创建，承诺 48 小时内发出。

### 现在最不能做什么

- `发送已暂停：不要再次索取相同破损图片。`

### 下一步直接做什么

- 主按钮：`查询补发进度`。
- 次按钮：`生成解决回复`。
- 条件按钮：`提交仓库催办`。

完整旅程、AI 抽取、承诺分类、证据观察和规则来源全部折叠。

## 8. 两个连续界面状态

### 动作前状态

顶部突出 `INTERVENE / ALLOW / HUMAN_REVIEW`、一句中文原因和两个直接动作。挑战变体必须同时显示 `Challenge Mode`，缓存结果必须同时显示“缓存抽取结果”。

### 人工确认后状态

第一屏转为服务进度回执和责任倒计时，继续显示“消费者无需操作”、下次检查时间和异常补救策略。

## 8.1 Card → Focus View

卡片只显示结论、状态和一行动作；点击后进入 Focus View，展示来源、判断依据和边界：

- Evidence Focus：只列“已知证据 / 待补充证据 / 不要再问”，不再用复杂图表让客服重新判断。
- Emotion Focus：展示趋势、原因和沟通建议，明确不参与风险分。
- Promise Focus：展示承诺原文、DeadlineState、Monitor 状态和完成条件。
- Risk Focus：展示因素、权重和来源，不展示不可解释的模型黑箱分数。

## 8.2 Customer Switching 与 Priority Queue

Customer Switching 必须保留当前会话上下文，并在切换时清空上一位消费者的临时决策，防止旧决策短暂作用于新案例。

Priority Queue 展示排序原因，而不只是分数；必须至少包含承诺风险、等待、重复沟通、证据冲突或人工复核需求之一。

## 8.3 Risk Radar

Risk Radar 是内部运营视图：

- 默认按 `RiskState.score` 或 `PriorityState.rank` 排序。
- 每个风险因素必须显示来源或可解释原因。
- 情绪只作为沟通上下文，不直接加分。
- Emerging Issue 固定标明测试数据、人工确认和非预测边界。

## 9. 消费者端表达与轻量管理区

消费者只看到已收到什么、正在做什么、何时更新、未完成时如何处理及是否仍需操作。内部责任人、情绪标签、风险分数和推理过程不展示。

不开发独立 BI 大屏。可展示 80 条五类工单和 28 条非完结工单等赛事 Mock 数据事实；“重复索证风险”只能是明确标记的人工标注测试假设。

## 10. 交互约束

- 1366×768 下无需滚动即可看到判断、原因和首要动作。
- 警告只在高价值动作前出现，避免提醒疲劳。
- 颜色不作为唯一状态表达。
- 默认不展示 JSON、置信度小数或内部责任人姓名。
- “赛事 Mock 数据＋团队压力测试扩充”固定可见一次。
