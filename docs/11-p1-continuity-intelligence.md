# 11｜P1 连续服务洞察

## 1. 范围

P1 在 P0 Customer State 与 Promise-to-Action 基础上补齐四项能力：

1. Journey Timeline。
2. Multi-source Fusion：Conversation + Image + Order + Ticket。
3. Promise deadline monitoring。
4. Emerging Issue Detection。

实现继续遵循两项边界：不把情绪推断写入风险分数；不把异常聚类表述为投诉、流失或舆情预测。

## 2. Journey Timeline

`POST /api/cases/analyze` 返回统一 `timeline[]`。每个事件必须包含：

- `at`：事件时间。
- `type`：业务事件类型。
- `source_type`：`CONVERSATION / IMAGE / ORDER / TICKET / SYSTEM_EVENT`。
- `source_ids[]`：可回到原始记录的 ID。
- `title / detail`：界面展示信息。

订单缺少独立时间字段时，时间线使用首次观察时间并标记 `derived_time: true`，不得伪装成订单创建时间。

## 3. Multi-source Fusion

分析响应增加 `multi_source_fusion`：

- 展示四类数据是否存在、数量和来源 ID。
- 展示三条连接关系及状态。
- 使用 `source_session_id / order_id / sku_id / ticket_id` 组织实体关系。
- 发现当前问题 SKU 不属于订单时返回 `CONFLICT` 并要求人工复核。
- 事实优先级保持“业务系统事实 > 人工修正 > 确定性规则 > 模型推断”。

Multi-source Fusion 不把四份数据简单拼接成文本；所有融合结果必须保留来源和冲突。

## 4. Promise deadline monitoring

人工批准生成 `open_obligation` 后，Deadline Monitor 每 10 秒检查一次：

```text
SCHEDULED
→ deadline 到达
→ open_obligation.status = AT_RISK
→ case_status = AT_RISK
→ commitment_status = AT_RISK
→ 生成 PROMISE_DEADLINE_ESCALATED 审计事件
→ Risk Radar 刷新
```

同一责任只升级一次，不重复写审计。送达结案后 Monitor 进入 `CLOSED`。

接口：

- `GET /api/monitor/deadlines`：查看监控状态。
- `POST /api/monitor/deadlines/run`：演示或测试中手工触发一次检查。

Monitor 只处理已经人工批准并进入运行态的责任，不会让模型输出直接成为生效承诺。

## 5. Emerging Issue Detection

接口 `GET /api/emerging-issues` 在固定时间窗口内按以下指纹聚类：

```text
sku_id + affected_component + issue_type
```

候选必须达到至少 3 个独立 `customer_key`，同一消费者或同一会话重复出现不能放大计数。输出包含窗口、独立消费者数、当前与前序窗口、数据源覆盖和支持信号 ID。

输出固定为 `EMERGING_CANDIDATE`、`requires_human_confirmation: true`、`prediction: false`。它表示“多个消费者已经出现相同事实模式”，不是未来风险预测或产品质量结论。

当前 `fixtures/emerging-issue-signals.json` 为团队构建的 P1 模式检测测试数据，界面固定展示披露说明。

## 6. 验收标准

| ID | Given | When | Then |
|:--:|:---|:---|:---|
| P1-1 | Hero case | 分析 | 时间线覆盖 Conversation、Image、Order、Ticket 且每项有来源 ID |
| P1-2 | 四源均存在 | 分析 | Fusion 为 COMPLETE、完整度 100% |
| P1-3 | 已批准责任未到期 | Monitor 检查 | 保持 SCHEDULED，不升级 |
| P1-4 | 已批准责任超过 deadline | Monitor 检查 | 自动转 AT_RISK 并写一次审计 |
| P1-5 | 再次检查同一逾期责任 | Monitor 检查 | 不重复升级，不重复写审计 |
| P1-6 | 24 小时内 3 个独立消费者出现同指纹问题 | 聚类 | 生成待人工确认 Emerging Candidate |
| P1-7 | 同一消费者重复上报 | 聚类 | 独立消费者数不增加 |
| P1-8 | 聚类结果 | 查看 API 与界面 | 固定标明测试数据与非预测边界 |
