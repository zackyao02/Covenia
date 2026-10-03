# Covenia 实现状态

对应冻结文件：`PRODUCT-FREEZE.md`
对应冻结基线：`4e83f3baeb5f4d6d9ee9b8bfc61c112abc1f55cb` (v0.8)
更新时间：2026-10-03
维护者：Codex

## JEV 实际 API 烟测（2026-10-03）

- 用户已在本机项目根目录 `.env` 配置 TypeSafe API Key；`.env` 已被 Git 忽略，不会提交密钥。
- 对合成演示案例 `DEMO_001` 发起真实后端分析，TypeSafe 返回有效 JEV 结果：`READY`、情绪恶化概率 `0.93`、建议动作 `CHECK_REPLACEMENT`（概率 `0.92`），调用耗时约 `1.65s`；没有触发本地 fallback。
- 随后在工作台点击“重新分析”，案例恢复显示。密钥未输出或写入项目文档。
- 本次是单次合成数据烟测，不代表阈值已校准或真实消费者数据已验证；`thresholds_validated=false`，人工升级概率为 `0.47`。JEV 只提供软指标建议，规则引擎仍负责硬性责任与风险拦截。

## 本轮体验改进（2026-10-02）

基于团队共享分支 `feature/bc-v1.1-product-attempt` 的 `830ef8e`，由用户授权子 agent 改进。子 agent 已按用户要求切换为 GPT-6-Luna；主线程负责集成。

- 发送前提交实际草稿，明确的进度回复可本地记录；重复索证/提前结案继续受硬规则控制，新承诺与未知文本需人工确认。
- 人工确认提交实际回复、执行方和下次更新时间，保存到批准结果、回执与审计；确认后的编辑文本再次受服务端检查。
- 待处理队列读取后端状态，已解决案件退出队列；切换案件保留已确认的服务进度。
- 首屏突出证据、负责方、更新时间；沟通建议保留来源，未取得有效 JEV 结果显示待确认。
- JEV 接入按官方 Noul/Choice 响应检查，模型输入脱敏，失败不生成情绪概率，缓存随消息内容变化。

本轮本地修改尚未提交。本轮独立重跑前后端自动测试与生产构建；全新浏览器会话确认主案例显示 09:32 二次进线、原始模糊回复，并明确标出图文演示适配器与未计量状态。此前已验证“查询进度→人工确认→未揽收催办→延迟后揽收→送达闭环”。这属于 Codex 自验，不等同于队员或 Claude 的独立验收。草稿判断仍是关键词规则，JEV 阈值尚未校准；工作台未接真实千牛发送，后端状态仍在进程内存中。

### 视觉与交互打磨（2026-10-02）

以可读性和服务动作清晰度为首要设计目标：统一暖白、深墨与克制紫色的视觉体系；拉开会话、事实、下一步的层级与留白；保留真实千牛工作台语境，清除未实现的空按钮。会话搜索、未回复筛选、服务记录展开与 Enter 发送现在有实际交互。不同屏宽下采用三栏、会话横排双栏、移动端纵向顺序；动效为轻量反馈，并尊重系统减少动态效果设置。

生产构建通过（1585 个模块，JS 197.50 kB）；在 390、768、840、920、1024、1280、1440px 宽度查看布局，未见页面级横向裁切。浏览器中验证搜索、筛选、案件切换、查询进度及人工确认弹窗，未出现控制台错误。视觉验收图：`artifacts/2026-10-02-experience-desktop.png` 与 `artifacts/2026-10-02-experience-mobile.png`。完整自动测试和端到端业务验收仍按用户安排留待后续。

设计自检：排版采用明确的标题、正文与辅助信息层级；留白让当前消费者诉求与下一步动作独立成组；紫色只用于品牌与主操作，风险状态保留独立语义色；悬停、按下、焦点和加载反馈保持轻量，并提供减少动效模式；窄屏不丢失主要动作；Covenia 的「连续负责」用队列→事实→下一步的固定阅读顺序表达。模态窗不再向客服暴露内部规则号。当前截图未见需通过装饰性模块填补的空白。

## C 线 P0 完成情况

| 冻结项 | 状态 | 实现位置 | 测试证据 | 是否影响主 Demo |
|---|---|---|---|---|
| 千牛响应式工作台与右侧插件 | 已完成 | `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/src/experience.css` | 生产构建和多屏宽视觉检查通过 | 是 |
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
| B/C 联调 | 队友或 Claude 对本轮的独立浏览器验收 | 本轮 Codex 已完成浏览器主闭环自验 | 由 D 线/Claude 按 `QA-ACCEPTANCE.md` 独立复测 |
| 证据图核验 | 图片来源与业务适用性验收 | 本工作区已有五张 `public/evidence/*.jpg`；文件存在不代表真实消费者证据 | 演示使用时按素材来源声明，后续核验图片与案例一致性 |
| 独立验收 | `QA-ACCEPTANCE.md` 对全部 P0 标记通过 | 本次为 G3 后的有限修复；尚未重新独立验收 | 修复提交后启动 Claude 只读复验 |

## 测试结果

| 检查 | 命令/步骤 | 结果 | 证据位置 |
|---|---|---|---|
| C 端契约与主流程 | `npm test -- --run` | 1 个测试文件、11 项测试全部通过 | `frontend/src/mockApi.test.ts`（2026-09-10） |
| TypeScript 与生产构建 | `npm run build` | 通过；Vite 生成 `dist/`，JS 230.13 kB（gzip 67.36 kB） | `frontend/package.json`（2026-09-10） |
| JSON 与决策 Schema | Python JSON + Draft 2020-12 校验 | 17 个 JSON 文件可解析；3 个 `DecisionResult` 示例通过 | `schemas/decision-result.schema.json`（2026-09-10） |
| B 端 API | `python -m pytest backend/tests -q` | 5 项测试全部通过 | `backend/tests/test_api.py`（2026-09-13） |
| B/C 浏览器 HTTP 联调 | `VITE_API_MODE=http` 启动前后端 | 主案例 E1 拦截、赠品 E2 放行、模糊图 H1 人工复核；查询→确认→揽收→送达闭环通过 | `backend/main.py` 与 `frontend/src/App.tsx`（2026-09-13） |
| 当前优化版后端接入 | 使用本地前端连接 B 线服务，逐一调用 analyze、evaluate、approve、shipment | 四接口烟测通过：`ACTION_REVIEW`、`INTERVENE/E1`、`IN_FULFILLMENT`、`AT_RISK`；`npm run build` 通过。未运行完整测试套件 | `backend/main.py`、`frontend/src/api/client.ts`（2026-09-29） |
| 当前视觉迭代 | `npm run build`；浏览器检查 1440px、1024px、390px，点击队列和证据入口 | 构建通过；三种宽度无横向溢出，队列选择后自动收起，证据入口可展开原始会话；未运行完整测试套件 | `artifacts/2026-10-02-qianniu-covenia-desktop.png`、`artifacts/2026-10-02-qianniu-covenia-mobile.png`（2026-10-02） |
| 标识与排版复核 | 新 Covenia 双弧标识；正文、动作、证据及响应式再调整；`npm run build` 与浏览器交互检查 | 构建通过（1586 模块）；1440/1024/768/390/320px 无页面级横向溢出，队列切换与详情展开正常；完整测试套件未运行 | `artifacts/2026-10-02-visual-audit.md`、`artifacts/2026-10-02-final-desktop.png`、`artifacts/2026-10-02-final-mobile.png`（2026-10-02） |
| 界面设计专项 | 使用 `frontend-design` Skill 制定“服务证据卷宗”方向，重排插件首屏、证据图与主动作；桌面和 390/320px 窄屏复核 | `npm run build` 通过（1586 模块，JS 201.79 kB）；无页面级横向溢出；证据大图可打开/关闭、Esc 关闭、焦点回到缩略图。完整业务测试仍待后续 | `artifacts/2026-10-02-frontend-design-direction.md`、`artifacts/2026-10-02-dossier-desktop.png`、`artifacts/2026-10-02-dossier-mobile.png`（2026-10-02） |
| 赛博轻奢视觉迭代 | 根据用户四张截图统一首屏、人工复核、服务进度和确认弹窗；换用 3D 交接标识、磨砂玻璃浮层、深青绿与局部珊瑚撞色；修复加载态在深底上的对比度 | `npm run build` 通过（1587 模块，JS 201.87 kB）；本地浏览器检查主案例、人工复核展开、物流状态与桌面/手机弹窗；390px 页面无横向溢出，手机弹窗确认按钮可见。完整业务测试仍待后续 | `artifacts/2026-10-02-visual-system-v2.md`、`artifacts/2026-10-02-cyber-first-desktop.png`、`artifacts/2026-10-02-cyber-review-desktop.png`、`artifacts/2026-10-02-cyber-progress-desktop.png`、`artifacts/2026-10-02-cyber-modal-mobile.png`（2026-10-02） |
| 玻璃视觉一致性修正 | 顶栏、按钮、队列、判断依据、倒计时、进度节点与确认弹窗统一光源、材质和按压反馈；用深色次级面板拉开阅读层次 | `npm run build` 通过（1587 模块，JS 201.87 kB）；浏览器核对队列、判断依据、进度、桌面及 390px 手机弹窗；390px 页面无横向溢出；`git diff --check` 通过。完整业务测试仍待后续 | `artifacts/2026-10-02-glass-consistency-progress.png`、`artifacts/2026-10-02-glass-consistency-decision.png`、`artifacts/2026-10-02-glass-consistency-timeline.png`、`artifacts/2026-10-02-glass-consistency-modal.png`、`artifacts/2026-10-02-glass-consistency-modal-mobile.png`（2026-10-02） |
| 卡片边缘视觉清理 | 移除风险卡红色侧条、判断卡金色侧条及同类装饰条，保留图标、文字和状态标签传达风险 | `npm run build` 通过（1587 模块）；浏览器核对主案例和人工复核展开态；`git diff --check` 通过 | `artifacts/2026-10-02-no-edge-stripes-progress.png`、`artifacts/2026-10-02-no-edge-stripes-review.png`（2026-10-02） |
| JEV 实际 API 烟测 | 使用本机 `.env` 密钥调用 `DEMO_001`，检查 TypeSafe 返回来源、状态、建议概率及延迟；工作台点击“重新分析”后恢复 | TypeSafe 返回 `READY`、`WORSENING 0.93`、`CHECK_REPLACEMENT 0.92`，耗时约 1.65 秒，`fallback_used=false`；阈值未校准，仅为合成数据单次烟测 | 本机 `GET /api/customer-state/DEMO_001` 与 `POST /api/cases/analyze`（2026-10-03） |
| JEV 接入后生产构建 | `python -m compileall -q backend`；`npm run build` | 后端语法检查通过；前端生产构建通过，1587 个模块，JS 201.87 kB（gzip 63.60 kB） | 本轮本机检查（2026-10-03） |
| 本轮自动化回归 | `npm --prefix frontend test -- --run`；`python -m pytest backend/tests -q`；`npm --prefix frontend run build` | 前端 11/11、后端 12/12 通过；构建通过（1587 模块，JS 202.45 kB，gzip 63.79 kB） | 本轮本机运行（2026-10-03） |
| 演示模式与计量边界 | 前后端示例、API schema、UI 运行信息、交付文案核对 | 本地演示适配器标为 `COVENIA_DEMO_ADAPTER`；未调用图文模型时 tokens/latency 显示未计量；README、交付指南和答辩稿不再声称现场图文抽取或 Excel 运行时导入 | 本轮代码与静态核对（2026-10-03） |
| 浏览器服务闭环 | 查询补发进度→确认责任与回复→未揽收催办→延迟后揽收→送达 | 主链完成，责任状态到 `RESOLVED`；发现并修复未揽收后时间倒退与已揽收后仍可点未揽收的问题 | `QA-ACCEPTANCE.md`（2026-10-03） |

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
- 2026-10-03：前后端和本轮体验修改已推送至 `codex/bc-v1.1-optimized`；Codex 主闭环自验通过，仍需 D 线或 Claude 独立验收。
- 2026-10-02：Covenia 视觉迭代以千牛接待工作台的会话、聊天和侧栏结构为底；右侧插件改为“当前动作优先”，证据、负责人、更新时间分层呈现，队列以浮层展开。增加自绘 Covenia 标识和千牛风格的演示标识；后者不是千牛官方素材，也不代表已完成千牛平台接入。桌面 1440px、平板 1024px、手机 390px 已做视觉检查，仍待团队独立验收。

## 已知风险与灾备

| 风险 | 触发条件 | 当前影响 | 灾备 | 是否影响 Demo |
|---|---|---|---|---|
| 模型不可用 | analyze 返回 `MODEL_UNAVAILABLE` | 无新抽取结果 | 显示可重试失败态；有缓存时显示“缓存抽取结果” | 否 |
| 物流事件逆序 | 未揽收直接送达 | 不允许假性结案 | 保持原状态并显示错误 | 否 |
| 图片未放入 | 证据图 URL 加载失败 | 不显示真实测试图 | 自动使用明确的 CSS 占位图 | 否 |
