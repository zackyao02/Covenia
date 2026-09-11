# A-02｜数据映射表

对应任务：`TEAM_AND_TIMELINE.md` 9/5–9/11「完成数据映射」
机器可校验版本：`02-数据映射表.json`
上游依据：`01-数据字段确认.md`、`docs/01-core-contracts.md`、`schemas/`

---

## 1. 用途

本表把赛事工作簿的 7 个业务表，逐字段映射到 Covenia 的四个契约。使用方式：

- **B 线**：直接按第 4 节的 `target_path` 实现导入层；第 5 节是必须实现的派生字典。
- **C 线**：第 7 节给出 `S00001` 从原始单元格到界面事实的完整链路，可用于核对右栏「已知什么」。
- **D 线**：第 10 节的检查点即门 1（数据真实进入）的验收清单。

映射只覆盖赛事数据到 `CaseInput` 的部分。`ExtractedJourney`、`AccountabilityState`、`DecisionResult` **不允许**由赛事字段直填，只能由模型与规则链路产出。

---

## 2. 映射总览

```text
聊天记录 ─┬─> CaseInput.conversation[]（消息、时间、角色、来源）
          ├─> CaseInput.evidence_images[]（图片引用 + 团队合成素材）
          └─> CaseInput.current_issue（场景语义，需人工标注）

订单    ─┬─> CaseInput.order（订单号、物流单号、商品与赠品行）
          └─> CaseInput.order.items[].batch_code（借不良反应工单批次号）

五类工单 ─┬─> CaseInput.service_tickets[]（类型、状态、执行方、补发单号）
          └─> 赠品货号字典（由补发换货工单派生）

CaseInput ──多模态模型──> ExtractedJourney
CaseInput + ExtractedJourney ──状态构建器──> AccountabilityState
AccountabilityState + PreparedAction ──体验防线──> DecisionResult
```

**映射方向一律单向。** 赛事字段不得写入 `evidence_status`、`active_commitments`、`prohibited_actions`、`current_scope` 或任何决策字段，与 `docs/05-api-and-ui.md` 第 3 节一致。

### 2.1 映射类型统计

`case_input_mapping` 共 **40** 条：

| 类型 | 含义 | 条数 |
|---|---|---:|
| 直接映射 | 源字段原样或经格式转换后进入契约 | 22 |
| 派生映射 | 需要由多字段、字典或聊天语义计算得到 | 8 |
| 常量 | Schema 固定值 | 3 |
| 来源标记与团队设定 | 工作簿没有或需团队声明的字段（`source_kind`、`evaluation_time`、素材来源等） | 7 |

另有 **4** 条「禁止直填」约束不属于映射，列在 `extracted_journey_input_constraints` 中（见第 6 节）。

---

## 3. 关联规则

| 优先级 | 关联 | 基数 | 实测 |
|---:|---|---|---|
| 1 | `聊天记录.会话ID = 订单.会话ID = 工单.会话ID` | 1 : 0..1 : 0..1 | 138 会话 / 113 订单 / 80 工单；无一对多 |
| 2 | `聊天记录.关联订单号 = 订单.订单号` | 一致性校验 | 0 处冲突 |
| 3 | `聊天记录.关联工单号 = 工单.工单号` | 一致性校验 | 0 处冲突 |
| 4 | `订单.订单号 = 工单.关联订单号` | 一致性校验 | 80 / 80 命中 |
| 5 | `买家昵称` | 仅辅助核对 | 112 昵称 : 113 订单，存在一人多单，不作主键 |

### 3.1 导入时必须遵守的类型规则

| 规则 | 字段 |
|---|---|
| 一律字符串 | `订单号`、所有 `工单号`、所有 `物流单号`、`退款编号`、`message_id`、`关联订单号`、`关联工单号` |
| 整数 | `消息序号`、`数量`、`年龄` |
| 金额（两位小数规整） | `单价(元)`、`实付金额(元)`、`退款金额(元)`、`订单实付(元)` |
| 时间（补 `+08:00`） | 所有 `*时间` |
| 布尔 | `is_target_buyer_message`、`客诉加急`、`是否异常`、`是否就医` |

按字符串读取的原因：订单号为 19 位数字，最大实测值 `6920958371179868642`，超出 IEEE 754 双精度可精确表示范围（2^53−1 = 9007199254740991），按数值读会出现末位归零或科学计数法，直接破坏跨表关联。

---

## 4. `CaseInput` 逐字段映射表

### 4.1 案例标识与来源

| 目标路径 | 类型 | 必填 | 来源 | 转换 |
|---|---|---|---|---|
| `case_id` | string | 是 | `聊天记录.会话ID` | 赛事会话用原 ID；演示扩充用 `DEMO_xxx` |
| `data_provenance.source_dataset` | const | 是 | 常量 | `TIANCHI_LOREAL_TRACK1_MOCK` |
| `data_provenance.source_session_id` | string | 是 | `聊天记录.会话ID` | 原样 |
| `data_provenance.augmentation_notes` | string[] | 是 | 团队扩充记录 | 逐条写明扩充内容与理由；无扩充为空数组 |
| `evaluation_time` | date-time | 是 | 团队设定 | 工作簿无此字段，必须显式声明；见第 9 节 OI-03 |

### 4.2 会话消息

| 目标路径 | 类型 | 必填 | 来源 | 转换 |
|---|---|---|---|---|
| `conversation[].message_id` | string | 是 | `聊天记录.message_id` | 原样，字符串 |
| `conversation[].timestamp` | date-time | 是 | `聊天记录.发送时间` | `yyyy-MM-dd HH:mm:ss` → ISO8601 + `+08:00` |
| `conversation[].speaker` | enum | 是 | `聊天记录.角色` | 买家→`CONSUMER`；客服→`AGENT`；系统推送→`SYSTEM` |
| `conversation[].text` | string | 是 | `聊天记录.message_text` | 原样，进模型前掩码 |
| `conversation[].source_kind` | enum | 是 | 数据来源 | 工作簿→`COMPETITION_MOCK`；扩充→`DEMO_AUGMENTATION` |

排序：按 `消息序号` 升序。实测 138 个会话的时间戳均严格递增，无需二次排序。

### 4.3 订单

| 目标路径 | 类型 | 必填 | 来源 | 转换 |
|---|---|---|---|---|
| `order.order_id` | string | 是 | `订单.订单号` | 原样，字符串 |
| `order.channel` | const | 是 | 常量 | `TIANCHI_MOCK_QIANNIU` |
| `order.original_logistics_number` | string | 是 | `订单.物流单号` | 原样，字符串 |
| `order.items[].fulfillment_item_id` | string | 是 | 派生 | `{订单号}-{商品货号}` |
| `order.items[].sku_id` | string | 是 | `订单.商品货号` / 赠品字典 | 正装取原值；赠品查第 5 节字典 |
| `order.items[].product_name` | string | 是 | `订单.商品名称` / `订单.赠品` | 原样 |
| `order.items[].batch_code` | string \| null | 否 | `不良反应工单.产品批次号` | 仅不良反应会话填入；`00` 视为未提供 |
| `order.items[].item_role` | enum | 是 | `订单.赠品` | 出现在赠品列→`GIFT`；否则→`PRIMARY` |

**商品行构造规则：** 每个订单至少生成 1 条 `PRIMARY`；当 `赠品` 列非空时，额外生成 1 条 `GIFT`。113 笔订单中 54 笔无赠品，59 笔有赠品。

### 4.4 工单

| 目标路径 | 类型 | 必填 | 来源 | 转换 |
|---|---|---|---|---|
| `service_tickets[].ticket_id` | string | 是 | 工单.`工单号` | 原样 |
| `service_tickets[].ticket_type` | enum | 是 | 来源表名 | 见下表 |
| `service_tickets[].status` | string | 是 | `工单状态` / `任务状态` | 原样保留中文值 |
| `service_tickets[].assignee_id` | string | 是 | 工单.`处理人` | 原样，内部代号 |
| `service_tickets[].executor_name` | string \| null | 否 | `补发换货工单.发货仓库` / `物流工单.发货仓` | 原样；其余表 null |
| `service_tickets[].replacement_logistics_number` | string \| null | 否 | `补发换货工单.补发物流单号` | 原样；其余表 null |
| `service_tickets[].created_at` | date-time | 是 | 工单.`创建时间` | + `+08:00` |
| `service_tickets[].completed_at` | date-time \| null | 否 | 工单.`完成时间` | + `+08:00`；空值保留 null |
| `service_tickets[].source_sheet` | string | 是 | 来源表名 | 中文表名原样 |

来源表 → `ticket_type`：

| 来源表 | `ticket_type` |
|---|---|
| 补发换货工单 | `REPLACEMENT` |
| 线下打款工单 | `OFFLINE_PAYMENT` |
| 物流工单 | `LOGISTICS` |
| 不良反应工单 | `ADVERSE_REACTION` |
| 售后退货工单 | `RETURN` |

### 4.5 图片证据

| 目标路径 | 类型 | 必填 | 来源 | 转换 |
|---|---|---|---|---|
| `evidence_images[].evidence_id` | string | 是 | 派生 | 赛事引用：`{会话ID}_IMG_{消息序号两位}`；团队素材：沿用素材命名 |
| `evidence_images[].file_name` | string | 是 | 素材文件名 / `image_path` basename | 取文件名 |
| `evidence_images[].submitted_at` | date-time | 是 | `聊天记录.发送时间` | 用图片消息本身的时间 |
| `evidence_images[].declared_view_type` | enum | 是 | 声明映射 | 见下表（`declared_` 前缀表示团队声明，非模型结论） |
| `evidence_images[].source_kind` | enum | 是 | 团队素材来源 | 复刻赛事语义→`TEAM_SYNTHETIC_RECREATION`；纯扩充→`TEAM_SYNTHETIC_AUGMENTATION` |
| `evidence_images[].source_message_id` | string | 是 | `聊天记录.message_id` | 对应图片消息的 ID |
| `evidence_images[].competition_reference_path` | string \| null | 否 | `聊天记录.image_path` | 原样保留；纯扩充图 null |

路径目录 → `declared_view_type`：

| `image_path` 目录 | `declared_view_type` |
|---|---|
| `broken_pump`、`short_item`、`missing_item`、`wrong_shade`、`swatch` | `ISSUE_DETAIL` |
| `broken_parcel` | `PACKAGE_CONTEXT` |
| `live_promise`、`refund_screenshot`、`logistics_screenshot`、`consult_card` | `OTHER` |
| 无法判定 | `OTHER` |

**必须遵守的约束（OI-01）：** `schemas/case-input.schema.json` 里 `evidence_images[].source_kind` 只允许两个团队素材枚举，因此赛事 `image_path` **不能**单独构成一条证据条目。每条赛事引用必须由团队合成对应素材后成对登记，赛事路径只保留在 `competition_reference_path` 字段。这与 `fixtures/README.md` 与 `fixtures/demo-cases.json` DEMO_001 的处理方式一致。P0 只需覆盖 `S00001` 这一条。

### 4.6 当前问题

| 目标路径 | 类型 | 必填 | 来源 | 转换 |
|---|---|---|---|---|
| `current_issue.fulfillment_item_id` | string | 是 | 派生 | `{订单号}-{问题商品货号}` |
| `current_issue.sku_id` | string | 是 | `订单.商品货号` + 聊天语义 | 取当前问题指向的商品 |
| `current_issue.issue_type` | enum | 是 | `scene_minor` + 聊天语义 | 见下表 |
| `current_issue.affected_component` | enum | 否 | 聊天语义（人工标注） | 见下表 |
| `policy_requirement_id` | const | 是 | 常量 | `DEMO_POLICY_PACKAGE_DAMAGE_V1` |

`scene_minor` → `issue_type`（枚举仅三值）：

| `scene_minor` | `issue_type` |
|---|---|
| 破损换货、包裹破损、错发色号、漏发赠品、少发正装、包裹少件 | `PACKAGE_DAMAGE` |
| 物流停滞疑似丢件 | `LOGISTICS_STALLED` |
| 泛红刺痒、闷痘爆痘、过敏就医 | `ADVERSE_REACTION` |

聊天语义 → `affected_component`：

| 语义 | 取值 |
|---|---|
| 泵头、按压头 | `PUMP` |
| 瓶身、瓶体、玻璃渣 | `BOTTLE` |
| 瓶盖、盖子 | `CAP` |
| 封口、封膜 | `SEAL` |
| 外箱、包装盒、面单 | `OUTER_PACKAGE` |
| 无法判定 | `UNKNOWN` |

**注意：** `PACKAGE_DAMAGE` 是一个宽口径枚举。当聊天明确指向泵头、瓶身等组件时，用 `affected_component` 承载细分；不要为了细分而扩展 `issue_type` 的取值。

---

## 5. 派生字典（导入层必须实现）

### 5.1 赠品货号字典

订单表只给赠品名称，不给赠品货号。赠品货号可由 `补发换货工单` 的「发出商品货号 / 发出商品名称」唯一派生，8 个赠品与 8 个 `XLG` 码一一对应，无缺口：

| 赠品货号 | 赠品名称 | 赛事出现次数（订单表） |
|---|---|---:|
| `XLG5001` | 测试修护精华小样5ml | 7 |
| `XLG5002` | 测试舒缓面霜中样15ml | 8 |
| `XLG5003` | 测试积雪草修护霜小样10ml | 5 |
| `XLG5004` | 测试B5面膜体验装2片 | 13 |
| `XLG5005` | 测试丝绒唇釉小样1.2g | 9 |
| `XLG5006` | 测试卸妆棉便携装20片 | 5 |
| `XLG5007` | 测试护发精油小样10ml | 9 |
| `XLG5008` | 测试发膜体验装30ml | 3 |

已核对：订单表的 8 个赠品名称全部能在该字典命中，命中率 100%。

### 5.2 正装货号字典

20 个 `商品货号` 与 `商品名称` 一一对应，无重名冲突，导入层可直接建 `sku_id → product_name` 只读字典，用于校验聊天中提到的商品是否与订单一致。

---

## 6. 派生契约说明（禁止由赛事字段直填）

### 6.1 `ExtractedJourney`

由唯一多模态模型从 `CaseInput` 产出。赛事字段对它的作用是**输入约束**，不是映射：

| 输出字段 | 允许的输入 | 明确禁止的输入 |
|---|---|---|
| `promise_events` | 仅 `speaker = AGENT` 的消息文本 | 承诺是否有效、是否超时、承诺类型结论 |
| `image_observations` | `evidence_images` 对应的实际图片文件 | 证据最终状态、图中文字断言 |
| `journey_understanding` | 已脱敏的会话文本 | 情绪指数、责任方、防线结果 |
| `extracted_scope` | `order` 与 `current_issue` | 范围是否匹配的结论 |
| `source_trace` | 上述来源三元组 | 无来源的推断 |

### 6.2 `AccountabilityState` 与 `DecisionResult`

| 字段 | 产出方 | 赛事数据的作用 |
|---|---|---|
| `evidence_status` | 状态构建器（SKU 匹配 × 问题组件覆盖 × 可读性） | 只提供订单、工单、问题范围事实 |
| `active_commitments` | 承诺编译 + 人工确认 | 只提供工单事实用于校验 |
| `prohibited_actions` | 状态构建器 | 只提供「是否已有证据」「是否已有承诺」等事实 |
| `current_scope` | 服务端按 `case_id` 装载后计算 | 只提供订单与问题范围 |
| `decision` / `rule_id` | 体验防线规则 | **不映射**；规则不得按 `case_id` 分支 |

这与 `PRODUCT-FREEZE.md` 附录 P0-8 完全一致：请求体中出现的同名字段一律忽略。

---

## 7. `S00001` 全量映射示例

### 7.1 来源定位

| 内容 | 位置 |
|---|---|
| 聊天 | `聊天记录!A2:R7`（6 条消息） |
| 订单 | `订单!A45:S45` |
| 工单 | `补发换货工单!A10:S10` |
| 图片引用 | `聊天记录!P4`（第 3 条消息，`mock_images/broken_pump/S00001_03.jpg`） |

### 7.2 映射结果（赛事原始部分）

| 目标字段 | 值 | 来自 |
|---|---|---|
| `case_id` | `S00001` | `聊天记录!A2` |
| `order.order_id` | `6920185815517983396` | `订单!A45` |
| `order.original_logistics_number` | `773478190943155` | `订单!O45` |
| `order.items[0]` | `…-XC33003` / `XC33003` / 测试轻透粉底液30ml #N02自然色 / `PRIMARY` | `订单!E45:F45` |
| `order.items[1]` | `…-XLG5004` / `XLG5004` / 测试B5面膜体验装2片 / `GIFT` | `订单!R45` + 赠品字典 |
| `service_tickets[0].ticket_id` | `BH919209358357` | `补发换货工单!A10` |
| `service_tickets[0].status` | `进行中` | `补发换货工单!P10` |
| `service_tickets[0].executor_name` | `测试美妆分销中心` | `补发换货工单!N10` |
| `service_tickets[0].replacement_logistics_number` | `YT7667875838478` | `补发换货工单!L10` |
| `service_tickets[0].created_at` | `2026-05-05T10:29:45+08:00` | `补发换货工单!R10` |
| `service_tickets[0].completed_at` | `null` | `补发换货工单!S10` |
| `evidence_images[0].evidence_id` | `S00001_IMG_03` | 派生 |
| `evidence_images[0].source_message_id` | `80525870445254.PNM` | `聊天记录!C4` |
| `evidence_images[0].competition_reference_path` | `mock_images/broken_pump/S00001_03.jpg` | `聊天记录!P4` |
| `current_issue.sku_id` | `XC33003` | `订单!E45` + 聊天 |
| `current_issue.issue_type` | `PACKAGE_DAMAGE` | `聊天记录!J: 补发换货/破损换货` |
| `current_issue.affected_component` | `PUMP` | 聊天第 1 条「泵头是坏的」 |

### 7.3 承诺候选（必须由模型从 AGENT 消息抽取，不得预填）

| 消息 ID | 时间 | 原文 | 预期分类 | 预期生效 |
|---|---|---|---|---|
| `22703823958720.PNM` | 2026-05-05 10:24:13 | 收到亲，确认属包装破损，为您登记换货：先给您发全新的，收到后用包裹里的面单把坏的寄回就好，运费我们出~ | `STANDARD_APPROVED` | `ACTIVE` |
| `36199788469718.PNM` | 2026-05-05 10:27:37 | 换货单已创建，48小时内发出，给您带来不便啦~ | `STANDARD_APPROVED` | `ACTIVE`，截止 `2026-05-07T10:27:37+08:00` |

### 7.4 团队扩充部分（不属于赛事记录）

| 项 | 值 | 标记 |
|---|---|---|
| 第二次进线消息 | `DEMO_AUG_MSG_001` | `DEMO_AUGMENTATION` |
| 泵头细节图、包装环境图 | `s00001-pump-detail.jpg`、`s00001-package-context.jpg` | `TEAM_SYNTHETIC_AUGMENTATION` |
| 泵头复刻图 | `s00001-product-overview.jpg` | `TEAM_SYNTHETIC_RECREATION` |
| `evaluation_time` | 见 OI-03 | 团队设定 |

---

## 8. 不进入映射的字段

| 字段 | 原因 |
|---|---|
| 三表的 `店铺` | 全表常量，无信息量 |
| `聊天记录.chat_content` | 与 `message_text` 一一对应的冗余结构 |
| `聊天记录.is_target_buyer_message` | 与「角色 = 买家」完全等价 |
| `聊天记录.买家昵称`、`发送方` | PII，且会话 ID 已覆盖其关联作用 |
| `订单.收货省`、`收货市`、物流工单的 `收货省`、`收货市` | PII，字段级掩码，不进模型 |
| `线下打款工单.支付宝实名`、`支付宝账号` | PII |
| `不良反应工单.年龄`、`不适部位`、`症状描述` | 健康类敏感信息，掩码后才可进 Prompt |
| 各表 `处理人`、`发货仓库`、`发货仓` | 内部组织信息，不对外展示 |
| `订单.买家留言` | 52 单为空且仅 3 种模板取值，P0 不强制映射 |

---

## 9. 待裁决口径问题

发现冲突时按 `AGENT-HANDOFF-PROTOCOL.md` 的要求同时列出双方路径，不自行选择方向。

| 编号 | 冲突 | 双方证据 | 影响 | 归属 |
|---|---|---|---|---|
| OI-01 | 赛事图片引用不能直接构成证据条目 | `schemas/case-input.schema.json`（`source_kind` 仅两个团队枚举）↔ `fixtures/README.md`（工作簿无图片文件） | 29 条引用需团队合成素材后成对登记 | 已澄清，A 线提供素材清单 |
| OI-02 | 赠品 SKU 代号不一致 | 赛事字典 `XLG5004` ↔ `fixtures/demo-cases.json` 的 `GIFT-B5-MASK-2` | D 线验收比对歧义 | 产品负责人 |
| OI-03 | Hero 评估时间与第二次进线时间不一致 | `PRODUCT-FREEZE.md` 附录 P0-4（09:32 / 09:40）↔ `fixtures/demo-cases.json` DEMO_001（10:45 / 11:00） | 按 11:00 评估时承诺已过期，与「即将到期」口径冲突，直接影响 `AT_RISK` 演示 | 产品负责人 |
| OI-04 | 工单状态字段名与取值不统一 | 三表用「工单状态」↔ 两表用「任务状态」，共 6 个取值，赛事未定义流转 | 导入层需归一 | 已澄清，B 线实现 |
| OI-05 | 赠品列与客服口述冲突 6 例 | `01-数据字段确认.md` 第 6.2 节 | 赠品归属可能被聊天口述带偏 | 产品负责人 |

---

## 10. 验收检查点（D 线可用）

| 编号 | 检查 | 通过标准 |
|---|---|---|
| M1 | 8 表全部读入，表头无遗漏 | 7 个业务表分别读到 998 / 113 / 24 / 13 / 15 / 10 / 18 行 |
| M2 | 长数字精度 | 随机抽 20 个订单号、工单号、物流单号，字符串长度与末位与源文件一致 |
| M3 | 关联完整性 | 工单→订单→会话三段关联缺失 0 条 |
| M4 | 商品行构造 | 113 笔订单生成的正装行 = 113，赠品行 = 59 |
| M5 | 赠品字典命中 | 59 条赠品全部命中 `XLG5001`–`XLG5008` |
| M6 | 时间格式 | 所有时间字段为带 `+08:00` 的 ISO8601 |
| M7 | 金额规整 | 不再出现 `8.8000000000000007` 一类原始浮点残留 |
| M8 | 来源可追溯 | 任一案例的订单、工单、消息都能定位回具体表与行号 |
| M9 | 脱敏生效 | 模型输入日志中不出现手机号、收货省/市、支付宝账号、症状原文 |
| M10 | 禁止直填 | `CaseInput` 中不出现 `evidence_status`、`active_commitments`、`prohibited_actions`、`current_scope`、`decision` |

数据来源与标注口径见 `05-证据来源说明.md`。
