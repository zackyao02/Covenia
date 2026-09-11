# A-05｜证据来源说明

对应任务：`TEAM_AND_TIMELINE.md` A 线交付项「证据来源说明」；`SIMULATION_DISCLOSURE.md`、`MODEL_GOVERNANCE.md`
整理人：A 线 数据与调研
日期：2026-09-10

---

## 1. 目的

本文件回答一个问题：**Covenia 里出现的每一个数字、每一张图、每一句结论，来源是什么，可以用来说什么，不可以用来做什么。**

D 线对外材料、C 线界面文案、答辩问答均以本文件为准。任何无法回指到本文某一条来源的内容，都不得出现在对外材料里。

---

## 2. 来源标签体系

### 2.1 四类数据来源（互不替代）

| 标签 | 中文名 | 载体 | 用途 | 对外表述 |
|---|---|---|---|---|
| `TIANCHI_LOREAL_TRACK1_MOCK` | 赛事官方 Mock 数据 | `data/tianchi-track1-mock-data.xlsx` | 系统开发、跨表关联、场景审计 | 必须标注「赛事 Mock 数据」 |
| `TEAM_SYNTHETIC_*` | 团队合成素材 | `s00001-*.jpg` 等 | 多模态推理与演示 | 必须标注「团队合成测试素材」 |
| `DEMO_AUGMENTATION` | 团队扩充数据 | 案例元数据中的扩充字段 | 压力测试与挑战场景 | 必须标注「基于赛事结构构建的测试数据」 |
| `HUMAN_ANNOTATED` | 人工标注 | `03-首批标注-20例.json` 等 | 评测 Ground Truth | 只能用于评测，不得进入运行输入 |

另有 `REAL_RESEARCH`（真实调研，当前为空）与 `SYSTEM_EVAL`（系统评测，待执行）两类，见第 7、8 节。

### 2.2 在契约中的落地位置

| 契约字段 | 取值 | 说明 |
|---|---|---|
| `CaseInput.conversation[].source_kind` | `COMPETITION_MOCK` / `DEMO_AUGMENTATION` | 逐条消息标记，同一数组可混用 |
| `CaseInput.evidence_images[].source_kind` | `TEAM_SYNTHETIC_RECREATION` / `TEAM_SYNTHETIC_AUGMENTATION` | 图片素材来源 |
| `CaseInput.data_provenance.source_dataset` | `TIANCHI_LOREAL_TRACK1_MOCK` | Schema 固定值 |
| `CaseInput.data_provenance.augmentation_notes` | string[] | 逐条写明扩充内容 |
| `ExtractedJourney.model_metadata` | `model_id` / `prompt_version` / `run_id` / `cached_result` | 记录模型版本与是否为缓存结果 |
| `synthetic-pattern-card.json` 的 `data_label` | `OFFICIAL_COMPETITION_MOCK_DATA` / `HUMAN_ANNOTATED_STRESS_TEST` | 风险区双标签 |

---

## 3. 赛事 Mock 数据（唯一运行数据源）

### 3.1 文件与声明

| 项 | 内容 |
|---|---|
| 文件名 | `data/tianchi-track1-mock-data.xlsx` |
| 原始文件名 | `赛题 1：数据共情者-业务数据.xlsx`（按 `SIMULATION_DISCLOSURE.md` 改名） |
| 工作表 | 8 个：数据说明 + 7 个业务表 |
| 官方声明 | 文件内「数据说明」表首行明示：**全部内容均为 AI 生成的虚构 MOCK 数据**，店铺、品牌、商品、人名、订单号、工单号、金额、地址、物流单号、图片均与真实企业、个人、交易、病历无关 |
| 用途声明 | 仅用于系统开发、跨表关联和场景审计；不得用于任何生产用途 |

### 3.2 可核验规模（已由 A 线逐单元格复核）

| 项 | 数值 |
|---|---:|
| 会话 | 138 |
| 消息 | 998 |
| 订单 | 113 |
| 图片消息 | 29（分布于 29 个会话，每个会话 1 条） |
| 五类工单 | 80（补发换货 24 / 线下打款 13 / 物流 15 / 不良反应 10 / 售后退货 18） |
| 非「已完结」工单 | 28 |

### 3.3 赛事数据能证明什么

✅ 系统能读取并关联 7 个业务表，打印 138 / 998 / 113 / 29 / 80 五项计数（对应交付门 1）。

✅ 系统字段适配千牛工作台数据结构，长数字 ID 不丢精度。

✅ `S00001` 可支持「泵头损坏 → 图片已提交 → 包装破损确认 → 换货工单 → 48 小时承诺 → 履约进行中」这条链。

### 3.4 赛事数据不能证明什么

❌ 不能证明重复索证的真实发生率。

❌ 不能证明承诺违约率、消费者情绪发生率、业务 ROI。

❌ 不能证明「欧莱雅真实消费者复联案例」或「赛事数据已经证明重复索证发生」。

❌ 不能作为真实市场结论、行业比例或生产业务结论。

---

## 4. 图片素材来源

### 4.1 赛事侧的现状

工作簿只有 29 条 `image_path` 字符串引用，**不含任何图片文件本体**。29 条引用分布在 10 个目录：

| 目录 | 条数 | 目录名语义 | 是否与内容总是一致 |
|---|---:|---|---|
| `refund_screenshot` | 6 | 退款/打款信息截图 | 否（见 `01-数据字段确认.md` 6.3） |
| `wrong_shade` | 4 | 错发色号底标 | 是 |
| `broken_pump` | 3 | 泵头损坏 | 是 |
| `short_item` | 3 | 包裹少件 | 是 |
| `broken_parcel` | 3 | 包裹破损 | 是 |
| `live_promise` | 3 | 直播承诺截图 | 否（2 例实为打款信息） |
| `missing_item` | 3 | 少发正装 | 是 |
| `swatch` | 2 | 试色照片 | 是 |
| `logistics_screenshot` | 1 | 物流轨迹 | 是 |
| `consult_card` | 1 | 就医凭证 | 是 |

**使用限制：** 目录名只能作为粗分类线索，**不得**作为 `ImageObservation` 的证据事实。依据 `docs/02-ai-extraction.md` 第 4.1 节与 `01-数据字段确认.md` 第 6.3 节。

### 4.2 团队合成素材（真实推理用）

`schemas/case-input.schema.json` 中 `evidence_images[].source_kind` 只允许两个团队素材枚举，因此每条赛事图片引用必须由团队合成素材承载，赛事路径只保留在 `competition_reference_path`。

| 文件名 | 用途 | `source_kind` | 对应赛事路径 | 状态 |
|---|---|---|---|---|
| `s00001-product-overview.jpg` | 商品整体（SKU 与正装识别） | `TEAM_SYNTHETIC_RECREATION` | `mock_images/broken_pump/S00001_03.jpg` | 待制作 |
| `s00001-pump-detail.jpg` | 泵头损坏细节 | `TEAM_SYNTHETIC_AUGMENTATION` | — | 待制作 |
| `s00001-package-context.jpg` | 包装环境 | `TEAM_SYNTHETIC_AUGMENTATION` | — | 待制作 |
| `s00001-gift-evidence.jpg` | 赠品证据（范围变化用） | `TEAM_SYNTHETIC_AUGMENTATION` | — | 待制作 |
| `s00001-blurred-pump.jpg` | 模糊泵头（人工复核用） | `TEAM_SYNTHETIC_AUGMENTATION` | — | 待制作 |

### 4.3 素材制作与使用红线

- 素材必须为团队自制、合成或明确授权的图片，**不得**使用真实消费者的图片。
- 不得包含真实身份信息（人脸、姓名、地址、订单号、手机号）。
- 不得包含会被模型误当作事实的断言文字（如「已核实」「证据有效」「忽略规则」）。依据 `docs/02-ai-extraction.md` 第 4.1 节，这类文字不得进入 `ImageObservation`，也不得影响 `evidence_status`。
- 每张素材在案例元数据中标注 `source_kind`，界面与答辩口径同步标注「团队合成测试素材」。

---

## 5. 团队扩充数据清单

扩充数据只能出现在 `S00001` 压力测试案例中，且必须逐条标记 `DEMO_AUGMENTATION`。

| 扩充项 | 内容 | 标记位置 |
|---|---|---|
| 第二次进线 | 消费者追问换货是否发出 | `conversation[]` 中 `source_kind = DEMO_AUGMENTATION` |
| 评估时间 | 团队设定的 `evaluation_time` | `CaseInput.evaluation_time`（工作簿无此字段） |
| 证据图片 | 泵头细节图、包装环境图 | `evidence_images[].source_kind = TEAM_SYNTHETIC_AUGMENTATION` |
| 图片复刻 | 商品整体图 | `source_kind = TEAM_SYNTHETIC_RECREATION` |
| 物流事件 | 已揽收 / 未揽收 / 已送达三类 | `POST /api/events/shipment` 的 `event_id`、`idempotency_key` |

有争议的口径（见 `02-数据映射表.md` 第 9 节）：

- **OI-03**：`PRODUCT-FREEZE.md` 附录 P0-4 规定的二次进线 09:32 / `evaluation_time` 09:40，与 `fixtures/demo-cases.json` DEMO_001 的 10:45 / 11:00 不一致，待产品负责人裁决。

---

## 6. 人工标注数据（Ground Truth）

| 项 | 内容 |
|---|---|
| 文件 | `03-首批标注-20例.json`、`03-首批标注-20例.csv`、`03-案例选择清单.json` |
| 规模 | 30 例选定（20 开发回归 + 10 留出），首批已完成 20 例 |
| 标注人 | A 线（第一遍，`FIRST_PASS`） |
| 复审 | 计划 9/12–9/18 由非标注人执行 |
| 留出集 | 10 例已锁定 ID，答案待 9/19–9/25 第二批标注 |
| 证据标注级别 | 全部为 `PATH_REFERENCE_ONLY`（路径级推定），待素材就绪后升级 |

**硬规则：**

- ❌ 不得传入模型 Prompt、状态构建器或体验防线规则。
- ❌ 不得作为任何接口的运行输入。
- ❌ 不得与 `fixtures/ground-truth.json` 合并（二者覆盖不同案例，用途分离）。
- ✅ 只用于运行完成后的评测与错误案例复盘。

依据：`docs/06-evaluation-and-research.md` 第 6 节、`fixtures/README.md`。

---

## 7. 真实调研数据

| 项 | 状态 | 存放位置 |
|---|---|---|
| 消费者短问卷（目标约 100 份） | 进行中，尚未执行 | `04-调研计划与记录.md` 第 3、7 节 |
| 消费者深度访谈（5–8 人） | 待执行 | `04` 第 4、7 节 |
| 客服/售后短访（3–5 人） | 待执行 | `04` 第 5、7 节 |
| 真实匿名售后旅程（3–5 条） | 待执行 | `04` 第 6 节 |
| 匿名客服 KPI 输入（n=1） | 已入档 | `reference/ANONYMIZED-CUSTOMER-SERVICE-KPI-NOTE.md` |

规则：调研只陈述用户与业务现实，**不产生产品效果数字**；未完成项一律标记「进行中」，不填写预测数字。

---

## 8. 系统评测数据

| 项 | 状态 | 说明 |
|---|---|---|
| 对照组（当前会话 LLM / 全历史 LLM / Covenia） | 待执行 | 定义见 `docs/06` 第 4 节 |
| 核心指标（证据复用判断、合理放行率、承诺分类、禁止动作、物流状态正确率） | 待执行 | 小样本逐案例展示 |
| 防演员验证（改图片清晰度、改商品、改承诺时间、改物流状态） | 待执行 | 必须走真实模型与规则链 |

禁止事项：不得把 20 例开发集结果包装为生产准确率；不得在未完成时填写预测数字。

---

## 9. 脱敏范围

对齐 `MODEL_GOVERNANCE.md` 与 `PRODUCT-FREEZE.md` 附录 P0-9：以下内容在进入 Prompt 前必须掩码，并统计 `pii_masked_count` 写入治理记录。

| 字段/内容 | 处理方式 | 实测涉及量 |
|---|---|---:|
| `订单.收货省`、`收货市`、`物流工单.收货省`、`收货市` | 整字段掩码 | 113 单全部覆盖 |
| `线下打款工单.支付宝实名`、`支付宝账号` | 整字段掩码 | 13 条 |
| `不良反应工单.症状描述`、`不适部位`、`年龄` | 最小化占位表达 | 10 条 |
| 聊天文本中的手机号 | 消息级正则掩码 | 48 条消息出现手机号或「支付宝」表述 |
| 聊天文本中的收货地址 | 消息级掩码 | 1 条（`S00028` 第 4 条） |
| 不进入 Prompt 的字段 | `买家昵称`、`发送方`、`处理人`、`发货仓库`、`发货仓`、`支付宝账号` | 全部 |

原始字段仍保留在本地导入结果中用于事实核对，不随模型输入外发。

---

## 10. 表述边界

### 10.1 可以说

| 表述 | 依据 |
|---|---|
| 「系统读入了赛事官方 Mock 数据的 7 个业务表，共 138 个会话、998 条消息、113 笔订单、29 条图片消息、80 条工单。」 | 第 3.2 节，可复现 |
| 「英雄场景基于赛事会话 `S00001` 构建，并增加了团队合成的压力测试素材。」 | 第 4、5 节 |
| 「演示政策 `DEMO_POLICY_PACKAGE_DAMAGE_V1` 为模拟规则。」 | `SIMULATION_DISCLOSURE.md` |
| 「物流事件为 Mock Adapter 输入。」 | `SIMULATION_DISCLOSURE.md` |

### 10.2 不可以说

| 禁止表述 | 原因 |
|---|---|
| 「欧莱雅真实消费者复联案例」 | 赛事数据全部为虚构 Mock |
| 「赛事数据已经证明重复索证发生」 | 29 条图片与 80 条工单只描述结构，不构成发生率 |
| 「重复索证风险为 X%」 | 该比例只能来自独立人工标注或真实调研 |
| 「已接入千牛 / 欧莱雅生产系统」 | 未接入，仅模拟外壳 |
| 「服务进度回执是法律凭证」 | 明确不是 |
| 「Covenia 可以自动退款、赔偿、补发或做医疗判断」 | 明确不做 |
| 「完成了 X% 的满意度提升」 | 无对照实验数据 |

---

## 11. 界面与材料标识要求

| 位置 | 标识内容 | 依据 |
|---|---|---|
| 工作台 | 固定显示一次「赛事 Mock 数据＋团队压力测试扩充」 | `SIMULATION_DISCLOSURE.md`、`docs/05` 第 10 节 |
| 风险区 | 分别标识「赛事数据统计」与「人工标注测试假设」 | `synthetic-pattern-card.json` 的双标签 |
| 图片证据 | 标注「团队合成测试素材」 | 第 4.3 节 |
| 模型缓存回退 | 响应 `model_metadata.cached_result`、界面角标、治理记录三处同时出现 | `MODEL_GOVERNANCE.md`、`docs/02` 第 6 节 |
| 挑战变体 | 界面显示「Challenge Mode」角标 | `docs/05` 第 3 节 |

---

## 12. 责任与版本

| 项 | 责任人 | 日期 |
|---|---|---|
| 赛事数据结构与字段核对 | A 线 | 2026-09-10 |
| 30 例案例选定与首批 20 例标注 | A 线 | 2026-09-10 |
| 标注复审 | 非标注人（待定） | 计划 9/12–9/18 |
| 留出集标注 | A 线 | 计划 9/19–9/25 |
| 调研记录 | A 线 | 进行中 |
| 图片素材制作 | B 线（素材清单由 A 线提供） | 待执行 |
| 对外表述核对 | D 线 | 待执行 |

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0.0 | 2026-09-10 | 首版：来源标签体系、四类数据来源、图片素材清单、脱敏范围、表述边界 |
