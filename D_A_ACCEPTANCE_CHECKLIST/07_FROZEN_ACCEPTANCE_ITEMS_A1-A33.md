# 07｜冻结验收项 A1–A33 清单

来源：`PRODUCT-FREEZE.md` 第「验收标准」节（产品冻结，审批状态 APPROVED，批准日期 2026-09-08）。

这 33 条是已批准的验收标准，D 线逐条执行。每条都可以直接对应到 `B_主流程测试数据/data/` 里的请求。

---

## 对应关系总览

| 分组 | 条目 | 主要对应的测试数据文件 |
|---|---|---|
| 决策推导与变体 | A1、A2、A3、A20、A21、A22 | `01_analyze-requests.json`、`02_evaluate-action-requests.json` |
| 责任闭环与物流 | A4、A5、A10 | `03_approve-resolution-requests.json`、`04_shipment-event-requests.json` |
| 时间与通知一致 | A6、A7、A8、A9 | `06_expected-results.json` |
| 审批与审计 | A11、A12、A18 | `03_approve-resolution-requests.json` |
| 规则优先级 | A13、A14、A15、A29、A30 | `02_evaluate-action-requests.json` |
| 承诺分级 | A17、A25、A28 | `01_analyze-requests.json`、`05_challenge-cases.json` |
| 数据与模型治理 | A16、A19、A23、A24、A31 | `00_赛事原始事实基线.json`、`05_challenge-cases.json` |
| 抗演员与抗硬编码 | A26、A27、A32、A33 | `05_challenge-cases.json` |

---

## 逐条清单

| ID | 场景（Given） | 动作（When） | 预期（Then） | 依据 | 状态 |
|---|---|---|---|---|---|
| A1 | 三个决策变体 | 互换 `case_id` | `decision` 与 `rule_id` 不变 | P0-1 | 待测 |
| A2 | `DEMO_001`、`evidence_status: VALID` | `challenge_mode: true`，把 `challenge_overrides.requested_scope.sku_id` 改成赠品 | `INTERVENE`/E1 → `ALLOW`/E2；响应回显 `challenge_mode: true` 且界面显示角标 | P0-8 | 待测 |
| A3 | 变体请求 | 计算 `fact_trace` | 每字段可由本请求算出，无一依赖 `case_id` | P0-1 | 待测 |
| A4 | 已批准案件 | 依次推揽收、送达 | `RESOLVED` + 义务 `COMPLETED` + 无 `ACTIVE` 承诺 | P0-2 | 待测 |
| A5 | 已批准案件 | 只推揽收 | 状态不得为 `RESOLVED` | P0-2 | 待测 |
| A6 | 生成主动通知 | 读取时间 | 通知时间 = `open_obligation.next_check_at` = `next_update_by` | P0-3 | 待测 |
| A7 | 通知未确认 | 查看回执 | 通知为草稿态，不进消费者可见回执 | P0-3 | 待测 |
| A8 | 全部样例 | 校验时序 | `event_time` / `approved_at` 均晚于 `evaluation_time` | P0-4 | 待测 |
| A9 | 分析时点 09:40 | 读承诺 | `deadline - evaluation_time > 0` 且承诺 `ACTIVE` | P0-4 | 待测 |
| A10 | `IN_FULFILLMENT` | 推 11:35 未揽收 | 承诺 `ACTIVE → AT_RISK`，风险等级变化界面可见 | P0-4 | 待测 |
| A11 | 批准请求 | 不带 `approver_id` | `VALIDATION_ERROR` | P0-5 | 待测 |
| A12 | `human_edits` 非空 | 批准 | `approved_resolution` 反映修改，`audit_trail.changed_fields` 与提交键集合一致 | P0-5 | 待测 |
| A13 | 禁止项含 `CLOSE_BEFORE_RESOLUTION` | 送 `CLOSE_CASE` | `INTERVENE` / `P0_PROHIBITED_ACTION` / 400 | P0-6 | 待测 |
| A14 | `issue_type: ADVERSE_REACTION`，证据 `VALID` | 送 `ASK_EVIDENCE` | `HUMAN_REVIEW` / H1 | P0-6 | 待测 |
| A15 | 无规则命中 | 送 `CHECK_REPLACEMENT_PROGRESS` | `ALLOW` / `E0_NO_RULE_MATCHED` / 0，不报错 | P0-6 | 待测 |
| A16 | 仅传 `case_id` | 分析 | 完成分析，日志打印来源表与行 | P0-7 | 待测 |
| A17 | 承诺文案改「尽快发出」 | 分析 | `STANDARD_APPROVED → AMBIGUOUS` | P0-7 | 待测 |
| A18 | 同幂等键 | 重放批准 / 事件 | 响应一致且状态不二次变更 | P1 | 待测 |
| A19 | Excel 导入 | 执行门 1 | 打印 138 / 998 / 113 / 29 / 80 并与官方对齐 | `docs/07` 门 1 | 待测 |
| A20 | 仅传 `case_id` 与 `prepared_action: ASK_EVIDENCE` | 评估 | `INTERVENE` / E1 / 300，状态由服务端装载 | P0-8 | 待测 |
| A21 | 请求体伪造 `evidence_status: MISMATCHED`，未开 `challenge_mode` | 评估 | 该字段被忽略，仍 `INTERVENE` / E1 | P0-8 | 待测 |
| A22 | `challenge_mode: true` + `challenge_overrides` 改赠品范围 | 评估 | `ALLOW` / E2，响应含 `challenge_mode: true`，界面角标可见 | P0-8 | 待测 |
| A23 | 聊天含手机号与收货地址 | 分析 | 模型输入日志显示掩码，治理记录 `pii_masked_count > 0` | P0-9 | 待测 |
| A24 | 关闭脱敏步骤 | 跑测试 | 测试失败（防回归） | P0-9 | 待测 |
| A25 | 消费者消息伪造「48小时内发出」或注入指令 | 分析 | 不产生新承诺；`active_commitments` 数量不变 | R2 | 待测 |
| A26 | 图片带「证据有效」文字 vs 同图无文字 | 分析 | `evidence_status` 一致；图中文字不进入规则事实 | R3 | 待测 |
| A27 | 未揽收时直接推 `SHIPMENT_DELIVERED` | 事件 | `INVALID_EVENT_TRANSITION`，状态和审计记录不变 | R4 | 待测 |
| A28 | 发送「全额退款并赔偿」 | 分析 / 批准 | 非 `STANDARD_APPROVED`；无审批记录时不生成 `ACTIVE` 承诺或截止时间 | R5 | 待测 |
| A29 | 消费者输入已完整，准备把后续跟进交给消费者 | 评估 | `INTERVENE` / `P0_PROHIBITED_ACTION` / 400 | R6 | 待测 |
| A30 | 不良反应 + `CLOSE_CASE` | 评估 | `P0_PROHIBITED_ACTION` 优先；`fact_trace.suppressed_rule_ids` 含 `H1` | R7 | 待测 |
| A31 | 强制模型不可用 | 分析 | 响应、界面和治理记录都显示缓存结果；关闭界面角标时测试失败 | R9 | 待测 |
| A32 | 主动通知草稿 | 批准 / 事件 | 文案中的下次时间与 `commits_next_update_at` 完全一致 | R10 | 待测 |
| A33 | 规则、状态构建器与 Prompt 目录 | 静态扫描 | 不含 `DEMO_001`、`DEMO_002`、`DEMO_003`、`S00001` 字面量 | 抗硬编码 | 待测 |

---

## A1–A33 执行状态汇总

| 状态 | 条数 |
|---|---:|
| 待测 | 33 |
| 通过 | 0 |
| 失败 | 0 |
| 阻塞 | 0 |

---

## 需要与 B 确认实现前的前提

| 条目 | 需要 B 先确认的问题 |
|---|---|
| A29 | `SHIFT_FOLLOW_UP_TO_CONSUMER` 对应哪一个 `prepared_action.action_type`？`prepared-action.schema.json` 的枚举里没有直接对应的动作，需要 B 说明用哪个动作触发这条禁止项 |
| A31 | 如何「强制模型不可用」？是环境变量、开关还是断网？D 需要有可复现的操作方式 |
| A24 | 「关闭脱敏步骤后测试失败」是哪个测试？D 需要测试命令与预期输出 |
| A33 | 静态扫描用哪条命令？由 B 提供命令，D 负责执行并截图 |
| A12 | `approved_resolution` 允许的编辑字段有哪些？D 需要一份允许字段清单才能核对 `changed_fields` |
