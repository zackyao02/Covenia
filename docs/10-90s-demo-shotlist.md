# Covenia 90 秒 Demo 镜头脚本

目标：不要做功能导览，而是做一部 90 秒小电影。让观众记住三个概念：

1. Don’t Ask Again：已经告诉企业的信息，不应该再让消费者重复。
2. Don’t Wait for Anger：不等投诉发生，提前识别服务正在恶化。
3. Don’t Forget a Promise：聊天结束以后，企业的责任没有结束。

推荐主线：

```text
多源数据
  ↓
Customer State
  ↓
Understand
  ↓
Anticipate
  ↓
Act
  ↓
Promise
  ↓
Ensure
```

## 0–10 秒：痛点开场

### 画面

千牛模拟工作台。消费者第三次进线：

```text
这已经是第三次问了。我前面图也发了，订单也给了，别再让我重新拍照了。
换货到底发没发？
```

普通 AI 准备回复：

```text
麻烦您重新上传一下故障照片，我们为您核实。
```

### 旁白

“传统 AI 客服经常只看当前这一轮对话，所以会重复索要消费者已经提供过的信息。”

### 要点

不要先展示 Dashboard。先让观众看到一个真实、讨厌、容易共鸣的错误。

## 10–22 秒：Covenia 阻止错误动作

### 画面

发送前，Covenia 右侧插件弹出：

```text
⚠️ Intervened

用户已于 2026-05-05 09:21 提供：
✓ 商品整体图
✓ 泵头细节图
✓ 包裹上下文图

建议：不要再次索取相同证据。
```

自动改写回复：

```text
我看到您之前已经提交过故障照片和订单信息，不需要重新提供。
我现在直接帮您核查换货发出进度。
```

### 旁白

“Covenia 的共情不是更会道歉，而是阻止一次糟糕的服务体验。”

### 记忆点

**Don’t Ask Again**

## 22–35 秒：Customer State 解释“为什么她不满”

### 画面

切到 Customer State Focus View：

```text
Why is she frustrated?

① Promise at risk
   48h 换货承诺即将/已经失约

② Repeated contact
   同一问题第 3 次联系

③ Repeated evidence risk
   已提交图片，不应重复索要

Consumer Effort: HIGH
```

JEV 作为二级解释出现：

```text
JEV Advisory
Emotion worsening: 0.84
Need human: 0.71
Model: jev-latest
Fallback: available
Audit: logged
```

### 旁白

“Covenia 不只是识别 Angry，而是解释为什么服务体验正在恶化。”

### 关键句

```text
产品问题让她第一次来，服务问题让她第三次来。
```

## 35–48 秒：时间快进，Risk / Priority 自动变化

### 画面

点击：

```text
Demo Time +48h
```

时间线快进：

```text
T1  Risk 31  Promise active
T2  Risk 48  Promise 还有 1h
T3  Risk 67  Promise 还有 10min
T4  Risk 87  Promise overdue
```

Priority Queue 动画：

```text
王女士
#3 → #1
```

原因：

```text
Moved to #1
✓ Promise overdue
✓ Third contact
✓ Emotion worsening
✓ No resolution yet
```

### 旁白

“Covenia 不等投诉发生，它发现一个消费者正在变成投诉。”

### 记忆点

**Don’t Wait for Anger**

## 48–60 秒：Next Best Action

### 画面

插件展示：

```text
Next Best Action

CHECK_REPLACEMENT
Model support: 87%

Why?
✓ Promise overdue
✓ Evidence already provided
✓ Existing replacement ticket
✓ Consumer action not required
```

点击执行：

```text
查询换货进度
```

### 旁白

“JEV 给出概率化建议，但最终动作仍经过规则、阈值和 fallback 治理。”

### 注意

不要把 JEV 当主角。默认只展示行动建议，点击 Why 再展示模型治理。

## 60–70 秒：人工确认 + 服务回执

### 画面

人工确认解决路径：

```text
Approve Resolution

Executor: Warehouse
Next update by: 10:30
Consumer action required: No
```

生成服务回执：

```text
我们已收到您之前提交的材料，不需要您再次补充。
当前正在核实换货件是否已由物流揽收。
我们会在 10:30 前主动更新。
```

### 旁白

“一旦客服确认，承诺就变成可追踪的服务责任。”

## 70–78 秒：物流异常触发恢复动作

### 画面

模拟物流事件：

```text
SHIPMENT_NOT_PICKED_UP
```

状态变化：

```text
Case Status: AT_RISK
Obligation: AT_RISK
Follow-up: HIGH
Supervisor Escalation: HIGH
```

消费者侧文案：

```text
您的换货件尚未完成物流揽收，我们已向仓库加急催办。
您无需再次提供材料，我们会在今天 12:00 前主动更新。
```

### 旁白

“企业承诺没有做到时，Covenia 不只是亮红灯，而是生成恢复动作。”

### 记忆点

**Don’t Forget a Promise**

## 78–84 秒：Zero-Repetition Handoff

### 画面

点击：

```text
Transfer to Human
```

出现 Human Handoff Package：

```text
What happened
粉底液泵头故障，已登记换货。

Already provided
✓ 订单信息
✓ 商品整体图
✓ 泵头细节图
✓ 包裹上下文图

Current request
核查换货是否发出。

DON'T ASK AGAIN
~~订单号~~
~~故障照片~~
~~重新描述问题~~

NEXT ACTION
Check replacement / Warehouse follow-up
```

真人客服第一句话：

```text
我看到您之前已经提交过照片并完成核实，不需要重新说明。
我直接帮您跟进换货发出情况。
```

### 旁白

“人工接手时，不应该让消费者从头再来。”

## 84–90 秒：最终收束

### 画面

物流恢复并送达：

```text
SHIPMENT_PICKED_UP
  ↓
IN_FULFILLMENT

SHIPMENT_DELIVERED
  ↓
RESOLVED
```

最后一屏：

```text
From one frustrated customer
to a service responsibility the company can keep.
```

或中文：

```text
从一次愤怒咨询，
到一个被企业持续履行的服务承诺。
```

### 旁白

“Covenia 不只是让 AI 更懂消费者，而是让企业记住消费者经历过什么，在风险升级前行动，并对自己说过的话负责。”

## 可选 Bonus：最后 5 秒 Zoom Out

如果时间允许，在 90 秒后追加一个 Bonus 镜头：

```text
Is this just one customer?
```

画面 zoom out：

```text
Emerging Issue

Same SKU / Same batch
27 similar cases
Possible pump failure cluster
Requires human confirmation
Prediction: false
```

用途：

把单用户共情升级成企业洞察：

```text
不是 27 个难缠消费者，
而是一个可能的产品 / 批次 / 履约问题。
```

## Demo 所需数据对照

| 镜头 | 当前 Hero data 是否支持 | 还需补充 |
|---|---|---|
| 重复索证被拦截 | 已支持 | 无 |
| Customer State + Why frustrated | 部分支持 | `why_frustrated` 展示文案 |
| JEV Advisory | 已支持 | 无 |
| 时间快进 | 已支持 | 已补 `demo_time_slices`，可展示 T0 → T4 |
| Priority #3 → #1 | 已支持 | 已补 `priority_queue_context` |
| 服务回执 | 已支持 | 无 |
| 物流异常升级 | 已支持 | 无 |
| Zero-Repetition Handoff | 已支持 | 已补 `human_handoff_package` |
| Consumer Recovery | 已支持 | 已补 `consumer_recovery_options` |
| Emerging Issue Zoom Out | 已支持 | 已补 `emerging_issue_cluster` |

新增 6 项 demo 证据均位于：

```text
data/designed_cases/covenia_effectiveness_hero_case.json
  → demo_evidence_pack
```

它们的镜头作用：

1. `without_covenia_replay`：先展示没有 Covenia 时的错误路径，让产品价值更容易被看见。
2. `demo_time_slices`：支撑时间快进，展示风险不是静态标签，而是随承诺和物流状态变化。
3. `priority_queue_context`：支撑 Hero Case 从 #3 升到 #1，说明系统改变企业处理顺序。
4. `human_handoff_package`：支撑人工接手不重复询问，体现 Zero-Repetition Handoff。
5. `consumer_recovery_options`：支撑承诺失约后的补救选择，不把责任推回消费者。
6. `emerging_issue_cluster`：支撑最后 5 秒 Zoom Out，但明确只是候选问题，需要人工确认。

## 一句话版本

如果只能讲一句：

```text
Covenia lets the company remember what the customer already did,
act before the service breaks,
and keep track of every promise until resolution.
```

中文：

```text
Covenia 让企业记住消费者已经做过什么，在服务恶化前行动，并追踪每个承诺直到真正解决。
```
