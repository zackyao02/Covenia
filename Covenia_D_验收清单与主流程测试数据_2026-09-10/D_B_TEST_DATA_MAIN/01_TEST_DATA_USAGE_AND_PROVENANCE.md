# 01｜主流程测试数据使用说明与来源声明

用途：A/B/C 一交付，D 就能直接照这一包跑主流程，并对答案。

---

## 1. 数据从哪来（来源声明）

| 数据 | 来源标签 | 说明 |
|---|---|---|
| 赛事 Excel 七张业务表 | `OFFICIAL_COMPETITION_MOCK_DATA` | 官方提供的 AI 生成虚构 Mock 数据，不是真实业务数据 |
| `S00001` 的原始聊天、订单、换货工单 | 同上（赛事原始记录） | 从 `data/tianchi-track1-mock-data.xlsx` 原样提取 |
| 第二次进线消息 | 团队压力测试扩充 | 团队构建，必须单独标注 |
| 五张测试图片 | 团队自制 / 合成 | `fixtures/README.md` 声明工作簿不含实际图片文件 |
| 物流动作与时间点 | 团队压力测试扩充 | 模拟事件，不代表真实物流 |
| `DEMO_POLICY_PACKAGE_DAMAGE_V1` | 演示政策 | 模拟规则，不代表欧莱雅真实售后政策 |
| 三份预期结果 | 评测标准答案 | **只用于运行完成后的比对，禁止作为任何输入** |

正确表述：

> 基于赛事 `S00001` 会话、订单和换货工单构建的压力测试案例。

不允许的说法：

- 「欧莱雅真实消费者复联案例」
- 「赛事数据已经证明重复索证发生」
- 「已接入欧莱雅生产系统 / 千牛 / OMS / WMS / TMS」

---

## 2. 目录与文件对应关系

| 文件 | 内容 | 谁用 |
|---|---|---|
| `data/00_赛事原始事实基线.json` | `S00001` 全部原始事实 + 导入计数基线 | D 验门 1；B 核对导入 |
| `data/01_analyze-requests.json` | `POST /api/cases/analyze` 的请求 | B 跑分析 |
| `data/02_evaluate-action-requests.json` | `POST /api/actions/evaluate` 的请求 | B 跑防线 |
| `data/03_approve-resolution-requests.json` | `POST /api/resolutions/approve` 的请求 | B 跑人工确认 |
| `data/04_shipment-event-requests.json` | `POST /api/events/shipment` 的请求 | B 跑物流事件 |
| `data/05_challenge-cases.json` | 挑战案例的构造方式 | 答辩与 Challenge Mode |
| `data/06_expected-results.json` | 预期结果（评测用） | **只给 D 比对用** |
| `data/07_test-run-sequence.json` | 跑测顺序与分支结构 | D 执行 |

每个请求文件都是「编号 → 请求体」的形式。**发请求时只发 `request` 里的那个对象**，编号只是给 D 记账用的。

---

## 3. 主流程怎么跑（先看这一节）

### 3.1 时间线（以已批准的产品冻结为准）

| 事件 | 时间 | 来源 |
|---|---|---|
| 原始咨询与换货承诺 | 2026-05-05 10:18–10:27 | 赛事 Mock |
| 承诺截止（承诺 + 48h） | 2026-05-07T10:27:37+08:00 | 赛事 Mock 推算 |
| 第二次进线 | 2026-05-07 09:32 | `PRODUCT-FREEZE.md` P0-4（团队扩充） |
| 评估时刻 `evaluation_time` | 2026-05-07T09:40:00+08:00 | `PRODUCT-FREEZE.md` P0-4 |
| 人工批准 `approved_at` | 2026-05-07T09:42:00+08:00 | 服务端生成 |
| 下一检查时间 `next_check_at` | 2026-05-07T10:30:00+08:00 | `PRODUCT-FREEZE.md` P0-4（见待确认 T-03） |
| 已揽收事件 | 2026-05-07T10:10:00+08:00 | `PRODUCT-FREEZE.md` P0-4 |
| 未揽收事件 | 2026-05-07T11:35:00+08:00 | `PRODUCT-FREEZE.md` P0-4 |
| 送达事件 | 2026-05-08T14:00:00+08:00 | **D 拟定值，工程文件未规定，见待确认 T-08** |

注意：`fixtures/demo-cases.json` 里 `DEMO_001` 的 `evaluation_time` 仍是 `2026-05-07T11:00:00+08:00`，与冻结版不一致。本包按冻结版编写，差异记在 `A_验收清单/09_阻塞与待确认清单.md` T-02。

### 3.2 六个阶段

```text
阶段 0  门 1：Excel 导入与计数核对
   ↓
阶段 1  分析：analyze × 3 个案例 + 2 个变体
   ↓
阶段 2  防线：evaluate × 主拦截 / 伪造字段 / 放行 / 人工复核 / 无规则命中
   ↓
阶段 3  人工确认：approve × 标准 / 带人工修改 / 幂等重放 / 缺审批人
   ↓
阶段 4  物流事件：两条独立分支（各自从阶段 3 之后开始）
   ├─ 分支 A（已揽收）：PICKED_UP → DELIVERED → RESOLVED
   └─ 分支 B（未揽收）：NOT_PICKED_UP → AT_RISK + 催办 + 升级
   ↓
阶段 5  红线与抗演员：A21 / A25 / A26 / A27 / A33 / A31
```

### 3.3 重要：分支 A 与分支 B 必须分开跑

揽收→送达，与未揽收→催办，是同一个责任对象的两条互斥路径。**跑完一个分支后，必须把案例重置回「人工确认完成」的状态，才能跑另一个分支。** 否则第二次推送会撞上 `INVALID_EVENT_TRANSITION`，看起来像 bug，其实是测试顺序问题。

### 3.4 每次跑测要记的四样东西

1. 请求（从本包复制）
2. 响应（整段保存或截图）
3. 界面（截图，按 `A_验收清单/08_验收记录表_模板.md` 的命名规范）
4. 结论（通过 / 失败 / 阻塞）

---

## 4. 请求纪律（容易踩的坑）

| 坑 | 说明 |
|---|---|
| 不要在 `evaluate` 请求里带状态字段 | `accountability_state`、`evidence_status`、`active_commitments`、`prohibited_actions`、`current_scope` 都是服务端计算字段，带上去会被忽略。本包里有两条专门用来验证这一点的请求（T07、T13） |
| 用 `challenge_mode` 造变体 | 变体必须 `challenge_mode: true` 且同时给 `challenge_overrides`，二者缺一 Schema 不通过 |
| 幂等键不要复用 | `approve` 与 `shipment` 的 `idempotency_key` 在同一 `case_id` 下唯一。本包对「重放」和「同键改体」分别给了不同的键 |
| `approved_at` 不要自己传 | 服务端生成，前端传入不采信 |
| 时间只用 `evaluation_time` 和 `event_time` | 倒计时与到期判断不得读取系统时间，否则换台机器结果就变了 |

---

## 5. 预期结果怎么用（红线）

`data/06_expected-results.json` 是**评测标准答案**。

> `fixtures/ground-truth.json` 只用于运行完成后的评测，不得传入模型、状态构建器或体验防线。

因此：

- 它只在 D 比对时打开；
- 不得复制进任何请求体；
- 不得作为模型的输入或提示词内容；
- 演示时不投屏这个文件。

如果发现 B 的接口输入里混进了 `expected_decision`、`expected_rule_id`、`expected_evidence_status` 这类字段，按失败处理并写入阻塞清单。
