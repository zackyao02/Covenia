# Covenia 实现状态

对应冻结文件：`PRODUCT-FREEZE.md`
对应冻结基线：`4e83f3baeb5f4d6d9ee9b8bfc61c112abc1f55cb` (v0.8)
更新时间：2026-09-10
维护者：Codex

## C 线 P0 完成情况

| 冻结项 | 状态 | 实现位置 | 测试证据 | 是否影响主 Demo |
|---|---|---|---|---|
| 千牛三栏模拟工作台与 360–420px 右侧插件 | 已完成 | `frontend/src/App.tsx`, `frontend/src/styles.css` | 生产构建通过 | 是 |
| 第一屏三问：已知、不能做、下一步 | 已完成 | `frontend/src/App.tsx` | 三种案例均可切换 | 是 |
| `INTERVENE` / `ALLOW` / `HUMAN_REVIEW` | 已完成（修复后） | `frontend/src/mockApi.ts` | Vitest 覆盖 P0/H1/E1/E2/E0、A20/A21/A22/A34 | 是 |
| 体验断层诊断、解决路径、人工确认 | 已完成 | `frontend/src/App.tsx` | 人工批准后才生成运行中义务 | 是 |
| 服务进度回执、倒计时、催办与主动通知 | 已完成（修复后） | `frontend/src/App.tsx` | 服务端时钟、催办/升级候选及回执一致性测试通过 | 是 |
| 物流时序：未揽收、已揽收、已送达 | 已完成 | `frontend/src/mockApi.ts` | 未揽收直接送达被拒绝；揽收后送达进入 `RESOLVED` | 是 |
| v0.8 四接口类型、统一响应外壳和 JSON 示例 | 已完成（修复后） | `frontend/src/api/`、`schemas/` | H1=350、`runtime_metrics`、卫生风险字段及示例通过 Schema 检查 | 是 |
| Challenge Mode、缓存标识、加载态与可重试错误 | 已完成 | `frontend/src/App.tsx` | 缓存/模型不可用测试通过 | 是 |
| 第一屏责任摘要、主管跟踪区与成本条 | 已完成（修复后） | `frontend/src/App.tsx`、`frontend/src/styles.css` | 状态、承诺、候选和服务端成本字段均直接渲染 | 是 |

## 未完成

| 范围 | 未完成内容 | 原因 | 下一步 |
|---|---|---|---|
| B/C 联调 | 浏览器端 HTTP 联调录屏 | B 线四端点已实现，本次尚未启动双服务完成浏览器录屏 | 设置 `VITE_API_MODE=http` 后启动 `backend/` 与 `frontend/`，执行主链、挑战链和物流链 |
| 真实证据图 | `public/evidence/` 内的团队压力测试图片二进制文件 | 当前未在 C 工作区提供 | 图片就位后按 README 的固定文件名放入；当前 UI 有明确占位回退 |
| 独立验收 | `QA-ACCEPTANCE.md` 对全部 P0 标记通过 | 本次为 G3 后的有限修复；尚未重新独立验收 | 修复提交后启动 Claude 只读复验 |

## 测试结果

| 检查 | 命令/步骤 | 结果 | 证据位置 |
|---|---|---|---|
| C 端契约与主流程 | `npm test -- --run` | 1 个测试文件、11 项测试全部通过 | `frontend/src/mockApi.test.ts`（2026-09-10） |
| TypeScript 与生产构建 | `npm run build` | 通过；Vite 生成 `dist/`，JS 230.13 kB（gzip 67.36 kB） | `frontend/package.json`（2026-09-10） |
| JSON 与决策 Schema | Python JSON + Draft 2020-12 校验 | 17 个 JSON 文件可解析；3 个 `DecisionResult` 示例通过 | `schemas/decision-result.schema.json`（2026-09-10） |

## B 线实现状态（2026-09-13）

| 范围 | 状态 | 实现位置 | 验证 |
|---|---|---|---|
| 四个 HTTP 接口 | 已完成 | `backend/main.py` | Pytest 覆盖响应外壳、挑战门控、审批、物流 |
| 规则与责任状态 | 已完成 | `backend/main.py` | P0(400) → H1(350) → E1(300) → E2(100) → E0(0) |
| 挑战/伪造输入防护 | 已完成 | `backend/main.py` | 未开启挑战模式时忽略覆盖与伪造状态字段 |
| 幂等与事件时序 | 已完成 | `backend/main.py` | 重放返回首次响应；同键不同体冲突；先揽收后送达 |
| 本地启动说明 | 已完成 | `backend/README.md` | 前端可设为 HTTP 模式 |

## 技术阻塞与事实证据

- C 线当前无独立技术阻塞。
- B 端服务已具备本地联调条件；仍需启动双服务完成浏览器端 HTTP 联调。

## 已知风险与灾备

| 风险 | 触发条件 | 当前影响 | 灾备 | 是否影响 Demo |
|---|---|---|---|---|
| 模型不可用 | analyze 返回 `MODEL_UNAVAILABLE` | 无新抽取结果 | 显示可重试失败态；有缓存时显示“缓存抽取结果” | 否 |
| 物流事件逆序 | 未揽收直接送达 | 不允许假性结案 | 保持原状态并显示错误 | 否 |
| 图片未放入 | 证据图 URL 加载失败 | 不显示真实测试图 | 自动使用明确的 CSS 占位图 | 否 |
