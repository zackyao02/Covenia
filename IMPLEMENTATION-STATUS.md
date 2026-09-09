# Covenia 实现状态

对应冻结文件：`PRODUCT-FREEZE.md`
对应冻结基线：`4e83f3baeb5f4d6d9ee9b8bfc61c112abc1f55cb` (v0.8)
更新时间：2026-09-09
维护者：Codex

## C 线 P0 完成情况

| 冻结项 | 状态 | 实现位置 | 测试证据 | 是否影响主 Demo |
|---|---|---|---|---|
| 千牛三栏模拟工作台与 360–420px 右侧插件 | 已完成 | `frontend/src/App.tsx`, `frontend/src/styles.css` | 生产构建通过 | 是 |
| 第一屏三问：已知、不能做、下一步 | 已完成 | `frontend/src/App.tsx` | 三种案例均可切换 | 是 |
| `INTERVENE` / `ALLOW` / `HUMAN_REVIEW` | 已完成 | `frontend/src/mockApi.ts` | Vitest 三组决策契约通过 | 是 |
| 体验断层诊断、解决路径、人工确认 | 已完成 | `frontend/src/App.tsx` | 人工批准后才生成运行中义务 | 是 |
| 服务进度回执、倒计时、催办与主动通知 | 已完成 | `frontend/src/App.tsx` | 回执和风险分支测试通过 | 是 |
| 物流时序：未揽收、已揽收、已送达 | 已完成 | `frontend/src/mockApi.ts` | 未揽收直接送达被拒绝；揽收后送达进入 `RESOLVED` | 是 |
| v0.8 四接口类型、统一响应外壳和 JSON 示例 | 已完成 | `frontend/src/api/` | TypeScript 编译通过 | 是 |
| Challenge Mode、缓存标识、加载态与可重试错误 | 已完成 | `frontend/src/App.tsx` | 缓存/模型不可用测试通过 | 是 |

## 未完成

| 范围 | 未完成内容 | 原因 | 下一步 |
|---|---|---|---|
| B/C 联调 | 真实后端四端点联调 | B 端实现不在本 C 线分支范围 | B 端可用后设置 `VITE_API_MODE=http` 执行联调 |
| 真实证据图 | `public/evidence/` 内的团队压力测试图片二进制文件 | 当前未在 C 工作区提供 | 图片就位后按 README 的固定文件名放入；当前 UI 有明确占位回退 |
| 独立验收 | `QA-ACCEPTANCE.md` 对全部 P0 标记通过 | 属于 G4/G5 后续门禁 | 产品负责人启动 Claude 只读验收 |

## 测试结果

| 检查 | 命令/步骤 | 结果 | 证据位置 |
|---|---|---|---|
| C 端契约与主流程 | `npm test -- --run` | 1 个测试文件、6 项测试全部通过 | `frontend/src/mockApi.test.ts` |
| TypeScript 与生产构建 | `npm run build` | 通过，Vite 成功生成生产产物 | `frontend/package.json` |

## 技术阻塞与事实证据

- C 线当前无独立技术阻塞。
- 切换真实 HTTP 模式需要 B 端四端点可访问，但不影响本地可点击 Demo。

## 已知风险与灾备

| 风险 | 触发条件 | 当前影响 | 灾备 | 是否影响 Demo |
|---|---|---|---|---|
| 模型不可用 | analyze 返回 `MODEL_UNAVAILABLE` | 无新抽取结果 | 显示可重试失败态；有缓存时显示“缓存抽取结果” | 否 |
| 物流事件逆序 | 未揽收直接送达 | 不允许假性结案 | 保持原状态并显示错误 | 否 |
| 图片未放入 | 证据图 URL 加载失败 | 不显示真实测试图 | 自动使用明确的 CSS 占位图 | 否 |
