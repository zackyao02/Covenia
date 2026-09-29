# Covenia 完整产品蓝图

完整产品蓝图说明 Covenia 最终是什么产品；Competition MVP 只决定本次比赛实现多深，不反向删除产品机制。

## 产品定义

> Covenia 是品牌服务承诺执行 Agent。它记住消费者已经提交的证据，把客服在自然语言中作出的有效服务承诺转化为可追踪责任，并在下一动作发生前防止重复伤害，在承诺失效前主动推动品牌完成服务。

消费者语言：消费者不应该成为自己售后问题的项目经理。

## 一条完整主链

```text
Experience Ledger
→ Customer State
→ Risk / Decision
→ Action / Priority
→ Resolution
```

旧版“多源服务旅程理解、消费者体验责任账本、体验防线、下一解决路径、责任闭环、流程风险发现”不删除，而是按四层拆清边界：

```text
BC Core（不破坏）
Experience Ledger / Evidence / Promise / Firewall / Resolution

Customer Extension（新增）
Intent / Emotion / Effort / Risk / Decision / Deadline

Aggregate / Operational State（独立）
Priority Queue / Emerging Issue / Risk Radar

Model Governance（独立）
JEV Decision / Confidence / Threshold / Fallback / Audit
```

其中 BC Core 是现有纵向链路，不因 v1.1 改名或重写；Customer Extension 只在核心事实之上增加消费者状态理解；Aggregate / Operational State 只做排序、聚合和运营观察，不写回原始事实；Model Governance 只约束模型和 Jev 的使用方式，不成为业务状态本身。

承诺编译与执行贯穿整条链路，不新增孤立的“承诺 Agent”：AI 从聊天中识别承诺，系统校验其类型、条件和权限，把有效承诺写入账本，随后由责任闭环持续执行。

## v1.1 新增 8 项能力

v1.1 将以下能力正式纳入完整产品定义，并在 BC line 中以新版 Customer Workspace 呈现：

| 能力 | 所属主链 | 产品定义 |
|---|---|---|
| Customer State | Customer Extension | 在核心事实之上组织 Intent、Emotion、Effort、Risk、Decision、Deadline。 |
| Emotion State | Customer Extension | 记录情绪表达、趋势和原因，只辅助沟通，不直接决定风险分和业务动作。 |
| Effort | Customer Extension | 记录消费者重复解释、重复举证、等待和多次进线成本。 |
| Source Evidence | BC Core | 所有判断必须可回到聊天、图片、订单、工单或物流来源。 |
| Risk State | Customer Extension | 作为单个消费者的服务风险状态，不输出投诉、流失或市场预测结论。 |
| Priority State | Aggregate / Operational State | 把风险、承诺、等待和业务紧急度转成队列排序，不写回核心事实。 |
| Emerging Issue | Aggregate / Operational State | 聚合多个已发生事实模式，必须人工确认，固定标注非预测。 |
| Deadline State | Customer Extension / Resolution | 把 Promise 接入 Monitor，驱动 Near Due、Overdue、Escalation 和主动回执。 |

## 1. 多源服务旅程理解

整合历史与当前聊天、图片、订单、售后工单、物流单号和处理状态，将分散信息转化为带来源追踪的事实。AI 同时输出消费者意图、体验表达、服务成因和潜在需求，但不生成孤立的情绪指数。

## 2. 消费者体验责任账本（Experience Ledger）

这是唯一对外核心数据对象，回答：

1. 消费者已经完成什么。
2. 已提交证据覆盖哪个订单、商品、组件和问题。
3. 客服作出了什么表达，其中哪些构成有效服务承诺。
4. 当前责任方、执行方和下一检查时间是谁。
5. 什么条件才算真正解决。
6. 下一动作中有哪些行为应被禁止。

代码中的 `AccountabilityState` 只是账本在某一时点的快照，不作为第二套产品概念。v1.1 起，`CustomerState` 是面向前端和协作链路的扩展视图，核心事实仍来自 Experience Ledger；新增字段为 `Intent / Emotion / Effort / Risk / Decision / Deadline`，不重写 `Evidence / Promise / Firewall / Resolution` 的核心语义。

## 3. 体验防线（Experience Firewall）

体验防线发生在客服发送消息或执行业务动作之前。完整产品覆盖重复解释、重复索证、责任倒流、无依据新承诺、承诺冲突、假性结案和高风险人工复核。

Competition MVP 重点运行 `E1 / E2 / H1`：相同范围有效证据被再次索取时阻止，范围变化时放行，证据无法可靠判断时进入人工复核。

## 4. 下一解决路径

系统不能只说“不能重新要照片”，还必须给出下一步：

- 查询现有换货与补发状态。
- 生成基于责任事实的消费者回复草稿。
- 预填仓库催办或升级任务。
- 标明责任方、执行方、期限和完成条件。
- 对需要审批的动作提供人工确认入口。

## 5. 责任闭环（Responsibility Loop）

人工批准后，有效承诺进入持续运行状态。系统按下一检查时间读取工单或物流事件，区分尚未到期、已经揽收、尚未揽收和承诺超时，并生成不同动作。消费者离开聊天窗口不结束责任。

## 6. 流程风险发现

完整产品会把个体案例中的体验断层聚合成待调查流程风险。比赛阶段不建设复杂管理驾驶舱，只展示：

- 五类工单状态和未完结数量等赛事数据可直接支持的统计。
- 基于人工标注压力测试案例形成的流程假设，并清楚标记为测试结论。

不从赛事 Mock 数据推导真实市场发生率，也不宣称发现欧莱雅真实流程缺陷。

## 服务进度回执

服务进度回执是体验责任账本的消费者可见视图，不是法律凭证，也不是额外要求消费者管理的新页面。消费者只看到：

- 品牌已经收到什么。
- 现在正在做什么。
- 最迟何时更新。
- 如果未按时完成，品牌将如何主动处理。
- 消费者现在是否还需要操作。

内部责任人、情绪标签、风险分数和 Agent 推理过程不会展示给消费者。

## 美妆业务边界

英雄场景以粉底液泵头损坏为核心，区分正装与赠品、商品与包装、泵头与瓶身、证据整体图与问题细节图，并判断是否影响产品完整性和卫生使用风险。批次号只在数据真实提供或图片可见时记录，不为破损换货案例虚构批次风险。

不良反应场景只进入信息收集、风险升级和人工转交，不自动诊断医疗因果或承诺赔付。

## 三层边界

| 层级 | 内容 | 实现原则 |
|---|---|---|
| 完整产品蓝图 | 账本、防线、解决路径、责任闭环、流程风险 | 不收缩 |
| Competition MVP | 在 `S00001` 破损换货原型上跑通完整责任链 | 纵向切薄 |
| 4 分钟 Demo | 拦截、承诺生效、回执生成、物流分支、主动补救 | 高度聚焦 |

范围变化与图片模糊案例进入 Challenge Mode；其他四类工单只做读取和统一展示，不在本次比赛中实现完整写入链路。

## 正式表达边界

对外使用“服务责任、待履行承诺、服务进度回执”，不使用“服务合约、强制履约、法律凭证、品牌欠款”。所有退款、赔偿、不良反应和高风险动作均保留人工确认。

## 设计冻结

本蓝图自 v0.7 起冻结。后续只补真实运行证据、调研结果和评测结果；新场景、新页面和企业级能力进入路线图。
