# D 线验收基线更新说明

更新日期：2026-09-13  
适用实现：`B-line` 提交 `29ae8fc` 及其父提交  
对比资产：`origin/D` 提交 `d1131a4`

## 先更新再独立验收

`origin/D` 的验收清单和测试数据来自旧主分支。它们不能直接用于判定当前实现是否通过：当前冻结契约已经明确 `P0(400) → H1(350) → E1(300) → E2(100) → E0(0)`，而 D 资产仍记录 `H1=200` 和 `E1(300) → H1(200)`。

独立验收仍由 D 线或 Claude 执行；本文件只更新其输入基线，不宣称验收已通过。

## 必须替换的断言

| 旧断言 | 当前冻结断言 | 影响 |
|---|---|---|
| `H1 / 200` | `H1 / 350` | 三案例检查、接口检查、挑战数据与预期结果中的全部 H1 项 |
| `P0(400) → E1(300) → H1(200) → E2(100) → E0(0)` | `P0(400) → H1(350) → E1(300) → E2(100) → E0(0)` | 优先级说明与 A14/A30 断言 |
| A14 只在 `MISMATCHED` 时复核 | `ADVERSE_REACTION + VALID + ASK_EVIDENCE → HUMAN_REVIEW/H1/350`，且 `E1` 在 `suppressed_rule_ids` | 不良反应优先级测试 |
| D 的 H1 预期 `200` | `350` | `01/03/04/05/06` 清单和 `02/05/06` 测试数据 |

历史审查记录 `CLAUDE-REVIEW-1.md` 不改动；以 `PRODUCT-FREEZE.md` 的 H1=350 补充令和当前 `schemas/decision-result.schema.json` 为准。

## 当前实现已具备的复测证据

| 范围 | 证据 | 结果 |
|---|---|---|
| 后端接口 | `python -m pytest backend/tests -q` | 5/5 通过 |
| Schema | `analyze`、`evaluate` 实际响应经 Draft 2020-12 校验 | 通过 |
| 浏览器 HTTP 主链 | E1 拦截 → 查询进度(E0) → 人工确认 → 已揽收 → 已送达 | 通过 |
| 浏览器挑战链 | 赠品范围 E2/ALLOW、模糊图 H1/HUMAN_REVIEW | 通过 |
| 幂等与时序 | 批准重放/冲突、未揽收直接送达、揽收后送达 | 后端测试通过 |

## 独立验收仍需完成的项目

1. D 线按上表更新 H1 断言后，以干净服务状态逐项执行其请求数据。
2. 把运行结果填入 `QA-ACCEPTANCE.md`；没有实际响应、截图或命令输出的项目保持未通过。
3. 需要额外确认的非主链项目：真实 Qwen 服务不可用时的缓存/错误切换、赛事 Excel 导入日志、承诺文本变体与抗硬编码扫描。

## 本地复测启动

```powershell
cd backend
python -m uvicorn backend.main:app --app-dir .. --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
$env:VITE_API_MODE = "http"
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```
