# 13｜JEV 融合方案与 To-do List

## 1. 产品定位

JEV 不取代 Covenia Risk Engine，也不直接执行退款、补发、责任认定或人工转接。它把经过最小化处理的 Customer State 转成有类型的概率化软信号；Covenia 再将这些信号与 Promise 超时、重复联系、证据状态和体验防线等确定性业务事实并排呈现。

```text
Conversation + Customer State
              ↓ 最小化、脱敏
            JEV
              ↓
Choice: emotion_change
Noul: needs_human_review
Score: service_urgency
              ↓
Covenia Decision Support（建议层）
              ↓
硬规则 / 权限 / 人工审批继续优先
```

当前运营 Risk Score 不接入 JEV 分值。界面仅展示以下实验公式预览：

```text
20 × P(emotion_worsening) + 30 × P(needs_human_review)
```

该结果固定标记为 `used_for_operational_risk: false`。只有完成真实标注集校准、阈值验证、业务评审和灰度实验后，才可提出进入正式 Risk Engine 的变更。

## 2. 已完成 To-do

- [x] 将完整对话旅程而非最后一句话投影成 JEV state。
- [x] 输入包含证据、重复联系、等待、Promise、工单和现有规则输出。
- [x] 不发送订单号、图片文件名、工单号、来源 ID 等非必要标识。
- [x] 对电话、邮箱和长数字标识做基础脱敏并记录数量。
- [x] 使用 JEV `choice` 输出 `improving / stable / worsening`。
- [x] 使用 JEV `noul` 输出需人工复核的 yes 概率。
- [x] 使用 JEV `score` 输出 0–3 服务紧迫度。
- [x] 一个请求并行发送三种 typed questions。
- [x] 新增真实 JEV Provider、关闭模式和契约 Mock 模式。
- [x] 默认 Mock 明确标注“不是 JEV 实际输出，不可证明校准能力”。
- [x] Provider 失败时 fail-open，保留原有规则链和客服操作。
- [x] JEV 信号不覆盖 Experience Firewall、权限或人工审批。
- [x] JEV 信号不改变当前运营 Risk Score。
- [x] 前端新增 `JEV Decision Signals` 卡片。
- [x] 新增 `/api/jev/status` 与 `/api/jev/cases/analyze`。
- [x] 新增状态最小化、契约、治理边界和故障回退测试。

## 3. 接入真实 JEV 前 To-do

### P0：真实 API 联调

- [ ] 在 TypeSafe Console 申请并保管 API Key，不写入仓库或前端。
- [ ] 使用 `GET /v1/models` 核对账号可用模型，并在验收环境固定模型版本。
- [ ] 配置 `JEV_MODE=live`、`TYPESAFE_API_KEY` 和 `JEV_MODEL`。
- [ ] 用无个人信息的测试集完成首次联调，核对 401、422、429、5xx 和超时处理。
- [ ] 增加请求量、延迟、错误率、token 使用和 Provider 版本监控。

### P0：隐私与治理

- [ ] 由数据负责人确认哪些对话字段允许发送至第三方模型服务。
- [ ] 评估现有正则脱敏对姓名、地址、账号和特殊身份信息的召回率。
- [ ] 明确数据驻留、保留期限、删除机制、DPA 和跨境处理要求。
- [ ] 将 API Key 放入 Secret Manager，并建立轮换、最小权限和审计机制。
- [ ] 为真实请求增加明确的环境级开关和紧急熔断。

### P1：校准与阈值验证

- [ ] 建立至少包含情绪变化、需人工介入和紧迫度标签的真实匿名评测集。
- [ ] 按渠道、问题类型、消费者群体和语言风格做分层评测。
- [ ] 评估 accuracy、macro-F1、Brier Score、ECE 和 reliability diagram。
- [ ] 验证 `needs_human_review >= 0.8` 是否满足业务精确率与召回率要求。
- [ ] 对比 JEV、现有词法规则和人工判断，不以单个 Demo 案例下结论。
- [ ] 记录 pinned model 与 `jev-latest` 的差异，避免模型升级造成静默漂移。

### P1：Shadow Mode

- [ ] 先运行 2–4 周影子模式，只记录建议，不改变客服动作、Risk 或队列顺序。
- [ ] 让人工客服对“情绪变化、是否需人工、紧迫度”进行反馈。
- [ ] 统计 JEV 建议与人工一致率、误升级率、漏升级率及人群差异。
- [ ] 任何进入 NBA 或 Risk 的改动均需单独评审、版本化和可回滚。

### P2：有限业务使用

- [ ] 仅将高置信度 `needs_human_review` 用于生成“人工复核候选”，仍需人工确认。
- [ ] 将 JEV 信号写入审计日志，包含模型版本、问题版本、概率、阈值和最终人工决定。
- [ ] 对低置信度、Provider 超时或输入不足统一显示“不确定”，不得自动补全结论。
- [ ] 完成 A/B 或 stepped-wedge 实验，验证 AHT、FCR、重复询问率和 CSAT 是否改善。

### P3：Risk Engine 候选实验

- [ ] 仅在 P1/P2 指标通过后评估是否把软信号加入正式风险公式。
- [ ] 即使加入，硬规则继续最高优先级，情绪概率不能单独触发惩罚性或不可逆动作。
- [ ] 将正式公式、权重、适用范围、校准数据和回滚条件写入模型治理文档。

## 4. 本地运行模式

默认运行契约 Mock，不访问外部网络：

```bash
npm start
```

关闭 JEV：

```bash
JEV_MODE=off npm start
```

真实 JEV：

```bash
JEV_MODE=live TYPESAFE_API_KEY='<key>' JEV_MODEL='jev-latest' npm start
```

API Key 只能作为环境变量或 Secret 注入，禁止提交到 Git。

## 5. 验收标准

| ID | 操作 | 期望结果 |
|---|---|---|
| JEV-1 | 默认启动并选择 DEMO_001 | 显示三类软信号，Provider 标记为 `JEV_CONTRACT_MOCK` |
| JEV-2 | 查看治理说明 | 明确概率为模拟值、不进入当前 Risk、不覆盖规则 |
| JEV-3 | `JEV_MODE=off` 启动 | 卡片显示不可用，其他 P0/P1 功能正常 |
| JEV-4 | Live Provider 超时或失败 | 返回 ERROR，`integration_policy=FAIL_OPEN_TO_EXISTING_RULES` |
| JEV-5 | Live 调用 | 请求只包含最小化 state、model 和三种 typed questions |
| JEV-6 | 对比接入前后 | 运营 Risk Score、体验防线和审批规则不因 JEV 自动改变 |

## 6. 官方资料

- TypeSafe API OpenAPI：<https://api.typesafe.ai/openapi.json>
- TypeSafe API 文档：<https://api.typesafe.ai/docs>
- TypeSafe 关于 System One Models 与 JEV 的说明：<https://typesafe.ai/blog/introducing-system-one-models-and-jev>
- TypeSafe 数据处理协议：<https://typesafe.ai/legal/data-processing>

JEV 的校准、速度和模型能力描述属于 TypeSafe 的官方声明；Covenia 必须通过自己的业务数据独立验证，不能把供应商声明直接当作本产品效果证据。
