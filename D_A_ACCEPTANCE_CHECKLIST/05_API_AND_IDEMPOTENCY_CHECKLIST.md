# 05｜接口与幂等验收清单

依据：`docs/05-api-and-ui.md`、`docs/08-idempotency-and-ordering.md`、`schemas/*-request.schema.json`。

四个接口不增加。所有响应统一外层 `{data, error, request_id}`。

---

## 1. 四个接口速查

| 接口 | 请求 Schema | 成功 `data` | 关键错误 | 谁主要产出 |
|---|---|---|---|---|
| `POST /api/cases/analyze` | `analyze-case-request.schema.json` | `ExtractedJourney`、`AccountabilityState`、`model_metadata` | `SCHEMA_INVALID`、`MODEL_UNAVAILABLE`、`MODEL_OUTPUT_INVALID` | B |
| `POST /api/actions/evaluate` | `evaluate-action-request.schema.json` | `DecisionResult` | `SCHEMA_INVALID`、`E0_NO_RULE_MATCHED`（这是成功结果，不是错误） | B 规则引擎 |
| `POST /api/resolutions/approve` | `approve-resolution-request.schema.json` | 更新后的账本、`approved_resolution`、`audit_trail` | `VALIDATION_ERROR`、`IDEMPOTENCY_CONFLICT` | B |
| `POST /api/events/shipment` | `shipment-event-request.schema.json` | 更新后的账本、催办候选、通知草稿 | `INVALID_EVENT_TRANSITION`、`IDEMPOTENCY_CONFLICT` | B |

---

## 2. 接口级验收表（跑测时填）

| 编号 | 接口 | 案例 | 预期结果 | 实际结果 | 一致 | 截图 | 状态 |
|---|---|---|---|---|---|---|---|
| I-01 | `analyze` | `DEMO_001` | `evidence_status = VALID`，承诺抽取正确，`case_status = ACTION_REVIEW` | | ☐ | | 待测 |
| I-02 | `analyze` | `DEMO_002` | `evidence_status = MISMATCHED` | | ☐ | | 待测 |
| I-03 | `analyze` | `DEMO_003` | `evidence_status = NEED_HUMAN_REVIEW` | | ☐ | | 待测 |
| I-04 | `analyze` | 仅传 `case_id` | 完成分析；日志打印来源表与行 | | ☐ | | 待测 |
| I-05 | `analyze` | 承诺文案改「尽快」 | `commitment_class` 变 `AMBIGUOUS`，不生成确定截止时间 | | ☐ | | 待测 |
| I-06 | `evaluate` | `DEMO_001` + `ASK_EVIDENCE` | `INTERVENE` / `E1` / `300` | | ☐ | | 待测 |
| I-07 | `evaluate` | `DEMO_001` + 伪造 `evidence_status` | 仍为 `INTERVENE` / `E1` / `300` | | ☐ | | 待测 |
| I-08 | `evaluate` | `DEMO_002` + `ASK_EVIDENCE` | `ALLOW` / `E2` / `100` | | ☐ | | 待测 |
| I-09 | `evaluate` | `DEMO_003` + `ASK_EVIDENCE` | `HUMAN_REVIEW` / `H1` / `200` | | ☐ | | 待测 |
| I-10 | `evaluate` | `challenge_overrides` 改赠品范围 | `ALLOW` / `E2`；响应 `challenge_mode: true`；界面显示角标 | | ☐ | | 待测 |
| I-11 | `evaluate` | 不良反应 + `ASK_EVIDENCE` | `HUMAN_REVIEW` / `H1` | | ☐ | | 待测 |
| I-12 | `evaluate` | `CHECK_REPLACEMENT_PROGRESS` | `ALLOW` / `E0_NO_RULE_MATCHED` / `0`，不报错 | | ☐ | | 待测 |
| I-13 | `evaluate` | 人工确认后送 `CLOSE_CASE` | `INTERVENE` / `P0_PROHIBITED_ACTION` / `400` | | ☐ | | 待测 |
| I-14 | `evaluate` | 不良反应 + `CLOSE_CASE` | `P0_PROHIBITED_ACTION` 优先，`suppressed_rule_ids` 含 `H1` | | ☐ | | 待测 |
| I-15 | `approve` | `DEMO_001` + `CHECK_REPLACEMENT_FULFILLMENT` | 创建 `open_obligation` + `service_progress_receipt`；`case_status = IN_FULFILLMENT` | | ☐ | | 待测 |
| I-16 | `approve` | 不带 `approver_id` | `VALIDATION_ERROR` | | ☐ | | 待测 |
| I-17 | `approve` | `human_edits` 非空 | `approved_resolution` 反映修改；`audit_trail.changed_fields` 与提交键一致 | | ☐ | | 待测 |
| I-18 | `shipment` | `SHIPMENT_PICKED_UP` | `IN_FULFILLMENT` / `ON_TRACK` / `IN_TRANSIT`，无催办 | | ☐ | | 待测 |
| I-19 | `shipment` | `SHIPMENT_NOT_PICKED_UP`（已到期） | `AT_RISK` + 仓库催办 + 主管升级 + 通知草稿 | | ☐ | | 待测 |
| I-20 | `shipment` | `SHIPMENT_DELIVERED`（已揽收后） | `RESOLVED` + 义务 `COMPLETED` | | ☐ | | 待测 |
| I-21 | `shipment` | 未揽收直接送达 | `INVALID_EVENT_TRANSITION` | | ☐ | | 待测 |
| I-22 | `shipment` | 事件时间倒退 | `INVALID_EVENT_TRANSITION` | | ☐ | | 待测 |

---

## 3. 错误码验收

| 错误码 | HTTP 建议 | D 怎么触发 | 期望前端行为 | 状态 |
|---|---:|---|---|---|
| `SCHEMA_INVALID` | 400 | 删掉必填字段（如 `prepared_action`） | 标记输入问题，不重试 | 待测 |
| `VALIDATION_ERROR` | 400 | `approve` 不带 `approver_id` | 展示缺失字段，不重试 | 待测 |
| `P0_PROHIBITED_ACTION` | 400 | 有禁止项时送对应动作 | 保持发送暂停并展示替代动作 | 待测 |
| `INVALID_EVENT_TRANSITION` | 409 | 未揽收直接送达、事件时间倒退 | 刷新账本，不显示成功 | 待测 |
| `IDEMPOTENCY_CONFLICT` | 409 | 同键改 `approver_id` 或改请求体 | 提示重新发起，不重试原键 | 待测 |
| `MODEL_UNAVAILABLE` | 503 | 关掉模型与缓存 | 展示明确失败态 | 待测 |
| `MODEL_OUTPUT_INVALID` | 502 | 让模型输出不合 Schema | 进入人工复核 | 待测 |

---

## 4. 可复现验证向量 V1–V5

| 向量 | 请求 | 预期 | 实际 | 状态 |
|---|---|---|---|---|
| V1 | 相同批准请求重放同一 `idempotency_key` | 响应相同，`audit_trail` 仅一条新增 | | 待测 |
| V2 | 同键改 `approver_id` | `IDEMPOTENCY_CONFLICT` | | 待测 |
| V3 | 未揽收直接 `SHIPMENT_DELIVERED` | `INVALID_EVENT_TRANSITION` | | 待测 |
| V4 | `event_time` 倒退 | `INVALID_EVENT_TRANSITION` | | 待测 |
| V5 | 关闭通知模板时间替换 | `VALIDATION_ERROR` 或测试失败 | | 待测 |

建议每个向量各跑 3 次，确认结果稳定、逐字节一致。

---

## 5. 请求体纪律（最容易出错的地方）

`PRODUCT-FREEZE.md` P0-8 冻结了 `evaluate` 的可信输入，只有五项：

```text
case_id, prepared_action, evaluation_time?, challenge_mode?, challenge_overrides?
```

| 检查项 | 说明 | 状态 |
|---|---|---|
| `accountability_state` 不得作为有效输入 | 请求里带同名兼容字段时，服务端必须忽略 | 待测 |
| `evidence_status` 不得作为有效输入 | 同上 | 待测 |
| `active_commitments` 不得作为有效输入 | 同上 | 待测 |
| `prohibited_actions` 不得作为有效输入 | 同上 | 待测 |
| `current_scope` 不得作为有效输入 | 同上 | 待测 |
| `challenge_overrides` 必须与 `challenge_mode: true` 同时出现 | 二者缺一即 Schema 不通过 | 待测 |
| `approved_at` 由服务端生成 | 前端传入不采信 | 待测 |
| `idempotency_key` 长度 8–128，同一 `case_id` 下唯一 | Schema 已约束 | 待测 |
