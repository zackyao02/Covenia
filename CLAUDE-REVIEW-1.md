# Covenia Competition MVP v0.7｜开发前终审（CLAUDE-REVIEW-1）

审查基线：仓库当前状态（`README.md`、`PRODUCT_BLUEPRINT.md`、`TEAM_AND_TIMELINE.md`、`docs/00`–`docs/07`、`schemas/*.schema.json`、`fixtures/*.json`、`fixtures/README.md`、`MODEL_GOVERNANCE.md`、`SIMULATION_DISCLOSURE.md`、`AGENT-HANDOFF-PROTOCOL.md`）。
仓库内不存在任何实现代码、图片素材、TypeScript 类型或接口样例；不存在 `PRODUCT-FREEZE.md`、`IMPLEMENTATION-STATUS.md`、`CLAUDE-REDTEAM.md`、`FIX-REQUESTS.md`。本轮结论基于文档与 Schema 的静态交叉核对，未运行任何代码。

---

## A. 总体裁决

**有条件通过。**

产品定位、Hero 边界、禁止项和数据披露口径在 `README.md`、`PRODUCT_BLUEPRINT.md`、`docs/00-product-p0.md`、`SIMULATION_DISCLOSURE.md` 之间是自洽的，不需要重新设计产品。范围收敛已经做到位：一个 Hero（`S00001`）、三条规则（`E1/E2/H1`）、四个接口、五个 Schema、六个状态。这一层可以直接进入冻结。

不能立即开发的原因集中在**契约层的空洞**，不在产品层：

1. `evidence_status` 是整条链路的唯一枢纽（`E1/E2/H1` 全部以它为条件，见 `docs/03-firewall-rules.md`），但从 `image_observations` 推导 `evidence_status` 的确定性函数在任何文档中都没有定义。`docs/02-ai-extraction.md` 第 2 节只写了“这些观察进入确定性证据判断”。没有这张判定表，三个案例无法证明不是按 `case_id` 写死，`docs/07-demo-and-delivery.md` 的门 3 无法验收。
2. `POST /api/resolutions/approve` 与 `POST /api/events/shipment` 的请求体、响应体、审批人、幂等键均无 Schema。`docs/04-responsibility-loop.md` 第 5 节要求人工可修正承诺分类、执行方、期限，但 `accountability-state.schema.json` 是 `additionalProperties: false` 且没有任何审计/留痕字段，人工修改在当前契约下无处可存。
3. `{ data, error, request_id }` 响应外壳、HTTP 与业务错误码在 `docs/05-api-and-ui.md` 中完全没有出现。
4. 六个业务状态只有枚举（`docs/00-product-p0.md` 第 6 节），没有迁移表。四人并行开发会各写一套状态机。
5. Hero 案例的时间轴自身矛盾：`fixtures/demo-cases.json` 的 `evaluation_time` 已晚于 `fixtures/ground-truth.json` 的承诺截止时间，导致 `docs/07-demo-and-delivery.md` 2:25–3:15 的“未到期/已到期”双分支在主 Demo 上不可能同时成立。
6. 门 2 所需的 5 张图片素材（`fixtures/README.md`）在仓库中不存在，AI 真实性目前是 0 证据。

按 `TEAM_AND_TIMELINE.md` 倒排，`9/12–9/18` 要求 `S00001` 纵向链路打通。当前（9/8）尚未通过 G2，且无任何实现产物。以上 1–6 项若不在冻结文件中定稿，后端、前端、数据三条线会在 9/12 之前产生不可合并的分歧。

---

## B. 证据冲突与缺口

| # | 文件路径 | 当前表述 | 冲突 / 缺失 | 必须由谁冻结 |
|---|---|---|---|---|
| B1 | `CLAUDE-PREFLIGHT-REVIEW.md:62` vs `docs/05-api-and-ui.md:28` | 前者写 `POST /api/events/assignment`，后者定义 `POST /api/events/shipment` | 事件接口路径两处不一致 | 产品负责人：只保留 `POST /api/events/shipment` |
| B2 | `docs/05-api-and-ui.md` 第 1 节 | 只列出四个接口的输入/输出对象名 | 无响应外壳、无 HTTP 码、无业务错误码、无超时、无幂等键 | 产品负责人 |
| B3 | `schemas/` 目录 | 只有 5 个 Schema：`case-input`、`extracted-journey`、`accountability-state`、`decision-result`、`prepared-action` | `resolutions/approve` 请求体、`events/shipment` 请求体、两者响应体无 Schema | 产品负责人 |
| B4 | `docs/04-responsibility-loop.md:56-58` vs `schemas/accountability-state.schema.json:6` | 文档要求人工可修正承诺分类、执行方、期限、业务动作 | `additionalProperties: false` 且无 `human_overrides` / `audit_trail` / `approved_by` / `approved_at` 字段 | 产品负责人 |
| B5 | `docs/05-api-and-ui.md:31` vs `schemas/accountability-state.schema.json` | 事件接口输出“催办候选与消费者主动通知草稿” | `AccountabilityState` 无催办候选、无升级候选、无通知草稿字段；这些字段只存在于 `DecisionResult.resolution_path`（防线输出，非事件输出） | 产品负责人 |
| B6 | `fixtures/demo-cases.json:16` vs `fixtures/ground-truth.json:14` | `evaluation_time = 2026-05-07T11:00:00+08:00`；`deadline = 2026-05-07T10:27:37+08:00` | 主案例在分析时刻已逾期 32 分钟，与 `docs/04` 第 4 节“若尚未到期：保持 `ON_TRACK`”分支互斥，与 `docs/04:31` 回执样例“最迟更新 10:27 前”互斥（`next_update_by` 会落在过去） | 产品负责人 |
| B7 | `docs/03-firewall-rules.md` 全文 | `E1/E2/H1` 均以 `evidence_status` 为输入 | `evidence_status = f(image_observations, current_issue, order)` 的判定表不存在 | 产品负责人 |
| B8 | `schemas/decision-result.schema.json:11-12` | `rule_id` 枚举仅 `E1/E2/H1`，`rule_priority` 仅 `300/200/100`，且均为 `required` | 无“无规则命中”表示法。`prepared-action.schema.json:11` 允许 `CHECK_REPLACEMENT_PROGRESS`、`CREATE_FOLLOW_UP_TASK`、`CLOSE_CASE`，这三种动作调用 `evaluate` 时无法构造合法响应；`evidence_status=VALID` 且范围不等时同样无规则命中 | 产品负责人 |
| B9 | `schemas/accountability-state.schema.json:55` vs `schemas/prepared-action.schema.json:11` | 禁止动作码 `ASK_SAME_EVIDENCE`/`CLOSE_BEFORE_RESOLUTION` 与动作码 `ASK_EVIDENCE`/`CLOSE_CASE` | 两套枚举之间的映射关系未定义 | 产品负责人 |
| B10 | `schemas/case-input.schema.json:118-120` vs `docs/01-core-contracts.md:29` | `current_issue` 预填 `integrity_concern`、`hygiene_risk`；`docs/01` 声明 `CaseInput` 不含证据最终状态 | 完整性与卫生风险是质量判断，`docs/02:18` 要求由模型从图片输出（`image_observations.integrity_concern` / `hygiene_risk_signal`）。同一结论在输入与输出各存一份，且 `demo-cases.json` 中 DEMO_001 填 `MEDIUM`、DEMO_003 填 `UNKNOWN`，构成按案例预置提示 | 产品负责人 |
| B11 | `docs/02-ai-extraction.md:5` vs `schemas/extracted-journey.schema.json:134` | 文档允许切换同系列更高版本；Schema 中 `model_id` 是 `const: "Qwen/Qwen2-VL-2B-Instruct"` | Schema 禁止文档允许的行为 | 产品负责人 |
| B12 | `docs/02-ai-extraction.md:40` | 承诺校验使用“工单、权限与模拟政策规则” | `CaseInput` 无客服角色、权限或额度字段，`APPROVAL_REQUIRED` 与 `ERRONEOUS_OR_UNAUTHORIZED` 无数据可校验 | 产品负责人 |
| B13 | `schemas/extracted-journey.schema.json:29-56` | `promise_events` 有 `source_ids`，无发话人字段 | 无法在 Schema 层区分“客服作出的承诺”与“消费者/系统文本中出现的承诺句”，构成注入面（见 G2） | 产品负责人 |
| B14 | `fixtures/demo-cases.json:111,120` | DEMO_001 两张图片 `source_message_id = DEMO_AUG_IMG_002 / DEMO_AUG_IMG_003` | 这两个 ID 不在 `conversation` 的任何 `message_id` 中；三张图 `submitted_at` 均为 `10:21:38`，等于消息 `80525870445254.PNM` 的时间。来源不可核验，违反 `docs/05:57` 的“规则来源可展开”与门 5 | 产品负责人 |
| B15 | `fixtures/README.md:6-12` | 列出 5 个必需 jpg 文件名 | 仓库中 0 个图片文件存在 | 产品负责人 + A 数据线 |
| B16 | `docs/00-product-p0.md:60-66` | 列出六个业务状态 | 无迁移表：哪个动作/事件触发哪条边、`RESOLVED` 的唯一入口条件 | 产品负责人 |
| B17 | `fixtures/ground-truth.json` | 三个案例只断言 `evidence_status`、`decision`、`rule_id`、`priority`、`candidate_type`、`creates_obligation` | 未断言 `case_status`、`prohibited_actions`、`next_check_at`、`consumer_input_required`，这些字段无验收基线 | 产品负责人 + A 数据线 |
| B18 | `docs/06-evaluation-and-research.md:60` | 评委至少可修改图片清晰度、当前商品、承诺时间、物流状态 | `docs/05-api-and-ui.md` 的界面约定只提供物流事件按钮，另外三项无入口 | 产品负责人 |
| B19 | `CLAUDE-PREFLIGHT-REVIEW.md:50` | 六项客服 KPI 与权重 | 该权重体系不出现在任何产品文档中；`docs/06` 第 4 节的核心指标是另一套 | 产品负责人 |
| B20 | `docs/05-api-and-ui.md:71` | 回执“以聊天消息或消息卡片形式发送” | 未定义是后端真实动作、前端模拟渲染还是仅草稿；无千牛账号（`docs/00:70`） | 产品负责人 |
| B21 | `README.md:49` / `docs/00-product-p0.md:47` vs `fixtures/README.md` | 前者“三张美妆测试图片”，后者 5 张 | 三张为 Hero 用量，另两张为 Challenge 用量；表述需统一，避免门 2 验收口径分歧 | 产品负责人 |
| B22 | `AGENT-HANDOFF-PROTOCOL.md:35` | G1 要求两份评审文件均非空 | `CLAUDE-REDTEAM.md` 不存在；`CLAUDE-REVIEW-1.md` 内容需在本次重定向后确认非空 | 产品负责人 |
| B23 | `docs/00-product-p0.md:35` / `PRODUCT_BLUEPRINT.md:85` | 不良反应工单为“高风险人工转交案例”；不自动诊断 | `issue_type` 枚举含 `ADVERSE_REACTION`，但 `E1/E2/H1` 全部只看 `evidence_status`，不良反应案例可能命中 `E2` 被放行，或无规则命中 | 产品负责人 |
| B24 | `fixtures/demo-cases.json` 全体 | `evaluation_time` 为固定注入值（2026-05） | 未声明禁止使用系统 `now()`。若倒计时读系统时间，演示日（2026-09/10）所有承诺逾期约 4 个月 | 产品负责人 |

待验证（材料未提供，不作为结论）：赛事工作簿本体、`mock_images/broken_pump/S00001_03.jpg`、阿里云实例规格与推理时延、问卷与访谈进度、`reference/Covenia_Competition_MVP_v0.7.docx` 与 Markdown 的一致性。

---

## C. P0 阻塞项

以下每项未解决前，禁止启动对应的开发工作。

### C1｜冻结 `evidence_status` 判定表

- 证据：`docs/03-firewall-rules.md:9-40` 三条规则全部以 `evidence_status` 为唯一条件；`docs/02-ai-extraction.md:20` 仅有“进入确定性证据判断”一句。
- 影响：判定函数缺失时，`DEMO_001=VALID / DEMO_002=MISMATCHED / DEMO_003=NEED_HUMAN_REVIEW`（`fixtures/ground-truth.json`）只能靠写死实现，`docs/07` 门 3 与 `docs/06` 第 5 节抗演员验证同时失败。
- 最小修改：在冻结文件中给出一张按顺序求值的判定表，输入只允许 `image_observations[]`、`CaseInput.current_issue`、`CaseInput.order.items[]`、`ExtractedJourney.extracted_scope`。建议定稿为：
  1. 任一图片 `readability = LOW` 或 `product_identifiable = false` 或 `sku_match = UNKNOWN` → `NEED_HUMAN_REVIEW`；
  2. `extracted_scope.sku_id ≠ current_issue.sku_id` → `NEED_HUMAN_REVIEW`（AI 与系统事实冲突，遵循 `docs/01:78-83` 优先级）；
  3. 存在 `sku_match = MISMATCH` 或 `product_role ≠ 订单中该 SKU 的 item_role` → `MISMATCHED`；
  4. 全部图片 `sku_match = MATCH` 且 `coverage` 并集 ⊇ `{PRODUCT_IDENTITY, AFFECTED_COMPONENT, DAMAGE_DETAIL}` 且存在一张 `affected_component = current_issue.affected_component` 且 `issue_visible = true` → `VALID`；
  5. 其余 → `NEED_HUMAN_REVIEW`。
- 验收条件：单元测试对上述五条分支各有 1 个用例共 5 个用例全部通过；`DEMO_001/002/003` 在不读取 `case_id` 的前提下命中第 4、3、1 条；代码中 `grep -R "DEMO_00" src/` 在规则与状态构建模块内返回 0 行。

### C2｜冻结四个接口的响应外壳与错误码

- 证据：`docs/05-api-and-ui.md` 第 1 节无外壳定义；`CLAUDE-PREFLIGHT-REVIEW.md:60` 提出 `{ data, error, request_id }`。
- 影响：前端（C 线）与后端（B 线）对失败态渲染无共同契约，模型失败降级（`docs/02:60-63`）无法在界面区分。
- 最小修改：四个接口统一 `{ data, error, request_id }`，`data` 与 `error` 互斥；`error = { code, message, retryable }`。业务错误码定稿为固定 6 项：`SCHEMA_INVALID`、`MODEL_UNAVAILABLE`、`MODEL_OUTPUT_INVALID`、`CASE_NOT_FOUND`、`DUPLICATE_EVENT`、`STATE_CONFLICT`。HTTP 映射：`400 / 503 / 422 / 404 / 200(幂等重放) / 409`。模型超时上限 20 秒。
- 验收条件：4 个接口 × 正常态 1 例 + 异常态 1 例 = 8 份 JSON 样例入库；`MODEL_UNAVAILABLE` 时界面显示“缓存抽取结果”标识（`MODEL_GOVERNANCE.md:52`），且后续规则与事件链仍返回真实计算结果。

### C3｜补齐 `approve` 与 `shipment` 的请求/响应 Schema 与人工留痕字段

- 证据：`schemas/` 缺两个请求 Schema；`schemas/accountability-state.schema.json:6` 为 `additionalProperties: false` 且无审计字段；`docs/04-responsibility-loop.md:56-58` 要求人工修正后以人工事实为最高优先级。
- 影响：人工修改无法持久化、无法展示、无法审计，`docs/04` 第 5 节与红队“人工修改未留痕”直接失败；事件接口的催办候选与通知草稿无返回位置。
- 最小修改：新增两个 Schema，并在 `AccountabilityState` 增加两个字段（属于契约补全，不新增模块或页面）：
  - `resolution-approval.schema.json`：`case_id`、`decision_ref`（`request_id`）、`candidate_type`、`commitment_activation`（`ACTIVATE` / `REJECT`）、`human_overrides[]`（`field_path`、`old_value`、`new_value`、`reason`）、`approver_id`、`approved_at`、`idempotency_key`。
  - `shipment-event.schema.json`：`case_id`、`event_id`、`event_type`（`SHIPMENT_PICKED_UP` / `SHIPMENT_NOT_PICKED_UP`）、`event_time`、`idempotency_key`。
  - `AccountabilityState` 增补：`audit_trail[]`（`actor_id`、`action`、`at`、`field_path`、`old_value`、`new_value`、`source`∈`HUMAN`/`RULE`/`EVENT`）与 `pending_candidates`（`follow_up_task`、`escalation_candidate`、`consumer_notification_draft`，均可为 `null`）。
- 验收条件：同一 `idempotency_key` 重复调用 `approve` 与 `shipment` 各 3 次，`audit_trail` 长度不增加、状态不变、响应体逐字节一致；一次人工把 `deadline` 从 `10:27:37` 改为 `12:00:00` 后，`audit_trail` 中存在该条记录且界面可展开查看修改人与时间。

### C4｜修正 Hero 时间轴，使双物流分支同时可演

- 证据：`fixtures/demo-cases.json:16`（`evaluation_time 11:00`）、`fixtures/demo-cases.json:55`（二次进线 `10:45`）、`fixtures/ground-truth.json:14`（`deadline 10:27:37`）、`docs/04-responsibility-loop.md:48-53`、`docs/07-demo-and-delivery.md:23-27`。
- 影响：分析时刻承诺已逾期，回执 `next_update_by` 落在过去；`SHIPMENT_NOT_PICKED_UP` 的“尚未到期”分支不可达；Demo 2:25–3:15 声称“已揽收不产生催办 / 未揽收进入 AT_RISK”的对比失去前提。
- 最小修改：`DEMO_001` 的 `evaluation_time` 改为 `2026-05-07T09:40:00+08:00`，`DEMO_AUG_MSG_001.timestamp` 改为 `2026-05-07T09:35:00+08:00`；`next_check_at` 定为 `2026-05-07T10:00:00+08:00`；演示两个事件时间固定为 `SHIPMENT_PICKED_UP = 2026-05-07T10:00:00+08:00`、`SHIPMENT_NOT_PICKED_UP = 2026-05-07T10:40:00+08:00`；`fixtures/ground-truth.json:20` 的 `service_cause` 由“承诺已到期”改为“承诺即将到期”。同时明确：倒计时与到期判断只允许读取 `CaseInput.evaluation_time` 与事件 `event_time`，禁止调用系统时间。
- 验收条件：`analyze` 后 `open_obligation.status = ON_TRACK`、`case_status = IN_FULFILLMENT`、`service_progress_receipt.next_update_by = 2026-05-07T10:27:37+08:00` 且晚于 `evaluation_time`；推送 `SHIPMENT_PICKED_UP` 后 `pending_candidates.follow_up_task = null` 且 `milestone = IN_TRANSIT`；推送 `SHIPMENT_NOT_PICKED_UP(10:40)` 后 `case_status = AT_RISK`、`open_obligation.status = AT_RISK`、三个候选对象均非空；在任意机器日期下重复运行，上述值不变。

### C5｜冻结六状态迁移表与 `RESOLVED` 唯一入口

- 证据：`docs/00-product-p0.md:60-66` 只有枚举；`docs/04-responsibility-loop.md:62` 强调“工单创建 ≠ 已发出 ≠ 已揽收 ≠ 已送达 ≠ 真正解决”。
- 影响：`case_status` 与 `open_obligation.status`、`service_progress_receipt.status` 三处状态可能互相矛盾；假性结案无法阻止。
- 最小修改：冻结迁移表（触发者 → 边）：`consumer_input_required=true` → `WAITING_FOR_CONSUMER`；`evidence_status=VALID` 且无人工确认 → `READY_FOR_BRAND`；`decision=HUMAN_REVIEW` 或 `requires_human_approval=true` → `ACTION_REVIEW`；`approve` 成功且 `creates_obligation=true` → `IN_FULFILLMENT`；`event_time > deadline` 且 `milestone=AWAITING_CARRIER_PICKUP` → `AT_RISK`；`milestone=DELIVERED` 且 `resolution_condition=REPLACEMENT_DELIVERED` 满足 → `RESOLVED`。并规定三处 status 的一致性约束：`case_status=AT_RISK ⇔ open_obligation.status=AT_RISK ⇔ receipt.status=AT_RISK`。
- 验收条件：状态机测试覆盖上述 6 条边各 1 例；`RESOLVED` 在 `milestone ≠ DELIVERED` 时无法写入（返回 `STATE_CONFLICT`）；断言三处 status 一致性的测试存在且通过。

### C6｜关闭 `evaluate` 的无规则命中缺口，并把不良反应纳入 H1

- 证据：`schemas/decision-result.schema.json:7,11,12`；`schemas/prepared-action.schema.json:11`；`docs/00-product-p0.md:35`；`PRODUCT_BLUEPRINT.md:85`。
- 影响：`CHECK_REPLACEMENT_PROGRESS`、`CREATE_FOLLOW_UP_TASK`、`CLOSE_CASE` 三种动作，以及 `VALID` + 范围不等的组合，无法构造合法 `DecisionResult`；不良反应案例可能被 `E2` 放行，突破“高风险保留人工确认”的硬边界。
- 最小修改：P0 期 `POST /api/actions/evaluate` 只接受 `action_type = ASK_EVIDENCE`，其余三种返回 `400 / SCHEMA_INVALID`（`CLOSE_CASE` 的假性结案由 C5 的 `RESOLVED` 约束拦住）；`H1` 条件扩展为 `evidence_status = NEED_HUMAN_REVIEW OR current_scope.issue_type = ADVERSE_REACTION`，并保持 `H1` 优先级 200 高于 `E2`；`DecisionResult` 增补 `rule_id` 取值 `E0_NO_RULE_MATCHED`（`rule_priority: 0`、`decision: HUMAN_REVIEW`）作为兜底，禁止任何路径返回空 `rule_id`。
- 验收条件：4 种 `action_type` 各 1 个用例，1 通过 3 被拒；构造 `issue_type=ADVERSE_REACTION` + `evidence_status=MISMATCHED` 的用例，输出 `HUMAN_REVIEW / H1 / 200`，且 `resolution_path.executor = HUMAN_REVIEW_QUEUE`、`creates_obligation = false`；构造 `VALID` + 范围不等用例，输出 `E0_NO_RULE_MATCHED`，不返回 500。

### C7｜清理 `CaseInput` 中的质量结论预填

- 证据：`schemas/case-input.schema.json:118-120`；`fixtures/demo-cases.json:129-130`（DEMO_001 `integrity_concern=true` / `hygiene_risk=MEDIUM`）与 `275`（DEMO_003 `UNKNOWN`）；`docs/01-core-contracts.md:29`；`docs/02-ai-extraction.md:18`。
- 影响：这是本包中最容易被评委指为“输入里已经藏了答案”的一处；同时把完整性与卫生风险判断压给一线客服或数据准备者，违反“不把客服假设为质量专家”的边界。
- 最小修改：从 `CaseInput.current_issue` 删除 `integrity_concern` 与 `hygiene_risk`，仅保留 `fulfillment_item_id`、`sku_id`、`issue_type`、`affected_component`（后者是客服声明的问题范围，非质量结论）；完整性与卫生风险只从 `image_observations.integrity_concern` / `hygiene_risk_signal` 派生，并在界面标注“来自图片观察”。
- 验收条件：`case-input.schema.json` 中不再出现这两个字段，三个 fixture 通过 Schema 校验；`AccountabilityState.experience_risk` 的计算输入中不包含 `CaseInput` 的任何风险字段（代码审查 + 1 个反例测试：删除图片后 `experience_risk` 发生变化）。

### C8｜产出 5 张演示图片与来源可追溯的图片-消息绑定

- 证据：`fixtures/README.md:6-12`；仓库内 0 张图片；`fixtures/demo-cases.json:111,120` 引用不存在的消息 ID。
- 影响：门 2“至少一个案例从原始聊天和实际图片文件生成 `ExtractedJourney`”无法验收；来源展开功能无数据。
- 最小修改：产出 5 个文件（`s00001-product-overview.jpg`、`s00001-pump-detail.jpg`、`s00001-package-context.jpg`、`s00001-gift-evidence.jpg`、`s00001-blurred-pump.jpg`），不含真实消费者身份信息；把 DEMO_001 三张图片的 `source_message_id` 统一改为 `80525870445254.PNM`（与 `submitted_at 10:21:38` 一致），或在 `conversation` 中补入对应的 `DEMO_AUGMENTATION` 图片消息并保持时间戳一致。
- 验收条件：5 个文件存在且可被推理代码打开；`ExtractedJourney.source_trace` 中每条 `source_type=IMAGE` 的 `source_id` 都能在 `evidence_images[].evidence_id` 中找到，每条 `evidence_images[].source_message_id` 都能在 `conversation[].message_id` 中找到（一个引用完整性测试，0 条悬挂引用）。

### C9｜冻结模型版本与结构化输出的可靠性方案

- 证据：`docs/02-ai-extraction.md:5` 与 `schemas/extracted-journey.schema.json:134` 冲突；`extracted-journey.schema.json` 为 `additionalProperties: false` 且含 12 个枚举、2 个 `date-time`、多处 `minItems/minLength`。
- 影响：2B 级 VL 模型一次性产出该 Schema 的合法实例成功率存在实质风险；`docs/02:60-61` 规定失败即 `HUMAN_REVIEW`，主 Demo 的 `INTERVENE` 会被概率性击穿。
- 最小修改：`model_id` 保留 `const` 但改为在冻结文件中登记最终唯一版本，并把 `model_metadata.model_revision` 从可选改为必填；抽取拆为两次受约束调用（图片观察 / 聊天与承诺），启用 JSON 受约束解码；`date-time`、`confidence`、`source_ids` 由代码后处理填充而非模型自由生成；保留一次重试，重试仍失败按 C2 返回 `MODEL_OUTPUT_INVALID` 并使用带标识的缓存结果。
- 验收条件：对 20 个标注案例连续运行，Schema 一次通过率 ≥ 80%、含一次重试后 ≥ 95%；主 Hero 案例在演示硬件上端到端（3 张图片 + 聊天）p95 ≤ 25 秒，并留存 `run_id` 与时延日志；界面在使用缓存时固定显示“缓存抽取结果”。

---

## D. P1 / P2

| 项 | 级别 | 延后不破坏 Hero 的理由 |
|---|---|---|
| `APPROVAL_REQUIRED` / `ERRONEOUS_OR_UNAUTHORIZED` 的权限校验数据源（B12） | P1 | Hero 的唯一有效承诺是 `STANDARD_APPROVED`（有 `BH919209358357` 工单支撑，`fixtures/ground-truth.json:12`）。P0 期把这两类统一按 `activation_recommendation = BLOCKED` 处理并在界面写明“需人工批准，系统不生成倒计时”，即可守住硬边界；权限表在无客服角色数据时无法真实校验。 |
| `open_obligation.executor_name`（B26 相关） | P1 | `executor` 枚举已能表达 `WAREHOUSE`，回执不展示内部执行方姓名（`docs/04:35`）。仅内部视图缺少“测试美妆分销中心”这一显示名，不影响状态流转。 |
| `ground-truth.json` 补齐 `case_status` / `prohibited_actions` / `next_check_at` 断言（B17） | P1 | C1+C5 已把这些字段的推导规则确定化，评测断言可在链路跑通后一次补齐；缺失只影响回归覆盖率，不影响 Demo 运行。 |
| 五类工单只读统一展示（`docs/00:33-36` 中线下打款、售后退货） | P1 | 只读列表不参与 Hero 决策；晚一周接入不改变任何状态机。 |
| 轻量管理区（`docs/05-api-and-ui.md` 第 6 节） | P1 | 数据已在 `fixtures/synthetic-pattern-card.json` 中定稿，可直接静态渲染，无需后端接口。 |
| 对照实验三系统完整跑批（`docs/06` 第 4 节） | P1 | 属于门 5 证据链，与门 1–4 的运行能力解耦。 |
| 问卷 100 份 / 深访 5–8 人 / 客服短访 3–5 人 | P1 | `docs/06:24` 已声明真实旅程拿不到不阻塞系统开发。 |
| 多货件并发、事件总线、重试策略（`docs/04` 第 7 节已排除） | P2 | 文档已显式排除，无需讨论。 |
| `cooperation_willingness` 的界面呈现 | P2 | 该字段只允许影响优先级与解决路径（`docs/03:50`），不呈现不影响任何决策结果。 |

---

## E. 一线客服与 KPI 裁决

### E1 可用性裁决

`docs/05-api-and-ui.md` 第 3 节的第一屏结构（已经知道什么 / 现在最不能做什么 / 下一步直接做什么）正确，不需要改。三点必须补齐：

1. **不让客服做质量判断。** 按 C7 移除 `CaseInput` 的 `integrity_concern` / `hygiene_risk`。界面上完整性与卫生风险只以“图片观察显示泵头可见损坏，可能影响正常使用”这类描述出现，并标注来源图片，不出现“质量责任”“批次风险”字样（`PRODUCT_BLUEPRINT.md:84` 已禁止为破损换货虚构批次风险）。
2. **不让客服判断承诺权限。** `APPROVAL_REQUIRED` 与 `ERRONEOUS_OR_UNAUTHORIZED` 一律显示为一句话加一个按钮：“该承诺需主管确认后才开始计时”＋`提交主管确认`。客服不需要理解五类承诺分类的差别，分类只在折叠区可查。
3. **升级路径必须是一个按钮，不是一段说明。** `AT_RISK` 时右栏顶部固定出现 `提交仓库催办` 与 `升级主管` 两个按钮（`pending_candidates` 非空时可用），不要求客服自行判断该找谁。

P0 保留：第一屏三问、`INTERVENE` 的一句中文原因、两个直接动作、人工确认入口、`HUMAN_REVIEW` 的转人工按钮、一次性“赛事 Mock 数据＋团队压力测试扩充”标识（`SIMULATION_DISCLOSURE.md:32`）。

建议删除：任何培训看板、规则说明长文、置信度小数、JSON 视图、情绪曲线、内部责任人姓名（`docs/05:90` 已要求默认不展示，落实为“不实现”而非“默认折叠”）。

### E2 KPI 裁决

`CLAUDE-PREFLIGHT-REVIEW.md:50` 的权重体系不出现在任何产品文档中，属于外部输入，需要由产品负责人决定是否写入冻结文件。裁决如下（权重不可作为 Covenia 的效果承诺）：

| KPI（权重） | 分类 | 裁决 |
|---|---|---|
| 响应速度 20% | 部分为过程指标 | 可直接记录：从案例打开到首个可执行动作出现的耗时、回复草稿生成耗时、草稿采纳率。不可承诺整体首响时长（受排班与并发影响）。 |
| 客户满意度 20% | 结果指标 | 只能通过对照实验观察（`docs/06` 第 4 节）。P0 只登记代理过程指标：按时更新率、消费者重复追问次数。 |
| 询单转化率 30% | 不可承诺 | Covenia 是售后责任副驾（`README.md:3`），不参与售前询单。必须在冻结文件中明确不承诺该指标，否则构成越界宣称。 |
| 品退率 10% | 不可承诺 | 受商品、价格、物流影响。可观察的相关过程指标只有“换货履约按时完成率”。 |
| 商品差评 10% | 不可承诺 | 受配方与物流影响。 |
| 平台求助/投诉 10% | 结果指标 | 只能通过对照实验观察；可记录的过程指标是“承诺逾期未主动通知的案例数”。 |

P0 必须实现且可直接从日志计数的过程指标（六项，全部来自已有契约字段）：

1. 重复索证拦截次数（`DecisionResult.rule_id = E1` 计数）；
2. 合理索证放行次数（`rule_id = E2` 计数）；
3. 人工复核转出次数（`rule_id = H1` 计数）；
4. 承诺激活数与逾期数（`active_commitments.status`）；
5. 按时更新率（`receipt.next_update_by` 与实际更新时间比较）；
6. 主动催办与升级候选生成数（`pending_candidates`）。

以上六项在 `docs/06` 的核心指标中已有对应，不新增指标体系。所有结果指标在对外材料中标注“需对照实验验证 / 进行中”，不填预测数字（`docs/06:67`）。

---

## F. API 与最小架构裁决

### F1 端点（四个，不增不减）

| 端点 | 请求 | 响应 `data` | 幂等 |
|---|---|---|---|
| `POST /api/cases/analyze` | `CaseInput` | `{ extracted_journey, accountability_state }` | 按 `case_id + evaluation_time + prompt_version` 可缓存，重复请求返回同一 `run_id` |
| `POST /api/actions/evaluate` | `{ accountability_state, prepared_action }` | `DecisionResult` | 纯函数，无副作用 |
| `POST /api/resolutions/approve` | `ResolutionApproval`（C3 新增 Schema） | `AccountabilityState`（含 `service_progress_receipt`、`audit_trail`） | `idempotency_key` 必填，重放返回首次结果 |
| `POST /api/events/shipment` | `ShipmentEvent`（C3 新增 Schema） | `AccountabilityState`（含 `pending_candidates`） | `event_id` + `idempotency_key`；`event_time` 早于已处理的最大 `event_time` 时返回 `DUPLICATE_EVENT` 且不改状态 |

`POST /api/events/assignment`（`CLAUDE-PREFLIGHT-REVIEW.md:62`）不进入 P0，路径以 `docs/05-api-and-ui.md:28` 的 `/api/events/shipment` 为准。

案例列表与详情、聊天记录、外发进度均不新增接口：列表与聊天记录由前端读取 `fixtures/demo-cases.json`（静态资产，标注模拟数据），详情与外发进度由 `analyze` 与 `approve` 的响应体承载。回执不新增接口（`docs/05:33`）。

### F2 “发送消费者回复”的裁决

P0 定为：**后端生成草稿并落库到 `service_progress_receipt`，前端在模拟千牛聊天区渲染，并固定标注“模拟发送，未接入千牛”。** 不实现真实外发（无千牛账号，`docs/00:70`）。`approve` 响应中的回执即为发送内容的唯一来源，前端不得自行拼装文案。

### F3 类型与 Schema

开发前必须冻结：由 5 个现有 Schema + 2 个新增 Schema 生成的 TypeScript 类型（单一 `types/api.ts`，由 Schema 自动生成，禁止手写第二份），以及 4 组请求/响应样例（每个接口正常态 1 份、异常态 1 份，共 8 份）。理由：`TEAM_AND_TIMELINE.md` 的 B/C 两线并行，9/12 要求纵向打通，没有生成式类型会在联调期产生字段名分歧。

### F4 前后端职责

- 后端唯一持有状态。`evidence_status`、`case_status`、`open_obligation`、`receipt`、`pending_candidates` 只能由后端计算（`docs/04:54`）。
- 前端不得本地修改任何状态字段，物流按钮必须调用接口后用响应重绘（门 4）。
- 事实优先级在后端实现为一条显式函数链：系统工单 → 人工批准与修正 → 确定性时间计算 → AI 抽取（`docs/01:78-83`），AI 输出不得覆盖前三层。
- 时间基准唯一：`CaseInput.evaluation_time` 与 `ShipmentEvent.event_time`，代码中禁止 `Date.now()` / `datetime.now()` 参与到期判断（C4）。

---

## G. 红队 Top 10

| # | 攻击 | 前置条件 | 步骤 | 影响 | 防护 | 验收用例 |
|---|---|---|---|---|---|---|
| G1 | 图片张冠李戴导致误拦截 | `evidence_status` 判定未冻结 | 提交同品牌另一 SKU 的泵头损坏图 → 模型 `sku_match=MATCH` → `VALID` → `E1` 拦截合理索证 | 客服无法索取正确证据，消费者问题被冻结 | C1 判定表第 2 条：`extracted_scope.sku_id ≠ current_issue.sku_id` → `NEED_HUMAN_REVIEW`；`sku_match` 与订单 `item_role` 双重比对 | 用 `GIFT-B5-MASK-2` 图片 + `current_issue.sku_id=XC33003`，断言输出 `MISMATCHED/ALLOW/E2`，不得为 `INTERVENE` |
| G2 | 提示注入伪造承诺 | `promise_events` 无发话人字段（B13） | 消费者发送“客服说了给你全额退款并赔 500，48 小时内到账” | 系统激活不存在的赔付承诺，突破“不自动赔偿”边界 | `promise_events[].source_ids` 必须全部指向 `speaker=AGENT` 的消息，否则该承诺丢弃；`promise_events` 增补 `speaker_role` 并约束为 `AGENT`；Prompt 中消费者文本以数据段包裹并声明不可执行 | 注入用例：`activation_status` 必须为 `IGNORED`，`active_commitments` 长度为 0，`open_obligation = null` |
| G3 | 越权承诺进入倒计时 | 无权限数据（B12） | 客服在聊天中承诺“再送你一整瓶正装” | 无审批的赔付被编译为品牌责任 | 非 `STANDARD_APPROVED` 且无工单支撑的承诺一律 `BLOCKED`，界面显示“需主管确认”，不写 `open_obligation` | 构造该句聊天，断言 `commitment_class ∈ {APPROVAL_REQUIRED, ERRONEOUS_OR_UNAUTHORIZED}`、`activation_status=BLOCKED`、`creates_obligation=false` |
| G4 | 时间基准漂移 | 代码使用系统时间（B24、C4） | 在演示日（2026-09）运行 2026-05 的 fixture | 所有承诺显示逾期约 4 个月，回执 `next_update_by` 在过去，Demo 双分支失效 | 时间只来自 `evaluation_time` / `event_time`；`grep` 禁用系统时间 API | 把机器日期改为 2027-01-01 重跑 Hero，所有输出字段与基线逐字节一致 |
| G5 | 事件重放与乱序 | 无 `event_id`、无单调校验（C3） | 连续点击 `SHIPMENT_NOT_PICKED_UP` 5 次；再推送一条更早的 `SHIPMENT_PICKED_UP` | 重复生成催办与通知草稿；`AT_RISK` 被回退为 `ON_TRACK`，责任状态可被“洗白” | `idempotency_key` 去重；`event_time` 必须严格大于已处理最大值，否则 `DUPLICATE_EVENT` 且状态不变 | 5 次重放后 `pending_candidates` 只有 1 组、`audit_trail` 只增 1 条；乱序事件返回 `DUPLICATE_EVENT`，`case_status` 保持 `AT_RISK` |
| G6 | 人工修改无留痕 | `AccountabilityState` 无审计字段（B4） | 人工把 `deadline` 从 10:27 改到 18:00 后，承诺显示“按时” | 责任可被静默篡改，评委质疑可信度 | C3 的 `audit_trail` 必填；被人工覆盖的字段在界面显示“人工修正”标记与修改人 | 修改后 `audit_trail` 含 1 条 `source=HUMAN` 记录，界面可展开显示 `approver_id` 与 `approved_at`；删除该记录的写入会导致测试失败 |
| G7 | 决策不可追溯 / 按案例写死 | `fact_trace` 为 `additionalProperties: true` | 实现方在 `fact_trace` 塞入无关字段，或按 `case_id` 分支返回结果 | 门 3 与抗演员验证失败，评委现场改输入即暴露 | 规则模块禁止访问 `case_id`（代码审查 + `grep`）；`fact_trace` 收紧为固定 4 字段并要求 `evidence_status` 与 `AccountabilityState.evidence_status` 一致 | 交换三个 fixture 的 `case_id` 后重跑，三条决策结果不变；`grep -R "DEMO_00" src/rules src/state` 返回 0 行 |
| G8 | 敏感信息进入模型或回执 | 线下打款工单含账号类字段；不良反应工单含健康信息 | 把打款/不良反应工单一并塞进 Prompt 或回执 | 违反 `MODEL_GOVERNANCE.md:38`，构成隐私事故 | Prompt 构造层白名单：只允许 `conversation`、`order.items`、`REPLACEMENT` 工单的状态与时间、图片；账号、地址、就医信息在进入 Prompt 前剔除；回执字段固定 8 项（`accountability-state.schema.json:114`） | 构造含账号与就医描述的输入，断言 Prompt 快照中不含这些字符串，回执不含内部字段 |
| G9 | 缓存冒充实时推理 | `model_metadata.cached_result` 为可选字段 | 模型不可用时展示缓存结果但不标识 | 违反 `MODEL_GOVERNANCE.md:52` 与 `docs/07:71`，属于诚信问题 | `cached_result` 改为必填布尔；为 `true` 时界面必须渲染“缓存抽取结果”标识，且不得声明为现场推理 | 断网运行 Hero，界面出现缓存标识；把该标识注释掉后 UI 测试失败 |
| G10 | 假性结案 | `RESOLVED` 无入口约束（C5） | 直接把 `case_status` 或 `receipt.status` 置为 `COMPLETED` | 消费者收到“已解决”但补发未送达，违反 `docs/04:62` | `RESOLVED` 唯一入口为 `milestone=DELIVERED`；`receipt.status` 由 `open_obligation.status` 派生，不可独立赋值；`evaluate` 拒绝 `CLOSE_CASE` | 在 `milestone=AWAITING_CARRIER_PICKUP` 下尝试置 `RESOLVED`，返回 `409 / STATE_CONFLICT`；三处 status 一致性断言通过 |

---

## H. 单一 Hero Demo

以 `docs/07-demo-and-delivery.md` 的七段结构为基线，只做时间与证明点的收紧（不改叙事顺序、不切换场景）。

| 时间 | 画面 | 操作 | 证明点 | 失败兜底 |
|---|---|---|---|---|
| 0:00–0:20 | 千牛三栏，右栏折叠 | 念一句价值判断：消费者已经发过图、品牌已经答应 48 小时发货，两天后消费者还要自己来问进度 | 前 20 秒说清消费者价值，不讲架构 | 纯口播，无需系统 |
| 0:20–1:00 | 导入结果 + 右栏第一屏 | 触发 `analyze`，屏幕显示 `run_id`、模型版本、三张图片文件名与推理耗时 | 门 1 + 门 2：长数字 ID 无精度丢失（订单 `6920185815517983396`、工单 `BH919209358357`、物流 `YT7667875838478` 逐字符可见）；`ExtractedJourney` 由真实图文推理产出 | 推理超 25 秒则改用带“缓存抽取结果”标识的结果，后续链路照常真实运行（`docs/07:71`） |
| 1:00–1:40 | 客服输入框 + 拦截卡 | 客服输入“麻烦再上传一下破损照片”并点发送 | 门 3：`INTERVENE / E1 / 300`，一句中文原因，展开可见触发事实与来源消息 ID | 前端失败时用接口响应原文展示同一 `DecisionResult`（`docs/07:73`） |
| 1:40–2:20 | 解决路径 + 人工确认 | 点 `查询补发进度` → `生成解决回复` → 人工确认 | `approve` 后第一屏转为回执与倒计时，`next_update_by = 2026-05-07T10:27:37+08:00` 且晚于评估时间；聊天区出现标注“模拟发送”的回执卡片 | 静态责任时间线，但不伪造接口执行（`docs/07:74`） |
| 2:20–3:10 | 物流事件两个按钮 | **请评委任选其一**：`已揽收(10:00)` 或 `未揽收(10:40)` | 门 4：已揽收 → `milestone=IN_TRANSIT`、无催办；未揽收且已过期 → `case_status=AT_RISK` + 仓库催办 + 主管升级候选 + 主动通知草稿。两条路径都由同一接口返回 | 若网络异常，本地服务重放同一请求；不使用预录动画 |
| 3:10–3:35 | 风险卡片 | 展示 `synthetic-pattern-card.json`：左侧“赛事数据统计”（80 条工单 / 28 条非完结 / 4 条补发进行中），右侧“人工标注压力测试假设”（4 例，`HYPOTHESIS_TO_INVESTIGATE`） | 统计与假设两类来源分开标注，不宣称发现真实流程缺陷 | 静态卡片，无依赖 |
| 3:35–4:00 | 证据卡 + 收尾句 | 展示问卷/访谈/30 案例/对照结果，未完成项标“进行中” | 门 5：来源可核验，不填预测数字 | 静态卡片 |

答辩期 Challenge Mode（同一链路，不切页面，右栏底部折叠区提供四个可改输入，满足 `docs/06:60`）：换赠品图 → `ALLOW/E2`；换模糊图 → `HUMAN_REVIEW/H1`；把承诺文本改为“尽快” → `AMBIGUOUS`，不生成截止时间；把物流改为已揽收 → 无催办。

现场必须回避的两句话：不说“已接入千牛/欧莱雅系统”，不说“赛事数据显示重复索证发生率”。

---

## I. 建议删除或降级

| 功能 | 处理方式 | 成本 | Demo 收益 | 理由 |
|---|---|---|---|---|
| `evaluate` 支持 `CHECK_REPLACEMENT_PROGRESS` / `CREATE_FOLLOW_UP_TASK` / `CLOSE_CASE` | P0 拒绝，只保留 `ASK_EVIDENCE` | 中 | 零 | 三者无对应规则，且会打开 B8 的 Schema 死角；`CLOSE_CASE` 的风险由 C5 的 `RESOLVED` 约束覆盖（`docs/01:74` 已声明 P0 主要验证 `ASK_EVIDENCE`） |
| 轻量管理区做成可交互统计区 | 降级为一张静态卡片，直接渲染 `fixtures/synthetic-pattern-card.json` | 中 | 25 秒画面，不因交互而增加 | `docs/05:75` 已声明不开发独立 BI；数据已定稿，无需接口 |
| 线下打款、售后退货工单的展示 | 降级 P1，仅在案例详情列出工单号与状态，不做筛选、排序、详情页 | 低 | 极低 | `docs/00:34,36` 定为“只读统一展示”；且这两类含账号类字段，展示面越小越安全（G8） |
| `APPROVAL_REQUIRED` / `ERRONEOUS_OR_UNAUTHORIZED` 的完整权限校验 | 降级 P1，P0 统一按 `BLOCKED` + “需主管确认”处理 | 高 | 低 | 无权限数据源（B12）。统一 `BLOCKED` 更保守，硬边界不破 |
| `cooperation_willingness`、`experience_risk` 的界面呈现 | 保留字段，删除界面呈现 | 低 | 零 | 接近情绪指数，`docs/02:32`、`docs/03:50` 已限定其不得决定高风险动作；不展示可避免评委质疑 |
| `CaseInput.current_issue.integrity_concern` / `hygiene_risk` | 删除字段（C7） | 低 | 正收益 | 消除“输入里藏答案”的攻击面，同时移除对客服的质量判断要求 |
| 培训看板、规则说明长文、JSON 视图、置信度小数 | 不实现 | — | 零 | `docs/05:90` 已要求默认不展示；确认为“不建设”，避免开发期反复 |
| 多货件、事件总线、重试与并发 | 不实现 | — | 零 | `docs/04:68-70` 已排除 |

---

## J. PRODUCT-FREEZE 输入摘要（候选内容，非冻结文件）

以下仅为候选条目，供产品负责人取舍后写入 `PRODUCT-FREEZE.md`。Claude 不生成、不修改该文件。

**范围（建议原样保留）**：一个 Hero（`S00001`）、三条规则（`E1/E2/H1`）、四个接口、六个业务状态、一次物流事件双分支、一个静态风险卡片。不新增模块、页面、售后场景。

**必须写入冻结文件的 9 项定义（对应 C1–C9）**：

1. `evidence_status` 五分支判定表及其唯一输入集合。
2. `{ data, error, request_id }` 外壳、6 个业务错误码与 HTTP 映射、20 秒模型超时。
3. `resolution-approval.schema.json`、`shipment-event.schema.json`，以及 `AccountabilityState` 增补 `audit_trail[]` 与 `pending_candidates`。
4. Hero 时间轴修正值（`evaluation_time = 2026-05-07T09:40:00+08:00`、二次进线 `09:35`、`next_check_at = 10:00`、两个事件时间 `10:00` / `10:40`）与“时间只来自 `evaluation_time` / `event_time`”的硬约束。
5. 六状态迁移表、`RESOLVED` 唯一入口、三处 status 一致性约束。
6. `evaluate` 只接受 `ASK_EVIDENCE`；`H1` 覆盖 `ADVERSE_REACTION`；新增 `E0_NO_RULE_MATCHED` 兜底。
7. 从 `CaseInput.current_issue` 删除 `integrity_concern` 与 `hygiene_risk`。
8. 5 张图片素材清单与图片-消息引用完整性要求。
9. 唯一模型版本登记（含 `model_revision` 必填）、两次受约束调用、Schema 通过率与时延门槛。

**验收门（在 `docs/07` 五道门基础上补三条可执行断言）**：

- 交换三个 fixture 的 `case_id` 后重跑，三条决策结果不变；规则与状态模块内 `grep -R "DEMO_00"` 返回 0 行。
- 机器日期任意变动，Hero 输出逐字节一致。
- `approve` 与 `shipment` 重放 3 次，状态与 `audit_trail` 不变。

**表达边界（沿用现有文档，逐字采用）**：`README.md:73`、`PRODUCT_BLUEPRINT.md:100`、`SIMULATION_DISCLOSURE.md` 全文。对外统一使用“服务责任、待履行承诺、服务进度回执”。

**KPI 承诺边界**：只承诺 E2 节列出的六项过程指标；明确不承诺询单转化率、品退率、商品差评；满意度与投诉类指标标注“需对照实验验证”。

**门禁提醒**：当前仓库不存在 `CLAUDE-REDTEAM.md`、`PRODUCT-FREEZE.md`、`IMPLEMENTATION-STATUS.md`。按 `AGENT-HANDOFF-PROTOCOL.md` 第 30–41 行，G1 未满足前不得编写最终冻结版，G2 未标记 `审批状态：APPROVED` 前 Codex 不得开始产品功能开发。C1–C9 未写入冻结文件前，建议禁止启动的开发范围为：规则引擎、状态构建器、`approve` 与 `shipment` 接口、回执渲染、倒计时逻辑。可以先行启动且不受阻塞的工作为：Excel 导入与关联（B 线）、千牛三栏与右栏静态骨架（C 线）、5 张图片素材与 30 个案例标注（A 线）、`analyze` 的模型调用与 Schema 校验管线（B 线，模型版本待 C9 定稿前使用默认基线）。
