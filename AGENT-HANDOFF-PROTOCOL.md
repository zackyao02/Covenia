# Covenia｜Claude × Codex 协作与交接协议

## 核心规则

Claude 与 Codex 不通过 API 直连。两者共享同一个 Git 工程目录，通过可追溯的 Markdown 文件交接。Claude 负责优化产品并创建冻结草案；产品负责人是唯一能批准冻结版本、改变已批准范围和确认修复清单的人。产品负责人在 Codex 对话中的明确批准指令，由 Codex 精确记录到交接文件，产品负责人无需手动编辑文件；Claude 的建议本身不构成批准。

```text
Claude 开发前终审 → CLAUDE-REVIEW-1.md
Claude 独立红队   → CLAUDE-REDTEAM.md
产品负责人拍板   → PRODUCT-FREEZE.md（APPROVED）
Codex 开发        → IMPLEMENTATION-STATUS.md
Claude 独立验收   → QA-ACCEPTANCE.md
产品负责人拍板   → FIX-REQUESTS.md（APPROVED）
Codex 有限修复    → 更新 IMPLEMENTATION-STATUS.md
Claude 复验       → 更新 QA-ACCEPTANCE.md
```

## 文件职责

| 文件 | 唯一写入者 | 允许内容 | 禁止内容 |
|---|---|---|---|
| `CLAUDE-PREFLIGHT-REVIEW.md` | 产品负责人/Codex 代整理 | 事实、问题、审查契约 | Claude 的结论 |
| `CLAUDE-REVIEW-1.md` | 终端重定向 Claude 输出 | 开发前终审 | 改写冻结范围 |
| `CLAUDE-REDTEAM.md` | 终端重定向独立 Claude 输出 | 淘汰式攻击与三项建议 | 读取首轮结论后迎合 |
| `PRODUCT-FREEZE.md` | Claude 起草，产品负责人批准 | 唯一产品范围与验收定义 | `APPROVED` 之前启动开发；“有时间再做”的隐性范围 |
| `IMPLEMENTATION-STATUS.md` | Codex | 完成、未完成、测试、阻塞、风险 | 新产品方向 |
| `QA-ACCEPTANCE.md` | 终端重定向 Claude 输出 | 逐项验收、缺陷、证据 | 直接修代码或扩范围 |
| `FIX-REQUESTS.md` | 产品负责人 | 已确认的有限修复 | 新功能与未批准建议 |

## 阶段门禁

| 门禁 | 必须满足 | 未满足时禁止 |
|---|---|---|
| G0 终审输入 | 工程基线与 `CLAUDE-PREFLIGHT-REVIEW.md` 可读 | Claude 开始终审 |
| G1 评审完成 | `CLAUDE-REVIEW-1.md`、`CLAUDE-REDTEAM.md` 均非空 | 编写最终冻结版 |
| G2 产品冻结 | Claude 已生成 `DRAFT` 草案；产品负责人确认内容后含 `审批状态：APPROVED` 和批准日期 | Codex 开发产品功能 |
| G3 实现完成 | `IMPLEMENTATION-STATUS.md` 列出 P0、测试证据和已知风险 | Claude 开发后验收 |
| G4 修复批准 | `FIX-REQUESTS.md` 含 `审批状态：APPROVED` 和批准日期 | Codex 验收修复 |
| G5 发布候选 | `QA-ACCEPTANCE.md` 对所有 P0 标记通过 | 最终演示包或发布候选 |

Claude 的建议、Codex 的技术替代方案和口头讨论均不能自动跨越门禁。

## 交互式执行方式

以下命令从 Windows CMD 运行，当前目录必须是本工程根目录。使用交互模式的目的是让产品负责人先在屏幕上完整阅读、追问和判断 Claude 的交付；不使用 `-p` 或 `>` 静默重定向。产品负责人不需要导出或复制。

### 开发前终审

先启动 Claude：

```bat
claude --model opus --effort high --permission-mode plan --tools "Read,Glob,Grep"
```

进入 Claude 后粘贴：

```text
严格遵守 CLAUDE.md，完整读取 CLAUDE-PREFLIGHT-REVIEW.md 及其证据清单，按输出契约进行开发前终审。先在终端完整展示最终报告，不修改任何文件，也不要自行保存文件；等待我阅读和追问。
```

产品负责人读完后，回到 Codex 发送“确认保存本轮终审”。Codex 自动生成 `CLAUDE-REVIEW-1.md`；该确认只保存审查记录，不表示批准产品范围。

### Claude 产品优化与冻结草案

产品负责人认可终审方向后，启动一个新的 Claude 会话：

```bat
claude --model opus --effort high --permission-mode acceptEdits --tools "Read,Glob,Grep,Edit,Write"
```

进入 Claude 后粘贴：

```text
严格遵守 CLAUDE.md。读取 CLAUDE-REVIEW-1.md、CLAUDE-PREFLIGHT-REVIEW.md、AGENT-HANDOFF-PROTOCOL.md 和工程事实文件。你负责优化产品，不负责开发：按 handoff-templates/PRODUCT-FREEZE.template.md 创建 PRODUCT-FREEZE.md 草案，解决已确认的 P0 契约和 Hero 演示问题。不得修改代码、schemas、fixtures、既有 docs、配置或 Git；不得新增独立模块、页面或售后场景；审批状态必须保持 DRAFT。完成后在终端解释每个取舍，等待我审阅。
```

产品负责人审阅草案后，只有明确回复“批准冻结”时，才能将其标记为 `APPROVED`；产品负责人在 Codex 对话中给出该指令后，Codex 负责记录批准状态、批准人和日期。此前 Codex 不得开发。

### 独立红队

使用新 Claude 会话，不读取 `CLAUDE-REVIEW-1.md`：

新开一个 CMD 窗口并启动同样的只读 Claude：

```bat
claude --model opus --effort high --permission-mode plan --tools "Read,Glob,Grep"
```

进入 Claude 后粘贴：

```text
严格遵守 CLAUDE.md。不要读取 CLAUDE-REVIEW-1.md。作为决赛淘汰评委独立攻击当前 Covenia 方案，只展示：致命伤、Top 5 扣分项、只能修改的三件事、当前可演示性、修改后潜力和每项验证方法。不要修改或自行保存任何文件，等待我阅读和追问。
```

读完后，产品负责人回到 Codex 发送“确认保存本轮红队”。Codex 自动生成 `CLAUDE-REDTEAM.md`；该确认只保存红队记录，不表示批准产品范围。

### 开发后验收

```bat
claude --model opus --effort high --permission-mode plan --tools "Read,Glob,Grep"
```

进入 Claude 后粘贴：

```text
严格遵守 CLAUDE.md，只读 PRODUCT-FREEZE.md、IMPLEMENTATION-STATUS.md、相关实现和测试证据。逐条执行独立验收，在终端展示通过/阻塞、缺陷等级、复现步骤、证据和最小修复建议。不要修改或自行保存任何文件，等待我阅读和追问。
```

产品负责人读完后，回到 Codex 发送“确认保存本轮验收”。Codex 自动生成 `QA-ACCEPTANCE.md`。空文件、错误信息或未经产品负责人阅读确认的记录都不算有效产物，不能跨越门禁。

## 模板使用

四份模板位于 `handoff-templates/`，模板本身不得作为已通过门禁的实际交接文件：

| 模板 | 生成的实际文件 | 使用者 |
|---|---|---|
| `handoff-templates/PRODUCT-FREEZE.template.md` | `PRODUCT-FREEZE.md` | Claude 起草为 DRAFT，产品负责人审阅并批准 |
| `handoff-templates/IMPLEMENTATION-STATUS.template.md` | `IMPLEMENTATION-STATUS.md` | Codex 在开发开始时复制并持续更新 |
| `handoff-templates/QA-ACCEPTANCE.template.md` | `QA-ACCEPTANCE.md` | Claude 的只读输出由终端保存 |
| `handoff-templates/FIX-REQUESTS.template.md` | `FIX-REQUESTS.md` | 产品负责人复制、筛选缺陷并批准 |

Claude 可以从 `PRODUCT-FREEZE.template.md` 起草产品冻结草案，但必须保留 `审批状态：DRAFT`。`PRODUCT-FREEZE.md` 和 `FIX-REQUESTS.md` 只有在产品负责人明确批准后才生效；Codex 负责把该批准原样记录为批准人、批准日期和 `审批状态：APPROVED`。Claude 不得自行完成批准字段，也不得修改已批准范围。

## Codex 开发指令

产品冻结后，给 Codex 的首条任务固定为：

> `PRODUCT-FREEZE.md` 是唯一产品范围与验收依据。先检查其审批状态；未标记 `APPROVED` 时不得开发。先实现并验证 `S00001` 的完整 Hero 闭环，再实现其他 P0。不得新增产品功能或改变产品逻辑。若遇到技术阻塞，在 `IMPLEMENTATION-STATUS.md` 写明事实、影响和最小替代方案，等待产品负责人决定。每完成一个阶段，运行相应测试并更新实现状态。
