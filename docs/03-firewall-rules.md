# 03｜体验防线规则

体验防线运行在客服发送消息或执行关键动作之前。Competition MVP 仍只重点编码三条决策规则；承诺类型与权限校验属于承诺编译阶段，不额外包装成第四个演示规则。

## E1｜重复索证拦截

优先级：`300`

```text
evidence_status = VALID
AND prepared_action = ASK_EVIDENCE
AND requested_scope = current_scope
```

输出：`INTERVENE`

英雄场景下一路径不是重新创建换货，而是查询已有换货/补发进度；如尚未揽收，预填仓库催办并生成主动更新回复。

## H1｜人工复核

优先级：`350`

```text
evidence_status = NEED_HUMAN_REVIEW
OR current_scope.issue_type = ADVERSE_REACTION
```

输出：`HUMAN_REVIEW`

适用于图片模糊、商品不可识别、问题不可见、SKU 无法匹配、模型来源冲突或高风险边界。

## E2｜范围变化放行

优先级：`100`

```text
evidence_status = MISMATCHED
AND prepared_action = ASK_EVIDENCE
```

输出：`ALLOW`

原因必须指出订单、商品货号、正装/赠品、问题组件或证据类型中哪一项发生变化，并只请求当前缺失的证据。

## P0_PROHIBITED_ACTION｜禁止动作拦截

优先级：`400`

当服务端计算出的 `prohibited_actions` 包含以下任一项时，禁止对应动作：

| 禁止项 | 受阻动作 |
|---|---|
| `ASK_SAME_EVIDENCE` | 同一范围下的 `ASK_EVIDENCE` |
| `ASK_REPEAT_EXPLANATION` | 要求消费者重新说明已知问题的动作 |
| `SHIFT_FOLLOW_UP_TO_CONSUMER` | 把已完成输入后的履约跟进交回消费者的动作 |
| `CLOSE_BEFORE_RESOLUTION` | `CLOSE_CASE` |

输出：`INTERVENE` / `P0_PROHIBITED_ACTION` / `400`。禁止项和责任状态只由服务端状态构建器产生，前端提交的同名字段不参与判定。

## E0_NO_RULE_MATCHED｜无规则命中

优先级：`0`

当不存在禁止项、也没有 E1、H1、E2 命中时，返回 `ALLOW` / `E0_NO_RULE_MATCHED` / `0`，并保留完整 `fact_trace`。这不是报错，也不能返回空规则编号。

## 求值顺序与可解释性

规则按 `P0_PROHIBITED_ACTION (400) → H1 (350) → E1 (300) → E2 (100) → E0_NO_RULE_MATCHED (0)` 求值。一次请求可以同时满足多个条件；只返回最高优先级规则，并在 `fact_trace.suppressed_rule_ids` 写入其余命中的规则。这样不良反应与假性结案同时出现时，界面可解释为何先阻断结案。

## 决策约束

- 三个案例使用同一状态构建器和规则实现。
- 禁止根据 `case_id` 返回固定结果。
- 图片观察必须进入证据状态计算。
- 没有足够事实时进入 `HUMAN_REVIEW`，不让模型假装确定。
- 体验表达只影响优先级和解决路径，不直接决定高风险业务动作。
- 状态构建器可用 `case_id` 装载赛事事实，但规则函数、Prompt 和状态推导不得按案例编号分支或返回固定结果。

## 完整产品规则目录

- `E1`：拦截相同范围的重复索证。
- `E2`：范围变化时放行合理索证。
- `E3`：证据不足时只说明具体缺口。
- `R1`：消费者完成必要输入后阻止责任倒流。
- `P1`：阻止未经审批、与系统事实冲突或无法跟踪的新承诺。
- `C1`：完成条件未满足时阻止假性结案。
- `O1`：有效承诺临近到期或逾期时升级处理。
- `H1`：事实不确定或高风险时进入人工复核。

主 Demo 聚焦 E1 和跨时间责任变化；E2 与 H1 在 Challenge Mode 验证。完整规则目录不因演示聚焦而删除。
