# Covenia D 线交付包｜验收清单 + 主流程测试数据

版本：v0.1（第一版可检查交付）
日期：2026-09-10
模块：D｜联调、验收与演示保障
依据工程版本：Covenia Competition MVP v0.8.0（`PRODUCT-FREEZE.md` 审批状态 APPROVED，批准日期 2026-09-08）

---

## 0. 这一包里有什么

```text
Covenia_D_验收清单与主流程测试数据_2026-09-10/
│
├── 00_README_D.md                          ← 你正在读的文件
│
├── A_验收清单/                              ← 任务一：建立验收清单
│   ├── 01_验收清单_总表.md                   ← 主清单，所有检查项一张表
│   ├── 02_统一验收门槛与红线清单.md           ← 队里定死的 6 条门槛 + 红线
│   ├── 03_五道交付门验收清单.md               ← docs/07 的五道门逐条可勾选
│   ├── 04_三案例决策验收清单.md               ← DEMO_001/002/003 对照 ground-truth
│   ├── 05_接口与幂等验收清单.md               ← 四个接口 + 错误码 + V1–V5
│   ├── 06_Schema字段验收清单.md               ← 五个 schema 该看哪些字段
│   ├── 07_冻结验收项_A1-A33清单.md            ← 已批准验收标准 A1–A33
│   ├── 08_验收记录表_模板.md                  ← 跑测时往这里填
│   └── 09_阻塞与待确认清单.md                 ← 已发现的不一致 + 待确认问题
│
└── B_主流程测试数据/                          ← 任务二：准备主流程测试数据
    ├── 01_测试数据使用说明与来源声明.md        ← 怎么用、什么不能做
    ├── 02_图片素材与凭证清单.md                ← 5 张测试图 + 截图命名
    └── data/
        ├── 00_赛事原始事实基线.json             ← 门 1 的事实基线（含计数核对）
        ├── 01_analyze-requests.json            ← 分析接口的请求
        ├── 02_evaluate-action-requests.json    ← 防线接口的请求
        ├── 03_approve-resolution-requests.json ← 人工确认接口的请求
        ├── 04_shipment-event-requests.json     ← 物流事件接口的请求
        ├── 05_challenge-cases.json             ← 挑战案例构造方式
        ├── 06_expected-results.json            ← 预期结果（只做评测）
        └── 07_test-run-sequence.json           ← 跑测顺序与记录字段
```

---

## 1. 操作流程

1. 按 `B_主流程测试数据/07_test-run-sequence.json` 的顺序。
2. 每跑一步，在 `A_验收清单/08_验收记录表_模板.md` 填一行，截一张图。
3. 跑不通就在「结论」列写「阻塞」，在「阻塞」列写清楚卡在哪、报什么、找谁 —— **不要追责，只记录事实**。
4. 把 `A_验收清单/09_阻塞与待确认清单.md` 更新成当前真实状态。

---

## 2. 事实依据与取值优先级

本包所有数值都来自工程内文件，没有自行发明。若文件之间冲突，按下面顺序取值，并把冲突记入 `A_验收清单/09_阻塞与待确认清单.md`：

1. `PRODUCT-FREEZE.md`（已批准的产品冻结，含 P0-1 至 P0-9 补充令）
2. `schemas/` 与 `docs/05-api-and-ui.md`（接口唯一实现基线）
3. `fixtures/ground-truth.json` 与 `fixtures/demo-cases.json`（评测标准答案与案例输入）
4. `docs/03-firewall-rules.md`、`docs/04-responsibility-loop.md`、`docs/07-demo-and-delivery.md`、`docs/08-idempotency-and-ordering.md`
5. `TEAM_AND_TIMELINE.md` 第四节「统一验收门槛」与 `docs/06-evaluation-and-research.md`
6. `MODEL_GOVERNANCE.md`、`SIMULATION_DISCLOSURE.md`

已发现的冲突不藏着，全部写在 `A_验收清单/09_阻塞与待确认清单.md` 里。

---

## 3. 三条不能越过的红线

1. `fixtures/ground-truth.json` 只用于运行完成后的评测，**不得**传入模型、状态构建器或体验防线。
2. 赛事 Excel 是官方 Mock 数据，团队图片与第二次进线是团队压力测试扩充，两者必须分开标注，不得说成欧莱雅真实业务数据。
3. 固定动画和缓存结果只能作为灾备，使用时必须在响应、界面角标和治理记录三处同时标明。

---

## 4. 当前最大风险

主案例 `DEMO_001` 可运行的前提是**五张团队测试图片存在**（`s00001-product-overview.jpg`、`s00001-pump-detail.jpg`、`s00001-package-context.jpg`、`s00001-gift-evidence.jpg`、`s00001-blurred-pump.jpg`）。工程包里只有文件名，没有图片文件。没有图，多模态推理跑不了，门 2「AI 真实」直接失败。

这件事写在 `B_主流程测试数据/02_图片素材与凭证清单.md`，请第一时间确认负责人。
