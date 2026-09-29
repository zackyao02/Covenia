# 01｜数据映射与核心契约

完整产品对外统一使用“消费者体验责任账本（Experience Ledger）”。v1.1 起，前端和跨线联调用 `CustomerState` 作为 Customer Extension 视图，但它不替代账本：账本保存可追溯事实，Customer State 只新增 Intent、Emotion、Effort、Risk、Decision 和 Deadline。

完整分层：

```text
BC Core：Raw Sources → Experience Ledger → Evidence / Promise / Firewall / Resolution
Customer Extension：Intent / Emotion / Effort / RiskState / Decision / DeadlineState
Aggregate / Operational State：Priority Queue / Emerging Issue / Risk Radar
Model Governance：JEV Decision / Confidence / Threshold / Fallback / Audit
```

其中 Raw Sources 包括聊天、图片、订单、工单、物流、人工确认和系统事件。LLM/VLM 负责理解和候选抽取；确定性事实、责任状态、规则决策、Deadline Monitor 和优先级落地由代码/API 负责。

## 0. 对象生产、消费与修改权

| 对象 | 谁生产 | 谁消费 | 谁能修改 |
|---|---|---|---|
| Raw Sources | 导入器、业务 API、物流事件、人工确认 | 抽取器、账本构建器 | 原始来源不可改；只能追加人工修正 |
| SourceEvidence | 导入器、抽取器、规则引擎 | CustomerState、RiskState、Decision、审计 | 只能追加；不得覆盖原 source_id |
| CustomerState | 服务端状态构建器 | 右侧插件、Handoff | 前端只读；人工确认可通过受限接口追加修正 |
| EmotionState | LLM 从对话和事件中抽取 | 回复语气、Handoff | 人工可覆盖标签；不得直接改 Risk |
| RiskState | 规则引擎按等待、承诺、重复沟通、证据冲突计算 | Priority、Risk Radar、主管跟踪 | 代码/API 修改；Jev 只能提供受限模糊判断输入 |
| Decision | 体验防线服务 | 插件动作按钮、人工确认弹窗 | 规则和人工审批修改；前端不得提交最终决策 |
| PriorityState | Priority 服务 | Customer Switching、Priority Queue | 独立运营态；服务端按 Risk、Deadline、工单状态重算，不写回核心事实 |
| EmergingIssue | 聚类服务 | Risk Radar、管理区 | 独立运营态；仅人工确认后可变为 CONFIRMED |
| DeadlineState | Deadline Monitor | Promise-to-Action、Priority、Escalation | Monitor 和人工修正接口修改 |
| Resolution | 人工确认与责任闭环服务 | 消费者回复、服务进度回执、物流分支 | 人工确认和物流事件修改 |

## 1. 赛事数据导入

以字符串方式读取订单号、工单号、物流单号和消息 ID，避免长数字在 Excel 导入时转为科学计数法或丢失精度。

关联优先级：

1. `会话ID` 连接聊天、订单与五类工单。
2. `关联订单号` 进行订单一致性校验。
3. `关联工单号/工单号` 连接当前服务动作。
4. 买家昵称只用于辅助核对，不作为唯一主键。

29 条图片消息只有 `image_path` 引用，工作簿不含实际图片二进制。导入层必须保留原始路径和来源消息 ID；模型运行使用的团队图片另行标记来源。

## 2. CaseInput

原始输入包含：

- 数据来源、赛事会话 ID 与扩充说明。
- 原始聊天消息及消息 ID。
- 订单、正装/赠品、商品货号和物流单号。
- 已有关联工单及处理状态。
- 图片文件引用与数据来源。
- 当前评估时间和当前问题范围。

`CaseInput` 不包含承诺结论、证据最终状态、责任方或体验防线结果。承诺必须从原始聊天抽取。

## 3. ExtractedJourney

由唯一多模态模型输出：

- 消费者已完成动作。
- 图片中的商品、组件、问题可见性、证据覆盖和 SKU 匹配观察。
- 消费者意图、体验表达、服务成因和潜在需求。
- 服务承诺原文、承诺类型、条件、建议生效状态和置信度。
- 所有结论的来源追踪。

承诺类型代码：

- `STANDARD_APPROVED`：已有工单或标准动作支撑，可进入责任。
- `APPROVAL_REQUIRED`：需要权限或人工批准后生效。
- `CONDITIONAL`：保留条件，条件满足前不直接倒计时。
- `ERRONEOUS_OR_UNAUTHORIZED`：疑似越权或与系统事实冲突。
- `AMBIGUOUS`：如“尽快”“第一时间”，不生成正式截止时间。

## 4. AccountabilityState

这是体验责任账本在当前时点的代码快照，包含：

- 六个 Case 状态之一。
- 消费者是否还需要输入。
- 当前责任方、执行方和证据状态。
- 有效服务承诺与待履行责任。
- 下一检查时间、当前里程碑和真正完成条件。
- 体验断层诊断与禁止动作。
- 消费者可见的服务进度回执视图。

服务进度回执不显示内部责任人姓名、风险分数、情绪标签或推理过程。

## 4.1 CustomerState

`CustomerState` 是 v1.1 的 Customer Extension 主对象，在不破坏 BC Core 的前提下必须覆盖：

- `Facts`：已经确认的事实，每条有 SourceEvidence。
- `Evidence`：已知证据、待补充证据、不要再问。
- `Intent`：当前目标、约束、接受和拒绝的方案。
- `Emotion`：当前情绪、趋势、原因和沟通建议。
- `Effort`：重复解释、重复举证、等待、多次进线等消费者成本。
- `Actions`：下一步动作、禁止动作、允许动作、人工复核动作。
- `Promises`：有效承诺及其 DeadlineState。
- `Risk`：单个消费者的 RiskState。
- `Decision`：当前动作的轻量 Decision 或最近一次 DecisionResult 摘要。
- `Resolution`：解决路径、回执和闭环状态。

Customer State 只从 Experience Ledger、ExtractedJourney、规则服务、Monitor 和人工确认结果派生。前端不能直接写 Customer State，只能通过 `approve`、`shipment`、人工修正或后续专门接口触发服务端重算。Priority Queue、Emerging Issue 和 Risk Radar 是独立运营态，不作为 CustomerState 的必填子对象。

## 5. DecisionResult

体验防线输出：

- `INTERVENE / ALLOW / HUMAN_REVIEW`。
- 唯一触发规则、事实追踪和中文原因。
- 下一解决路径：查询动作、回复草稿、催办预填、人工批准、责任与完成条件。
- 承诺编译结果：原始承诺、分类、生效状态、截止时间与主动补救策略。
- `accountability_state`：服务端按 `case_id` 装载事实后自行计算的责任状态快照，只作为响应字段，不接受前端提交（P0-8）。
- `challenge_mode`：变体演示回显，仅在 `challenge_overrides` 生效时为 `true`，界面据此显示角标（P0-8）。

`Decision` 是 `DecisionResult` 的轻量业务表达，用于 `/decisions`、Handoff 和新版工作区。它必须保留 `source_evidence_ids`，并明确该判断来自规则、Jev 受限判断、人工确认还是兜底人工复核。

## 5.2 Risk、Priority 与 Emerging 的分层

`RiskState` 是单个消费者的 Customer Extension 状态，不是投诉、流失、医学或质量预测。它只能使用确定事实、等待时间、承诺状态、重复沟通、证据冲突和人工复核需求，不直接读取情绪标签作为加分项。

`PriorityState` 属于 Aggregate / Operational State，消费 `RiskState + DeadlineState + 工单状态 + 等待时间`，输出队列排序、优先级带和下一步动作。Priority 不改变事实，只决定先处理谁。

`EmergingIssue` 属于 Aggregate / Operational State，只表示“多个消费者已经出现同一事实指纹”，默认 `requires_human_confirmation: true`、`prediction: false`。同一消费者或同一会话重复上报不能放大独立消费者数。

## 5.3 三个激活字段对照表

三个契约各有一个“激活”字段，含义和取值都不同，不能互相赋值：

| 字段 | 位置 | 取值 | 语义 |
|---|---|---|---|
| `activation_recommendation` | `ExtractedJourney.promise_events[]` | `ACTIVE` / `PENDING_APPROVAL` / `BLOCKED` / `IGNORED` | AI 的建议，不是结论 |
| `activation_status` | `DecisionResult.resolution_path.compiled_service_responsibility` | `ACTIVE` / `PENDING_APPROVAL` / `BLOCKED` / `IGNORED` | 规则与人工确认后的编译结果 |
| `status` | `AccountabilityState.active_commitments[]` | `ACTIVE` / `AT_RISK` / `COMPLETED` | 账本运行时状态 |

流转方向单一：AI 建议 → 编译结果 → 账本状态。只有编译结果为 `ACTIVE` 的承诺才进入 `active_commitments`；`AT_RISK` 与 `COMPLETED` 由时间推进和物流事件产生，AI 不得直接写入（见第 6 节事实来源优先级）。

## 动作请求｜PreparedAction

客服准备发送或执行的动作请求。P0 主要验证 `ASK_EVIDENCE`，完整产品还包括关闭工单、创建新承诺和高风险业务动作。

## 6. 事实来源优先级

1. 订单、工单和物流等系统事实。
2. 人工批准和人工修正。
3. 确定性时间与状态计算。
4. AI 的图文抽取和语义判断。

AI 不得覆盖系统工单状态、人工批准、权限配置或政策边界。
