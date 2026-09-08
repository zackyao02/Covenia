# 05｜接口与千牛右侧插件

## 1. 契约基线

四个接口不增加。`schemas/` 中的请求 Schema、领域 Schema 和本文件共同构成唯一实现基线。

所有响应使用统一外层：`{data, error, request_id}`。成功时 `error: null`；失败时 `data: null`，并给出机器可读的 `error.code`、面向开发的 `error.message` 与 `error.retryable`。`request_id` 在成功和失败时都必填，用于日志与审计关联。

| 接口 | 请求 Schema | 成功 `data` | 关键错误 |
|---|---|---|---|
| `POST /api/cases/analyze` | `analyze-case-request.schema.json` | `ExtractedJourney`、`AccountabilityState`、`model_metadata` | `SCHEMA_INVALID`、`MODEL_UNAVAILABLE`、`MODEL_OUTPUT_INVALID` |
| `POST /api/actions/evaluate` | `evaluate-action-request.schema.json` | `DecisionResult` | `SCHEMA_INVALID`、`E0_NO_RULE_MATCHED` |
| `POST /api/resolutions/approve` | `approve-resolution-request.schema.json` | 更新后的账本、`approved_resolution`、`audit_trail` | `VALIDATION_ERROR`、`IDEMPOTENCY_CONFLICT` |
| `POST /api/events/shipment` | `shipment-event-request.schema.json` | 更新后的账本、催办候选、通知草稿 | `INVALID_EVENT_TRANSITION`、`IDEMPOTENCY_CONFLICT` |

错误、幂等和时序的完整定义见 `docs/08-idempotency-and-ordering.md`。

## 2. 分析案例

`POST /api/cases/analyze`

可信输入为 `{case_id, evaluation_time?, challenge_mode?, case_input?}`。后端按 `case_id` 从赛事数据装载事实；仅在 `challenge_mode: true` 时允许 `case_input` 作为演示变体。承诺候选仅来自 `speaker: AGENT` 的消息，敏感字段先掩码再送入模型。

模型失败时可返回缓存结果，但必须在响应的 `model_metadata.cached_result`、界面角标和治理记录三处同时可见。

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

## 6. 千牛布局约束

赛事说明中的右侧辅助区是插件目标区域。Competition MVP 按约 360–420px 的窄栏设计，并保留中部聊天区和底部客服输入区。插件不覆盖消费者对话，也不要求客服跳转独立系统。

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

## 9. 消费者端表达与轻量管理区

消费者只看到已收到什么、正在做什么、何时更新、未完成时如何处理及是否仍需操作。内部责任人、情绪标签、风险分数和推理过程不展示。

不开发独立 BI 大屏。可展示 80 条五类工单和 28 条非完结工单等赛事 Mock 数据事实；“重复索证风险”只能是明确标记的人工标注测试假设。

## 10. 交互约束

- 1366×768 下无需滚动即可看到判断、原因和首要动作。
- 警告只在高价值动作前出现，避免提醒疲劳。
- 颜色不作为唯一状态表达。
- 默认不展示 JSON、置信度小数或内部责任人姓名。
- “赛事 Mock 数据＋团队压力测试扩充”固定可见一次。
