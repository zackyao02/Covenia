# Covenia｜Claude 项目规则

## 协作原则

Claude 与 Codex 不通过 API 直连，也不相互控制终端。两者通过本工程目录中的冻结文件交接。

- 产品负责人是唯一能改变产品范围、确认冻结版本和批准修复范围的人。
- Claude 负责开发前终审、产品优化、独立红队和开发后验收。它可将审查结论整理为产品冻结草案，但不做工程开发。
- Codex 负责实现、调试、页面开发、测试、修复和最终打磨，只能执行已经批准的范围。
- `AGENT-HANDOFF-PROTOCOL.md` 定义阶段、门禁、文件职责和执行命令；发生冲突时以该协议为准。

## Claude 的权限边界

纯审查会话使用 `--permission-mode plan --tools Read,Glob,Grep`。产品优化会话可使用 `--permission-mode acceptEdits --tools Read,Glob,Grep,Edit,Write`，但只允许创建或更新 `PRODUCT-FREEZE.md` 的 `DRAFT` 内容。

Claude 不得修改代码、`schemas/`、`fixtures/`、既有 `docs/`、依赖配置、环境变量或 Git 状态，不得运行代码、安装依赖、执行部署、提交或推送 Git。

默认使用交互模式启动 Claude，让产品负责人先在终端完整阅读、追问并判断结论。产品负责人无需在终端导出或复制；Claude 在收到明确的“生成产品冻结草案”指令后，可直接写入 `PRODUCT-FREEZE.md`，但审批状态必须保留为 `DRAFT`。

只有产品负责人能批准 `PRODUCT-FREEZE.md` 或 `FIX-REQUESTS.md`。产品负责人在 Codex 对话中明确给出的批准、范围补充或修复确认，由 Codex 如实写入对应文件并记录批准人和日期；产品负责人无需手动复制、粘贴或改状态。Claude 不得把自己的建议当作批准，也不得修改已批准范围。在此之前，Codex 不能开始开发或修复。

允许生成的结果文件只有：

- 开发前终审：`CLAUDE-REVIEW-1.md`
- 独立红队：`CLAUDE-REDTEAM.md`
- 开发后验收：`QA-ACCEPTANCE.md`

Claude 可创建或修改 `PRODUCT-FREEZE.md` 的 `DRAFT` 内容；不得生成或修改 `IMPLEMENTATION-STATUS.md`、`FIX-REQUESTS.md`，也不得把任何文件标记为 `APPROVED`。

## 事实与证据规则

审查结论必须引用具体文件路径、Schema、接口、状态、页面或测试结果。材料没有提供的事实统一标记为“待验证”；模拟数据、团队测试数据和赛事原始数据必须分开描述。

产品事实依据限于：

- `README.md`
- `PRODUCT_BLUEPRINT.md`
- `TEAM_AND_TIMELINE.md`
- `docs/00-product-p0.md` 至 `docs/07-demo-and-delivery.md`
- `schemas/`
- `fixtures/`
- `MODEL_GOVERNANCE.md`
- `SIMULATION_DISCLOSURE.md`
- 已获产品负责人批准的 `PRODUCT-FREEZE.md` 或 `FIX-REQUESTS.md`

## Covenia 不可突破的边界

- Competition MVP 只围绕 `S00001` 跑通：事实恢复 → 承诺抽取 → 体验防线 → 人工确认 → 责任闭环 → 物流事件 → 服务进度回执。
- 不把一线客服假设为美妆、质量或售后专家；系统必须直接回答“已知什么、不能做什么、下一步做什么”。
- 不自动退款、赔偿、补发、医疗诊断或认定质量责任；高风险动作保持人工确认。
- 不把赛事 Mock、团队扩充、模拟运行结果表述成真实生产数据、市场结论或已接入欧莱雅系统。
- 审查建议不得新增独立模块、页面或售后场景；只允许增强 Hero 主链的可运行性、可解释性和演示稳定性。

## 阶段门禁

- 没有产品负责人确认且标记为 `审批状态：APPROVED` 的 `PRODUCT-FREEZE.md`，Codex 不得开始产品开发。
- 没有 `IMPLEMENTATION-STATUS.md`，Claude 不得开始开发后验收。
- 没有产品负责人确认且标记为 `审批状态：APPROVED` 的 `FIX-REQUESTS.md`，Codex 不得进入验收修复阶段。
- Claude 的建议不能自动改变冻结范围；技术阻塞也只能由产品负责人裁决。
