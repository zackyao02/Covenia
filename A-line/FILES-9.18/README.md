# Covenia｜A 线（数据与调研）交付包

对应赛事：欧莱雅黑客松挑战赛 · 赛题 1《数据共情者-客服工作台》
对应时间节点：`TEAM_AND_TIMELINE.md` 9/2–9/4「确认数据字段与案例」＋ 9/5–9/11「完成数据映射、首批标注」＋ 9/12–9/18「交付英雄案例证据」
最后更新：2026-09-17（v1.1.0）
数据基线：`data/tianchi-track1-mock-data.xlsx`（官方 Mock 数据，8 表）

---

## 一、时间线与本包对应关系

| 时间 | 全队共同结果 | A 线任务 | 本包对应文件 | 状态 |
|---|---|---|---|---|
| 9/2–9/4 | 完成认领，冻结接口和主流程 | **确认数据字段与案例** | `01-DATA-FIELD-CONFIRMATION.md`、`03-CASE-SELECTION-LIST.json` | 已完成 |
| 9/5–9/11 | 各线有可检查的第一版 | **完成数据映射、首批标注** | `02-DATA-MAPPING-TABLE.md/.json`、`03-ANNOTATION-FIELD-DEFINITIONS-AND-RULES.md`、`03-FIRST-BATCH-ANNOTATIONS-20-CASES.json/.csv` | 已完成 |
| 9/12–9/18 | `S00001` 纵向链路打通 | **交付英雄案例证据** | `06-HERO-CASE-EVIDENCE-PACKAGE.md/.json`、`EVIDENCE-ASSETS/` | 已完成（2026-09-17） |

`TEAM_AND_TIMELINE.md` 对 A 线的交付定义是「数据映射表、案例标注表、调研记录和证据来源说明」。相配套的 `04-RESEARCH-PLAN-AND-RECORDS.md`（调研记录）状态为「进行中」，`05-EVIDENCE-SOURCE-STATEMENT.md`（证据来源说明）已完成。

按倒排，调研执行与记录整理安排在 9/19–9/25，因此 `04` 的**全部结果槽位保持为空**，不填预测数字。

---

## 二、文件清单

| 文件 | 类型 | 用途 | 状态 |
|---|---|---|---|
| `README.md` | 导航 | 本包总览、任务对应、跨线提醒 | 已完成 |
| `01-DATA-FIELD-CONFIRMATION.md` | 文档 | 7 个业务表 124 字段确认、关联规则、导入契约、数据质量审计 | 已完成 v1.1.0 |
| `02-DATA-MAPPING-TABLE.md` | 文档 | 赛事字段 → `CaseInput` 等契约的映射规则、赠品别名对照、`S00001` 全量示例 | 已完成 v1.1.0 |
| `02-DATA-MAPPING-TABLE.json` | 机器可校验 | 同上，供 B 线导入层与 D 线校验直接消费 | 已完成 v1.1.0 |
| `03-ANNOTATION-FIELD-DEFINITIONS-AND-RULES.md` | 文档 | 标注字段字典、取值枚举、判定顺序、质检规则、Ground Truth 纪律 | 已完成 v1.1.0 |
| `03-CASE-SELECTION-LIST.json` | 机器可校验 | 30 个标注案例（20 开发回归 + 10 留出）与覆盖矩阵 | 已完成 v1.1.0 |
| `03-FIRST-BATCH-ANNOTATIONS-20-CASES.json` | 机器可校验 | 首批 20 例完整标注（开发与回归集） | 已完成 v0.2.0 |
| `03-FIRST-BATCH-ANNOTATIONS-20-CASES.csv` | 表格 | 同上，44 列扁平表，便于非开发成员核对 | 已完成 |
| `04-RESEARCH-PLAN-AND-RECORDS.md` | 文档 | 问卷、消费者深访、客服短访的计划与记录模板 | 进行中（不含预测数字） |
| `05-EVIDENCE-SOURCE-STATEMENT.md` | 文档 | 三类证据链分述、数据来源标签、图片素材清单与来源、脱敏范围、表述边界 | 已完成 v1.1.0 |
| `06-HERO-CASE-EVIDENCE-PACKAGE.md` | 文档 | 英雄案例证据包：素材登记、文件级核验、`VALID` 推导链、发现与待办 | 已完成 |
| `06-HERO-CASE-EVIDENCE-PACKAGE.json` | 机器可校验 | 同上，含逐图 sha256 与期望 `image_observations` | 已完成 |
| `EVIDENCE-ASSETS/` | 图片 + 说明 | A 线派生的两张答辩级对照素材（不替换已交付素材） | 已完成 |
| `APPENDIX-SESSION-INDEX-138.json` | 机器可校验 | 全部 138 个会话的订单/工单关联、图片引用与案例选定状态 | 已完成 |

`_superseded-zh/` 存放 2026-09-10 那版中文文件名文件，仅作留档，不再更新。

---

## 三、2026-09-17 这次更新改了什么

团队在 9/12–9/13 推进了 B/C/D 三条线，A 线据此同步了契约口径并补交英雄案例证据。

### 3.1 已有文件的调整（均为小调整，格式未变）

| 文件 | 调整 |
|---|---|
| `01-DATA-FIELD-CONFIRMATION.md` | 补记与 D 线基线、B 线导入结果的交叉核对结论；第 8 节更新 Q1–Q3 处理状态并新增 Q4（赠品 SKU 双写口径）；补第 10 节修订记录 |
| `02-DATA-MAPPING-TABLE.md/.json` | 新增 5.1.1 赠品 SKU 别名对照；赠品 `fulfillment_item_id` 改用团队约定的 `{订单号}-GIFT-01`；OI-02 状态由「待裁决」改为「已收口」 |
| `03-ANNOTATION-FIELD-DEFINITIONS-AND-RULES.md` | 判定顺序与 `rule_priority` 同步为 `P0(400) → H1(350) → E1(300) → E2(100) → E0(0)` |
| `03-CASE-SELECTION-LIST.json` | 开发集 6 例 H1 的 `rule_priority` 由 200 改为 350 |
| `03-FIRST-BATCH-ANNOTATIONS-20-CASES.json/.csv` | 6 例 H1 优先级改为 350；`S00001` 证据标注级别由 `PATH_REFERENCE_ONLY` 升级为 `TEAM_IMAGE_OBSERVED`；英雄案例 `next_check_at` 统一为 `2026-05-07T10:30:00+08:00` |
| `05-EVIDENCE-SOURCE-STATEMENT.md` | 五张素材状态由「待制作」改为「已交付 2026-09-12」并补核验说明；新增两张派生素材 |
| `04-RESEARCH-PLAN-AND-RECORDS.md` | 仅补记复核结论，状态仍为「进行中」 |
| `APPENDIX-SESSION-INDEX-138.json` | 仅登记修订时间，内容未变 |

### 3.2 新增的英雄案例证据

团队 2026-09-12 交付的 5 张素材（B 线 `frontend/public/evidence/`）已由 A 线完成文件级核验，并补齐两张答辩级派生素材：

| 素材 | 作用 |
|---|---|
| `s00001-product-overview.jpg` | 商品身份与正装属性；同时是「模糊对照」的清晰基准 |
| `s00001-pump-detail.jpg` | 覆盖 `AFFECTED_COMPONENT` 与 `DAMAGE_DETAIL`，是 `VALID` 的关键图 |
| `s00001-package-context.jpg` | 覆盖 `PACKAGE_CONTEXT` |
| `s00001-gift-evidence.jpg` | 范围变化证据（DEMO_002） |
| `s00001-blurred-pump.jpg` | 模糊证据（DEMO_003） |
| `EVIDENCE-ASSETS/s00001-pump-detail-blurred.jpg` | A 线派生：与泵头特写同构图的模糊版本 |
| `EVIDENCE-ASSETS/s00001-pump-detail-assertion.jpg` | A 线派生：A26 断言文字对照组 |

逐图 sha256、尺寸、清晰度指标、期望 `image_observations` 与 `VALID` 推导链见 `06-HERO-CASE-EVIDENCE-PACKAGE.md`。

---

## 四、首批 20 例标注结果概览

| 维度 | 分布 |
|---|---|
| 工单类型 | REPLACEMENT 8 / ADVERSE_REACTION 4 / RETURN 3 / OFFLINE_PAYMENT 2 / LOGISTICS 2 / 无工单 1 |
| 决策 | `INTERVENE` 9 / `HUMAN_REVIEW` 6 / `ALLOW` 5 |
| 规则 | `E1` 9 / `H1` 6 / `E0_NO_RULE_MATCHED` 4 / `E2` 1 |
| 规则优先级 | `E1` 300（9 例）/ `H1` 350（6 例）/ `E2` 100（1 例）/ `E0` 0（4 例） |
| 证据状态 | `VALID` 11 / `NEED_HUMAN_REVIEW` 6 / `MISMATCHED` 3 |
| 承诺分类 | `STANDARD_APPROVED` 29 条 / `CONDITIONAL` 6 / `APPROVAL_REQUIRED` 5 / `AMBIGUOUS` 4 / `ERRONEOUS_OR_UNAUTHORIZED` 1 |
| 预期账本状态 | `IN_FULFILLMENT` 10 / `ACTION_REVIEW` 8 / `READY_FOR_BRAND` 2 |

每一例的 `expected_decision` 都能由 `evidence_status` ＋ 参考动作按 `docs/03-firewall-rules.md` 的优先级表重新推导（0 处不一致）；45 条承诺的 `source_message_id` 已回查工作簿确认为客服发言（0 处违规）。

---

## 五、跨线提醒（A 线核验发现，需其他线处理）

| 编号 | 事项 | 影响 | 归属 |
|---|---|---|---|
| G-01 | `analyze` 仍返回固定样例，尚未真实读取图片推理 | `docs/07` 门 2 目前不成立；抗演员段落不能使用缓存结果 | B 线 |
| G-02 | `s00001-blurred-pump.jpg` 实际构图是商品整体图，但被声明为 `ISSUE_DETAIL` | H1 结论不受影响，证据覆盖项会被误判；两个修复方案见 `06` 第 7 节 | 产品负责人 / B 线 |
| G-03 | D 线 `06_expected-results.json` 仍写 `H1 = 200` | 与 2026-09-13 后的契约（350）不一致，按旧值比对会误判 | D 线 |
| G-04 | `fixtures` 中 DEMO_001 评估时间 11:00，P0-4 与 D 线用 09:40 | 承诺到期叙事受影响 | 产品负责人 / B 线 |
| G-05 | 素材提交在工程仓库内，与 D 线「图片不要塞进工程仓库」建议冲突 | 来源分离原则弱化 | B 线 / D 线 |
| G-06 | `docs/04` 回执样例文字仍写「最迟更新 10:27」，实现与期望值为 10:30 | 文案滞后 | 产品负责人 |
| G-07 | DEMO_002 / DEMO_003 的 `source_message_id` 不在 `conversation` 中 | 证据无法回溯，门 5 核对会断链 | 产品负责人 / B 线 |

---

## 六、验收自查

| 检查项 | 结果 |
|---|---|
| Excel 124 字段全部登记，无遗漏 | 是（`01` 第 3 节字段字典） |
| 关键 ID 全部按字符串处理，长数字不丢精度 | 是（`01` 第 4 节） |
| 会话 ↔ 订单 ↔ 工单关联覆盖率 100% | 是（`01` 第 5 节，外键缺失 0 条） |
| 7 表规模与官方口径一致（138/998/113/29/80） | 是，且与 D 线基线交叉核对一致 |
| 非完结工单 28 条已可枚举 | 是（`01` 第 3.2 节） |
| 30 个标注案例选定，覆盖五类工单与三类决策 | 是（`03-CASE-SELECTION-LIST.json`） |
| 首批 20 例标注完成并含来源追踪 | 是（来源行号已回查工作簿，0 处错误） |
| 决策可由规则表重新推导（含 H1=350） | 是（0 处不一致） |
| 承诺来源均为客服消息 | 是（0 处违规） |
| 账本断言补齐（B17 缺口） | 是（每例含 `expected_ledger_assertions`） |
| 英雄案例证据包交付 | 是（5 张交付素材 + 2 张派生素材，含 sha256 与核验结论） |
| 英雄案例 `evidence_status = VALID` 推导链完整 | 是（`06` 第 5 节） |
| Ground Truth 与运行输入物理分离 | 是（文件级分离 + 文件头声明） |
| 调研数据不填预测数字 | 是（`04` 全部槽位为「进行中/待执行」） |
| 所有数据来源可区分 | 是（`05` 来源标签体系） |

---

## 七、交给其他三条线的事

| 交给谁 | 事项 |
|---|---|
| B 线 | 按 `02-DATA-MAPPING-TABLE.json` 实现导入层；实现 `XLG5001`–`XLG5008` 赠品字典并接受 `GIFT-*` 别名；模型输入前完成字段级掩码；接入真实图片推理后回填 `06` 的 `expected_image_observations` |
| C 线 | 界面固定显示「赛事 Mock 数据＋团队压力测试扩充」；风险区分别标注「赛事数据统计」与「人工标注测试假设」；证据展开引用 `06` 的 `evidence_id` |
| D 线 | 用 `06` 的 sha256 核对素材；用第 5 节推导链核对 `VALID`；按 F-03 修正对照项配对；按 G-03 更新期望值；按 G-01 把门 2 标为未通过 |
