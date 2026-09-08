# 08｜幂等、时序与接口错误

## 1. 通用响应

每个端点都返回 `ApiEnvelope`：`data`、`error`、`request_id` 三个字段必有其一套完整值。成功响应的 `error` 为 `null`；错误响应的 `data` 为 `null`。前端只能依据 `error.code` 判断失败类型，不能从自然语言消息解析业务状态。

## 2. 错误目录

| 错误码 | HTTP 建议 | 含义 | 前端动作 |
|---|---:|---|---|
| `SCHEMA_INVALID` | 400 | 请求不符合 Schema | 标记输入问题，不重试 |
| `VALIDATION_ERROR` | 400 | 业务必填或字段一致性失败 | 展示缺失字段，不重试 |
| `P0_PROHIBITED_ACTION` | 400 | 动作会造成重复伤害、责任倒流或假性结案 | 保持发送暂停并展示替代动作 |
| `INVALID_EVENT_TRANSITION` | 409 | 物流事件顺序或时间非法 | 刷新账本，不把操作显示为成功 |
| `IDEMPOTENCY_CONFLICT` | 409 | 相同幂等键对应不同请求体 | 提示重新发起，不重试原键 |
| `MODEL_UNAVAILABLE` | 503 | 模型和缓存均不可用 | 展示明确失败态 |
| `MODEL_OUTPUT_INVALID` | 502 | 模型输出无法通过 Schema | 进入人工复核 |

`E0_NO_RULE_MATCHED` 是 `evaluate` 的成功业务结果，不是错误。

## 3. 幂等规则

`approve` 与 `shipment` 请求的 `idempotency_key` 在同一 `case_id` 下唯一。相同键与相同规范化请求体必须返回首次响应，且不得新增 `audit_trail` 记录；相同键但不同请求体返回 `IDEMPOTENCY_CONFLICT`。建议服务端保存键、规范化请求摘要、首次 `request_id` 与响应体。

## 4. 时间与事件顺序

- 服务端生成 `approved_at`，客户端不得传入或覆盖。
- `event_time` 不得早于账本最近状态时间；违反时返回 `INVALID_EVENT_TRANSITION`。
- `SHIPMENT_DELIVERED` 只允许从 `IN_TRANSIT` 到达；`AWAITING_CARRIER_PICKUP → DELIVERED` 一律拒绝。
- `next_check_at`、回执 `next_update_by` 与通知 `commits_next_update_at` 是同一时点的不同投影，必须相等。

## 5. 可复现验证向量

| 向量 | 请求 | 预期 |
|---|---|---|
| V1 | 相同批准请求重放同一键 | 响应相同，审计记录仅一条 |
| V2 | 同键改 `approver_id` | `IDEMPOTENCY_CONFLICT` |
| V3 | 未揽收直接 `SHIPMENT_DELIVERED` | `INVALID_EVENT_TRANSITION` |
| V4 | `event_time` 倒退 | `INVALID_EVENT_TRANSITION` |
| V5 | 关闭通知模板时间替换 | `VALIDATION_ERROR` 或测试失败 |
