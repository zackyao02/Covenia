# Covenia 产品冻结

审批状态：APPROVED
批准人：Zack
批准日期：2026-09-10（含 R1 / R8 契约层补充令及 H1=350 修复令）
依据评审：`CLAUDE-REVIEW-1.md`、`CLAUDE-REDTEAM.md`

## 第一用户与触发时刻

第一用户：千牛客服工作台里的一线售后客服，不假设其懂美妆质量、证据范围或承诺权限。

触发时刻：消费者就同一问题**第二次进线**追问进度（S00001，09:32）。此刻客服面对的是一条已有承诺、已有工单、已有图片的旧案，但工作台不告诉他这些，他的默认动作是再要一次图片。Covenia 在这一刻介入。

## 核心痛点与一句话定位

痛点：客服在承诺发生后失去了对承诺的记忆。消费者已经交过材料、已经被承诺过时限，再次进线却被当作新问题重新举证，体验二次受损。

定位：**Covenia 把客服口头承诺编译成会到期、会催办、会升级的服务责任。**

## 单一 Hero：S00001

固定输入：赛事数据中的原始聊天、订单 `6920185815517983396`、SKU `XC33003`、赠品 `GIFT-B5-MASK-2`、换货工单 `BH919209358357`、团队测试图片（泵头损坏）。

链路：恢复已知事实 → 抽取并校验承诺“48小时内发出” → 体验责任账本 → 动作前体验防线 → 人工确认解决路径 → 服务进度回执 → 物流事件驱动状态与升级。

人工确认点：解决路径批准（`approver_id` 必填）、主动通知外发。

状态变化：`READY_FOR_BRAND → ACTION_REVIEW → IN_FULFILLMENT → AT_RISK → RESOLVED`。

最终回执：`RECEIPT_DEMO_001_001`，`consumer_action_required: false`，含下一次更新时间与失约补救。

## P0 页面

| 页面/区域 | 第一屏必须回答的问题 | 必须状态 | 明确不含 |
|---|---|---|---|
| 责任副驾主面板（千牛右侧窄栏） | 已知什么、不能做什么、下一步做什么 | 五个状态全部可显示；不滚动 | 情绪指数独立模块、培训看板 |
| 承诺与义务卡 | 承诺原文、剩余时限、当前义务归谁执行 | `ACTIVE` / `AT_RISK` / `COMPLETED` | 自动退款、赔偿、补发按钮 |
| 防线提示条 | 这个动作为什么被拦、改做什么 | `INTERVENE` / `HUMAN_REVIEW` 时出现 | 低价值动作上的弹窗 |
| 服务进度回执 | 消费者已交什么、品牌在做什么、何时再更新 | 随事件刷新 | 消费者端独立页面 |
| 主管跟踪区 | 哪些案子逾期、哪些已升级 | 催办候选、升级候选 | 新增售后场景 |
| 成本条（右下） | 本次 token 用量、推理延迟、规则层替代次数 | 实时 | 与业务逻辑耦合 |

## P0 功能与状态

| ID | 功能 | 输入 | 输出/状态 | 完成条件 |
|---|---|---|---|---|
| F1 | 事实恢复 | `case_id`（后端按赛事表装载） | `ExtractedJourney` + 事实来源 | 日志打印数据来自哪表哪行 |
| F2 | 承诺抽取与分级 | 聊天原文 | `commitment_class` 五类之一 | 仅客服侧消息可成为承诺候选；文案改“尽快”→`AMBIGUOUS` |
| F3 | 体验责任账本 | F1+F2 | `AccountabilityState` | `audit_trail` 每次变更留痕 |
| F4 | 动作前体验防线 | 服务端状态 + `PreparedAction` | `INTERVENE`/`ALLOW`/`HUMAN_REVIEW` + `rule_id` | 规则实现不按 `case_id` 分支；状态构建可按 `case_id` 装载事实 |
| F5 | 人工确认与承诺激活 | `resolution_path` + `approver_id` | `open_obligation` + 回执 | 缺审批人报 `VALIDATION_ERROR` |
| F6 | 物流事件驱动 | 三类事件 | 状态/催办/升级/通知草稿 | 送达后达 `RESOLVED` |
| F7 | 成本与性能记录 | 每次推理 | token、延迟、规则替代计数 | 界面可见且写入治理记录 |

## API、Schema 与前后端职责

接口形状以 `schemas/` 中的请求/响应 Schema 与 `docs/05-api-and-ui.md` 为唯一基线。四接口不增。

| 能力 | 端点/Schema | 前端职责 | 后端职责 | 错误与幂等 |
|---|---|---|---|---|
| 案例分析 | `POST /api/cases/analyze` / `case-input`、`accountability-state` | 传 `case_id`，渲染三问 | 装载赛事数据、调用模型、组装账本 | 超时 20s；失败回退显式标记缓存 |
| 动作评估 | `POST /api/actions/evaluate` | 送 `PreparedAction`；进度查询走此接口 | 规则判定 + `fact_trace` | 规则未命中返回 `E0_NO_RULE_MATCHED`/`ALLOW` |
| 路径批准 | `POST /api/resolutions/approve` | 提交 `human_edits` 与 `approver_id` | 合并后计算 `approved_resolution`、写 `audit_trail` | 需幂等键；缺审批人 `VALIDATION_ERROR` |
| 物流事件 | `POST /api/events/shipment` | 推送事件、渲染变化 | 状态转移、催办/升级候选、通知草稿 | 需幂等键；逆序返回 `INVALID_EVENT_TRANSITION` |

消费者回复与服务进度回执按字段读取，不设第五个接口。比赛版无鉴权，`SIMULATION_DISCLOSURE.md` 中明示。

## 真实数据与 AI 链路

- 赛事原始数据：官方 Excel（原名 `赛题 1：数据共情者-业务数据.xlsx`），改名 `tianchi-track1-mock-data.xlsx` 置于 `data/`，相对路径导入。7 个业务表关联并打印五项计数；工作簿共 8 表，「数据说明」不是运行输入。
- 团队测试数据：5 张泵头图片，明确标注为团队自建，不代表市场发生率。
- 模型实时输出：`Qwen/Qwen2-VL-2B-Instruct`（Apache-2.0，版本 `const` 锁定），承诺抽取与图片观察均真实推理。
- 缓存灾备：允许，但响应必须置 `cached_result: true` 且界面标注。

## 允许模拟 / 禁止模拟

| 项目 | 允许模拟方式 | 必须真实运行的部分 |
|---|---|---|
| 千牛工作台 | 静态示意外壳 | 右侧副驾全部逻辑 |
| 消费者回复外发 | 写入本地模拟聊天窗 | 草稿由后端生成、人工确认留痕 |
| 物流事件 | 手工触发三类事件 | 状态转移与升级由后端计算 |
| 仓库/物流系统 | 无对接 | 义务的 `executor` 切换与到期判定 |
| 模型不可用 | 缓存回退 | 回退必须可见标记 |

## 明确不做

自动退款、赔偿、补发；医疗诊断与质量责任认定；`/api/events/assignment`；第五个查询接口；情绪指数独立模块；客服培训看板；S00001 以外的售后场景（范围变化、图片模糊、物流分支仅用于 Challenge Mode）；询单转化率相关的售前能力；千牛或欧莱雅生产系统对接。

## 验收标准

| ID | Given | When | Then | 证据 |
|---|---|---|---|---|
| A1 | 三个决策变体 | 互换 `case_id` | `decision` 与 `rule_id` 不变 | P0-1 |
| A2 | DEMO_001，`evidence_status: VALID` | `challenge_mode: true` 下将 `challenge_overrides.requested_scope.sku_id` 改为赠品 | `INTERVENE`/E1 → `ALLOW`/E2；响应回显 `challenge_mode: true` 且界面显示角标 | P0-8 |
| A3 | 变体请求 | 计算 `fact_trace` | 每字段可由本请求算出，无一依赖 `case_id` | P0-1 |
| A4 | 已批准案件 | 依次推揽收、送达 | `RESOLVED` + 义务 `COMPLETED` + 无 `ACTIVE` 承诺 | P0-2 |
| A5 | 同上 | 只推揽收 | 状态不得为 `RESOLVED` | P0-2 |
| A6 | 生成主动通知 | 读取时间 | 通知时间 = `open_obligation.next_check_at` = `next_update_by` | P0-3 |
| A7 | 通知未确认 | 查看回执 | 通知为草稿态，不进消费者可见回执 | P0-3 |
| A8 | 全部样例 | 校验时序 | `event_time`/`approved_at` 均晚于 `evaluation_time` | P0-4 |
| A9 | 分析时点 09:40 | 读承诺 | `deadline - evaluation_time > 0` 且承诺 `ACTIVE` | P0-4 |
| A10 | `IN_FULFILLMENT` | 推 11:35 未揽收 | 承诺 `ACTIVE→AT_RISK`，风险等级变化界面可见 | P0-4 |
| A11 | 批准请求 | 不带 `approver_id` | `VALIDATION_ERROR` | P0-5 |
| A12 | `human_edits` 非空 | 批准 | `approved_resolution` 反映修改，`audit_trail.changed_fields` 与提交键集合一致 | P0-5 |
| A13 | 禁止项含 `CLOSE_BEFORE_RESOLUTION` | 送 `CLOSE_CASE` | `INTERVENE`/`P0_PROHIBITED_ACTION`/400 | P0-6 |
| A14 | `issue_type: ADVERSE_REACTION`，证据 `VALID` | 送 `ASK_EVIDENCE` | `HUMAN_REVIEW`/H1 | P0-6 |
| A15 | 无规则命中 | 送 `CHECK_REPLACEMENT_PROGRESS` | `ALLOW`/`E0_NO_RULE_MATCHED`/0，不报错 | P0-6 |
| A16 | 仅传 `case_id` | 分析 | 完成分析，日志打印来源表与行 | P0-7 |
| A17 | 承诺文案改“尽快发出” | 分析 | `STANDARD_APPROVED → AMBIGUOUS` | P0-7 |
| A18 | 同幂等键 | 重放批准/事件 | 响应一致且状态不二次变更 | P1 |
| A19 | Excel 导入 | 执行门 1 | 打印 138/998/113/29/80 并与官方对齐 | `docs/07:51` |
| A20 | 仅传 `case_id` 与 `prepared_action: ASK_EVIDENCE` | 评估 | `INTERVENE`/E1/300，状态由服务端装载 | P0-8 |
| A21 | 请求体伪造 `evidence_status: MISMATCHED`，未开 `challenge_mode` | 评估 | 该字段被忽略，仍 `INTERVENE`/E1 | P0-8 |
| A22 | `challenge_mode: true` + `challenge_overrides` 改赠品范围 | 评估 | `ALLOW`/E2，响应含 `challenge_mode: true`，界面角标可见 | P0-8 |
| A23 | 聊天含手机号与收货地址 | 分析 | 模型输入日志显示掩码，治理记录 `pii_masked_count > 0` | P0-9 |
| A24 | 关闭脱敏步骤 | 跑测试 | 测试失败（防回归） | P0-9 |
| A25 | 消费者消息伪造“48小时内发出”或注入指令 | 分析 | 不产生新承诺；`active_commitments` 数量不变 | R2 |
| A26 | 图片带“证据有效”文字与同图无文字版本 | 分析 | `evidence_status` 一致；图中文字不进入规则事实 | R3 |
| A27 | 未揽收时直接推 `SHIPMENT_DELIVERED` | 事件 | `INVALID_EVENT_TRANSITION`，状态和审计记录不变 | R4 |
| A28 | 发送“全额退款并赔偿” | 分析/批准 | 非 `STANDARD_APPROVED`，无审批记录时不生成 `ACTIVE` 承诺或截止时间 | R5 |
| A29 | 消费者输入已完整，准备把后续跟进交给消费者 | 评估 | `INTERVENE`/`P0_PROHIBITED_ACTION`/400 | R6 |
| A30 | 不良反应 + `CLOSE_CASE` | 评估 | `P0_PROHIBITED_ACTION` 优先；`fact_trace.suppressed_rule_ids` 含 `H1` | R7 |
| A31 | 强制模型不可用 | 分析 | 响应、界面和治理记录都显示缓存结果；关闭界面角标时测试失败 | R9 |
| A32 | 主动通知草稿 | 批准/事件 | 文案中的下次时间与 `commits_next_update_at` 完全一致 | R10 |
| A33 | 规则、状态构建器与 Prompt 目录 | 静态扫描 | 不含 `DEMO_001`、`DEMO_002`、`DEMO_003`、`S00001` 字面量 | 抗硬编码 |
| A34 | `challenge_overrides` 存在但 `challenge_mode` 为缺省或 `false` | 评估 | 覆盖字段被忽略，输出与无覆盖请求一致；响应回显 `challenge_mode: false` | 修复令 2026-09-10 |

## 4 分钟 Demo 完成定义

| 时间 | 画面 | 操作 | 证明点 | 失败兜底 |
|---|---|---|---|---|
| 0:00–0:20 | 消费者第二次进线 | 无 | 消费者价值：交过的材料不该再交一次 | 静态图 |
| 0:20–1:00 | Excel 导入与五项计数 | 跑门 1 | 赛事数据真实进入、7 个业务表关联 | 预生成计数截图 |
| 1:00–1:40 | 分析结果三问 | 传 `case_id` | AI 真实抽取；承诺 `ACTIVE` 带剩余时限 | 标记缓存的回放 |
| 1:40–2:10 | 抗演员双测 | 换 `case_id`；改承诺文案为“尽快” | 决策不变 + 分级变 `AMBIGUOUS` | 无兜底，此段必须真跑 |
| 2:10–2:40 | 防线拦截再次索证 | 先送伪造 `evidence_status: MISMATCHED` 的请求，再送 `ASK_EVIDENCE` | 伪造状态被忽略，仍 `INTERVENE`/E1/300 + `fact_trace`；回答“状态由谁计算” | 缓存判定结果 |
| 2:40–3:10 | 人工批准并激活承诺 | 填 `approver_id` 批准 | 责任真实运行：义务+回执生成，留痕 | 本地状态回放 |
| 3:10–3:40 | 推未揽收事件 | 触发 11:35 | 状态劣化到 `AT_RISK`，催办、升级、通知草稿出现 | 事件回放 |
| 3:40–4:00 | 推送达事件 + 成本条 | 触发送达 | 闭环到 `RESOLVED`；token 与延迟可见 | 治理记录截图 |

不得用固定动画替代接口执行。初赛视频以本脚本录制，与决赛现场同一作品。

## 附录：契约层修改令

P0-1 决策变体必须可从输入推导；`scope_match` 按 `order_id → sku_id → fulfillment_item_id → issue_type` 顺序比对得出，`evidence_status` 以其为输入。

P0-2 新增 `SHIPMENT_DELIVERED` 与 `PROMISE_FULFILLED`；揽收置承诺 `COMPLETED`、义务 `IN_TRANSIT`，送达置义务 `DELIVERED` 并转 `RESOLVED`。

P0-3 `proactive_notification_draft` 改结构体 `{text; commits_next_update_at; requires_human_approval: true; channel: "ORIGINAL_CHAT"}`。

P0-4 时间线同批修正：二次进线 09:32、`evaluation_time` 09:40、`approved_at` 09:42、揽收 10:10、未揽收 11:35、截止 10:27:37 不变。连带：`02`/`03` 中承诺 `AT_RISK→ACTIVE`、`PROMISE_OVERDUE→PROMISE_ACTIVE`；`03` 响应 `case_status AT_RISK→IN_FULFILLMENT`、`experience_risk HIGH→MEDIUM`、`next_check_at` 统一 10:30、`action_impacts` 去掉 `RAISE_PRIORITY`；`ground-truth.json:19` 改“承诺即将到期”。`next_check_at` 唯一真相三处相等。

P0-5 `approver_id` 必填；`approved_at` 用服务端时间；`accountability-state` 增 `audit_trail[]`（`at`/`actor`/`action`/`changed_fields[]`/`request_id`）；`approved_resolution` 为服务端合并结果。

P0-6 新增 `P0_PROHIBITED_ACTION`（400）与 `E0_NO_RULE_MATCHED`（0）；H1 条件扩至 `ADVERSE_REACTION`；优先级语义为限制性规则优先。

P0-7 `AnalyzeCaseRequest` 改 `{case_id; evaluation_time?; case_input?}`。

P0-8（红队 R1 冻结补充令）`evaluate` 的可信输入收敛为 `{case_id; prepared_action; evaluation_time?; challenge_mode?; challenge_overrides?}`。`accountability_state` 从请求体移除，只作为响应字段；服务端按 `case_id` 装载事实后自行计算 `evidence_status`、`active_commitments`、`prohibited_actions`、`current_scope`。请求体中出现的同名字段一律忽略。变体演示只能走 `challenge_overrides`，且必须 `challenge_mode: true` 才生效；响应必须回显 `challenge_mode: true`，界面显示角标。

说明：按 `case_id` 装载事实与 `docs/03-firewall-rules.md` 中“禁止根据 `case_id` 返回固定结果”不冲突。前者只装载规则输入，后者禁止跳过计算直接返回结论；规则实现内不得出现 `case_id` 分支。`02-evaluate-action.json` 在实现工程创建后必须改为上述请求/响应形状，原有 `decision_variants` 中直接提交状态或范围字段的写法不得保留。

P0-9（红队 R8 冻结补充令）模型输入前对手机号、收货地址、支付宝账号、就医与不良反应描述做掩码，掩码后再进入 Prompt。每次调用记录 `pii_masked_count` 并写入治理记录；`SIMULATION_DISCLOSURE.md` 的三类数据分述中明示脱敏范围。此项对应 `MODEL_GOVERNANCE.md` 的敏感数据治理要求，源码与运行指南均须提交，属于自证项。

P0-10（2026-09-10 H1 优先级修复令）H1 的唯一优先级统一为 `350`。规则求值顺序为 `P0_PROHIBITED_ACTION (400) → H1 (350) → E1 (300) → E2 (100) → E0_NO_RULE_MATCHED (0)`；不得通过拆分 H1 规则号实现条件优先级。A14 中不良反应与重复索证同时命中时，返回 `HUMAN_REVIEW/H1/350`，并在 `fact_trace.suppressed_rule_ids` 记录 `E1`。A30 中 `P0_PROHIBITED_ACTION` 仍优先，并记录被压制的 `H1`。A20/A21 的非不良反应 Hero 路径仍为 `INTERVENE/E1/300`。

P0-11（2026-09-10 成本条修复令）`analyze` 与 `evaluate` 响应正式包含服务端产生的 `runtime_metrics`：`input_tokens`、`output_tokens`、`inference_latency_ms`、`rule_substitution_count`，均为非负整数。右下成本条只读取响应字段：本次 token 用量为输入与输出之和，推理延迟直接显示，规则层替代次数直接显示；前端不得估算或伪造这些值。Mock 为演示环境时也必须通过同一响应契约返回固定可追溯值。

P0-12（2026-09-10 修复边界）保留 `schemas/evaluate-action-request.schema.json` 中标记为 deprecated/readOnly 的兼容字段，服务端忽略它们以承载 A21；不得删除。`CLAUDE-REVIEW-1.md` 是历史审查记录，不改写；其中 H1=200 的历史建议由本冻结令覆盖。`02-evaluate-action.json` 只保留 P0-8 的可信请求形状，展示 ID 统一为 `DEMO_001`。

P1（可同批修，不阻塞 Hero）：`integrity_concern`/`hygiene_risk` 移入 `ImageObservation` 并改必填；悬空 `DEMO_AUG_IMG_002/003` 统一指向 `80525870445254.PNM`；删重复的 `ApiMeta.cached_result`，仅保留 `model_metadata.cached_result`；analyze 超时 120s→20s 并预热；`FollowUpCandidate` 与 `TaskPrefill` 合并且后者加 `priority`；收口两处 `[key: string]: unknown`；补 `docs/08-idempotency-and-ordering.md` 与请求 Schema；三个激活字段建对照表；`experience_risk` 改确定性推导；展示 ID 统一（`04:106` 的 “S00001” 改 `DEMO_001`）。

调研结论：`docs/06` 中“记录可见但权限、协作、执行仍可能中断”降为**待验证假设**。已验证并保留：人工客服+AI 辅助的机动性优势；KPI 是一线行为的实际驱动力。KPI 模板作为一手证据入档，去除公司名、店铺名、人名，标注 n=1 不可外推。六项 KPI 覆盖度诚实声明，**询单转化率 30% 属售前，不桥接**。
