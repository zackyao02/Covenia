# 01｜验收清单总表

用途：D 线的唯一主清单。所有检查项都在这张表里，逐条填「状态」。

填写规则：

- 状态只填四种：`待测` / `通过` / `失败` / `阻塞`。
- 「证据」必须是可核验的东西：截图文件名、录屏时间点、接口响应片段、日志行。
- 有失败或阻塞时，在 `09_阻塞与待确认清单.md` 里补一条，写清楚找谁。

---

## 1. 数据进入（门 1）

| 编号 | 验收项 | 依据 | 通过标准 | 证据 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| D-01 | Excel 七个业务表导入 | `docs/07` 门 1、A19 | 打印 138 会话 / 998 消息 / 113 订单 / 29 图片消息 / 80 工单 | 运行截图 + 计数输出 | B | 待测 |
| D-02 | 长数字 ID 不丢精度 | `docs/01` §1、`docs/07` 门 1 | 订单号 `6920185815517983396`、原物流单号 `773478190943155`、补发单号 `YT7667875838478` 完整显示，无科学计数法、无尾数变 0 | 截图 + 原始值对照 | B | 待测 |
| D-03 | 跨表关联正确 | `docs/01` §1 | 会话 `S00001` 能同时关联聊天 5–6 条、订单 1 笔、补发换货工单 `BH919209358357` | 关联结果截图 | B | 待测 |
| D-04 | 图片路径引用被保留 | `docs/01` §1 | 原始路径 `mock_images/broken_pump/S00001_03.jpg` 与来源消息 ID `80525870445254.PNM` 都能看到 | 导入日志截图 | B | 待测 |
| D-05 | 不读取「数据说明」表作为运行输入 | `docs/00` §3 | 导入日志中运行输入为 7 张业务表 | 日志截图 | B | 待测 |

## 2. AI 真实（门 2）

| 编号 | 验收项 | 依据 | 通过标准 | 证据 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| D-06 | 至少一个案例走真实图文推理 | `docs/07` 门 2 | `DEMO_001` 由原始聊天 + 实际图片文件生成 `ExtractedJourney` | 模型输出片段截图 | B | 待测 |
| D-07 | 承诺不在输入里预填 | `docs/01` §2、`case-input.schema.json` | `CaseInput` 中不含承诺结论、证据最终状态、责任方、防线结果 | 输入 JSON 截图 | B/A | 待测 |
| D-08 | 承诺原文抽取正确 | `extracted-journey.schema.json` | `promise_events[].raw_text` 含「换货单已创建，48小时内发出」，来源指向消息 `36199788469718.PNM` | 输出截图 | B | 待测 |
| D-09 | 承诺分类与生效建议 | `docs/01` §3 | `commitment_class = STANDARD_APPROVED`、`activation_recommendation = ACTIVE`、`deadline = 2026-05-07T10:27:37+08:00` | 输出截图 | B | 待测 |
| D-10 | 图片观察真实改变证据状态 | `docs/03` 决策约束 | 泵头图被识别为 `PRIMARY` + `sku_match = MATCH` + `issue_visible = true`，证据状态由观察推出 | 输出截图 + 状态来源 | B | 待测 |
| D-11 | 模型版本被锁定 | `MODEL_GOVERNANCE.md` | `model_metadata.model_id = Qwen/Qwen2-VL-2B-Instruct` | 输出截图 | B | 待测 |
| D-12 | 承诺候选只来自客服侧消息 | `docs/05` §2、F2 | 消费者消息不出现在 `promise_events` 中 | 输出截图 | B | 待测 |

## 3. 判断真实（门 3）

| 编号 | 验收项 | 依据 | 通过标准 | 证据 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| D-13 | 三个案例出三种决策 | `docs/07` 门 3 | `INTERVENE`（E1/300）、`ALLOW`（E2/100）、`HUMAN_REVIEW`（H1/200） | 三次响应截图 | B | 待测 |
| D-14 | 三个决策来自同一规则链 | `docs/03` §决策约束 | 规则实现中不含 `DEMO_001/002/003`、`S00001` 字面量分支 | 静态扫描结果 + B 口头确认 | D/B | 待测 |
| D-15 | 服务端自行计算状态 | `PRODUCT-FREEZE.md` P0-8、A20 | 只传 `case_id` 与 `prepared_action`，仍返回 `INTERVENE`/E1/300 | 响应截图 | B | 待测 |
| D-16 | 客户端伪造字段被忽略 | A21 | 请求体伪造 `evidence_status: MISMATCHED` 后，结果仍是 `INTERVENE`/E1 | 响应截图 | B | 待测 |
| D-17 | 图片文字不改变规则结论 | A26 | 带「证据有效」文字的图与无文字版本，`evidence_status` 一致 | 两次响应对照 | B | 待测 |
| D-18 | 消费者伪造承诺无效 | A25 | 消费者消息里的「48小时内发出」不产生新 `active_commitments` | 响应截图 | B | 待测 |
| D-19 | 无规则命中不报错 | A15、`docs/03` E0 | `CHECK_REPLACEMENT_PROGRESS` 返回 `ALLOW` / `E0_NO_RULE_MATCHED` / 0 | 响应截图 | B | 待测 |
| D-20 | 限制性规则优先 | A30、`docs/03` 求值顺序 | 不良反应 + 结案时返回 `P0_PROHIBITED_ACTION`(400)，`fact_trace.suppressed_rule_ids` 含 `H1` | 响应截图 | B | 待测 |
| D-21 | `fact_trace` 可解释 | `decision-result.schema.json` | `evidence_status`、`prepared_action`、`scope_match`、`active_promise_count` 齐全且能由本请求推出 | 响应截图 | B | 待测 |

## 4. 责任真实运行（门 4）

| 编号 | 验收项 | 依据 | 通过标准 | 证据 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| D-22 | 人工确认创建责任 | `docs/04` §2 | `open_obligation` 非空：`REPLACEMENT_FULFILLMENT` / `BRAND` / `AWAITING_CARRIER_PICKUP` | 响应截图 | B | 待测 |
| D-23 | 人工确认生成回执 | `docs/04` §3 | `service_progress_receipt` 含 `received_evidence`、`brand_action`、`next_update_by`、`consumer_action_required:false`、`recovery_if_missed` | 响应 + 界面截图 | B/C | 待测 |
| D-24 | 缺审批人报错 | A11 | 不带 `approver_id` 返回 `VALIDATION_ERROR` | 响应截图 | B | 待测 |
| D-25 | 人工修改被记录 | A12 | `human_edits` 生效，`audit_trail.changed_fields` 与提交键一致 | 响应截图 | B | 待测 |
| D-26 | 时间三处一致 | `docs/08` §4、A6 | `open_obligation.next_check_at` = 回执 `next_update_by` = 通知 `commits_next_update_at` | 响应对照 | B | 待测 |
| D-27 | 物流已揽收分支 | `docs/04` §4 | 推 `SHIPMENT_PICKED_UP` → `IN_FULFILLMENT` / `ON_TRACK` / `IN_TRANSIT`，无催办 | 响应 + 界面截图 | B/C | 待测 |
| D-28 | 物流未揽收分支 | `docs/04` §4、A10 | 推到期后 `SHIPMENT_NOT_PICKED_UP` → `AT_RISK` + 仓库催办 + 主管升级 + 主动通知草稿 | 响应 + 界面截图 | B/C | 待测 |
| D-29 | 送达才结案 | `docs/04` §6、A4 | 推 `SHIPMENT_DELIVERED` → `RESOLVED` + 义务 `COMPLETED`，且无 `ACTIVE` 承诺 | 响应截图 | B | 待测 |
| D-30 | 揽收不等于结案 | A5 | 只推揽收时状态不得为 `RESOLVED` | 响应截图 | B | 待测 |
| D-31 | 未揽收直接送达被拒 | A27、`docs/08` V3 | 返回 `INVALID_EVENT_TRANSITION`，状态与审计不变 | 响应截图 | B | 待测 |
| D-32 | 事件时间倒退被拒 | `docs/08` V4 | 返回 `INVALID_EVENT_TRANSITION` | 响应截图 | B | 待测 |
| D-33 | 幂等重放一致 | A18、V1 | 同 `idempotency_key` 重放，响应一致且 `audit_trail` 不增加 | 两次响应对照 | B | 待测 |
| D-34 | 同键不同体冲突 | `docs/08` V2 | 返回 `IDEMPOTENCY_CONFLICT` | 响应截图 | B | 待测 |
| D-35 | 前端不能直接改状态 | `docs/04` §4 | 物流按钮调用 `POST /api/events/shipment`，不是前端写死 | 抓包或 B 确认 + 截图 | C | 待测 |

## 5. 证据可核验（门 5）与合规

| 编号 | 验收项 | 依据 | 通过标准 | 证据 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| D-36 | 三类数据来源分开标注 | `SIMULATION_DISCLOSURE.md` | 赛事 Mock / 团队扩充 / 真实调研分别标识，界面固定可见一次「赛事 Mock 数据＋团队压力测试扩充」 | 界面截图 | A/C | 待测 |
| D-37 | 管理区两类内容分开 | `fixtures/synthetic-pattern-card.json` | 统计标 `OFFICIAL_COMPETITION_MOCK_DATA`，假设标 `HUMAN_ANNOTATED_STRESS_TEST` | 界面截图 | C/A | 待测 |
| D-38 | 假设不被说成赛事发现 | `docs/05` §9 | 「重复索证风险」不被表述为赛事数据结论 | 文案核对 | D | 待测 |
| D-39 | 30 个标注案例与调研产物 | `docs/06` §3 | 20 个开发回归 + 10 个留出测试有独立产物 | 找 A 要清单 | A | 待测 |
| D-40 | ground-truth 未进入运行输入 | `fixtures/README.md`、`docs/06` §6 | 模型输入、状态构建器、防线输入中无 `expected_*` 字段 | 输入日志 + 静态扫描 | B/D | 待测 |
| D-41 | PII 掩码生效 | A23、P0-9 | 手机号、收货地址、支付宝、就医与不良反应描述先行掩码，`pii_masked_count > 0` | 治理记录截图 | B | 待测 |
| D-42 | 缓存结果三处同时标注 | A31、`MODEL_GOVERNANCE.md` | 响应 `cached_result: true` + 界面「缓存抽取结果」角标 + 治理记录 | 截图 | B/C | 待测 |

## 6. 界面与演示可用性

| 编号 | 验收项 | 依据 | 通过标准 | 证据 | 负责人 | 状态 |
|---|---|---|---|---|---|---|
| D-43 | 第一屏只回答三问 | `docs/05` §7 | 已知什么 / 现在不能做什么 / 下一步做什么 | 界面截图 | C | 待测 |
| D-44 | 窄栏不滚动可见 | `docs/05` §10 | 1366×768、360–420px 下无需滚动能看到判断、原因和首要动作 | 截图 | C | 待测 |
| D-45 | 颜色不是唯一状态表达 | `docs/05` §10 | 决策状态有文字标识 | 截图 | C | 待测 |
| D-46 | Challenge Mode 角标 | P0-8、A22 | `challenge_mode: true` 时界面显示角标 | 截图 | C | 待测 |
| D-47 | 消费者侧不显示内部信息 | `docs/04` §3 | 回执不含内部责任人、风险分数、情绪标签、推理过程 | 界面截图 | C | 待测 |
| D-48 | 成本条可见 | F7 | 界面右下显示 token、延迟、规则层替代次数 | 截图 | C | 待测 |

---

## 汇总

| 分组 | 条数 | 通过 | 失败 | 阻塞 | 待测 |
|---|---:|---:|---:|---:|---:|
| 数据进入 | 5 | 0 | 0 | 0 | 5 |
| AI 真实 | 7 | 0 | 0 | 0 | 7 |
| 判断真实 | 9 | 0 | 0 | 0 | 9 |
| 责任真实运行 | 14 | 0 | 0 | 0 | 14 |
| 证据可核验与合规 | 7 | 0 | 0 | 0 | 7 |
| 界面与演示可用性 | 6 | 0 | 0 | 0 | 6 |
| **合计** | **48** | 0 | 0 | 0 | 48 |

更细的字段级、接口级和 A1–A33 级清单分别见 `04`、`05`、`06`、`07` 号文件。
