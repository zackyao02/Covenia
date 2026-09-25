# 12｜远端打开与逐项验收指南

## 1. 推荐打开方式：远端服务器 + SSH 安全转发

当前 Demo 没有登录、HTTPS、限流和生产数据隔离。推荐让服务继续监听远端服务器的 `127.0.0.1`，通过 SSH 转发访问，不直接开放公网端口。

### 1.1 上传当前本地代码

因为本次改动没有推送 GitHub，可在本机终端执行：

```bash
rsync -az --exclude node_modules --exclude .git \
  '/Users/zly/Desktop/哦来源/2026-09-20/referenced-chatgpt-conversation-this-is-an/work/Covenia/' \
  <用户名>@<服务器地址>:~/covenia/
```

将 `<用户名>` 和 `<服务器地址>` 替换成实际值。

### 1.2 在远端服务器启动

```bash
ssh <用户名>@<服务器地址>
cd ~/covenia
node --version
npm test
npm start
```

期望：

- Node.js 为 20 或更高版本。
- 自动化测试显示 `12` 项通过、`0` 项失败。
- 服务输出 `Covenia is running at http://127.0.0.1:4173`。

保持这个终端运行。

### 1.3 在本机建立 SSH 转发

新开一个本机终端：

```bash
ssh -N -L 4173:127.0.0.1:4173 <用户名>@<服务器地址>
```

保持该终端运行，然后在本机浏览器打开：

```text
http://127.0.0.1:4173
```

打开以下地址做健康检查：

```text
http://127.0.0.1:4173/api/health
```

期望：HTTP 200，返回内容中有 `status: "ok"` 和 `service: "covenia-v1.1"`。

如果本机 4173 已被占用，可把转发命令左侧端口改成 5173：

```bash
ssh -N -L 5173:127.0.0.1:4173 <用户名>@<服务器地址>
```

浏览器相应打开 `http://127.0.0.1:5173`。

## 2. 受控局域网打开方式

如果两台设备在同一受信任局域网，可在运行服务的设备上执行：

```bash
HOST=0.0.0.0 PORT=4173 npm start
```

查询该设备局域网 IP 后，在另一台设备打开：

```text
http://<局域网IP>:4173
```

期望：首页正常加载，右上角显示“服务在线”。如果无法访问，检查系统防火墙是否仅对受信任局域网开放 TCP 4173。

不要在没有反向代理、HTTPS、认证和来源限制时把 4173 直接暴露到公网。

## 3. 测试前准备与重置

- 使用最新版 Chrome、Edge 或 Safari。
- 首次测试选择 `DEMO_001`。
- 页面数据为赛事 Mock 数据，不代表生产事实。
- 状态保存在服务进程内存中。需要恢复初始状态时，在服务器终端按 `Ctrl+C` 停止，再运行 `npm start`。
- “复制回复”依赖浏览器剪贴板权限；通过 SSH 转发的 localhost 地址更容易正常工作。

## 4. P0 功能验收

### P0-1 Customer State

操作：

1. 打开首页，停留在 `Covenia Copilot`。
2. 在右上案例下拉框选择 `DEMO_001`。
3. 查看 Consumer Story、已经知道什么、Emotion Journey、Customer Effort 和 Promise。

期望结果：

- 页面恢复当前诉求和最新消息。
- “已经知道什么”显示订单、商品、图片或工单等事实，并注明来源可追溯。
- 页面同时显示 Emotion、Effort 和 Promise 状态。
- Risk 分数可见，但情绪不直接构成 Risk 加分项。

### P0-2 Emotion Journey

操作：

1. 查看顶部 `Emotion Journey`。
2. 查看“情绪判断依据与使用边界”。
3. 对照每条原文、来源编号、时间、观察线索、推断标签和置信度。

期望结果：

- 情绪以旅程形式展示，而不是单个 sentiment 标签。
- 每项判断都能回到具体对话或事件。
- 推断内容明确标记为“推断”。
- 页面明确说明情绪只辅助沟通，不参与 Risk Score、不覆盖现有规则。

### P0-3 Consumer Effort

操作：查看 `Customer Effort` 卡片及 Risk Radar 中对应案例的风险原因。

期望结果：

- 显示 Effort 等级、分数、联系次数和等待时间。
- 重复解释、重复举证或多次联系能够作为可解释的服务成本展示。

### P0-4 Next Best Action 与体验防线

操作：

1. 查看“下一步直接做什么”。
2. 点击“验证动作”。

期望结果：

- 页面显示建议动作及理由。
- Demo 准备的重复索要材料动作被拦截。
- 提示信息包含 `INTERVENE` 和规则 `P0_PROHIBITED_ACTION`。
- 情绪推断不会越过该规则。

### P0-5 Handoff Package

操作：展开 `AI → 人工 Handoff Package`。

期望结果：

- 至少显示当前诉求、已知事实、已尝试动作、Emotion、Effort、Promise、不要再问和建议动作。
- 人工客服无需重新阅读全部历史或再次索要已经存在的材料。

### P0-6 Context-grounded Empathy Reply

操作：

1. 阅读“基于状态的共情回复”。
2. 点击“复制回复”。

期望结果：

- 回复引用当前案件的真实状态和下一步动作，不承诺系统未批准的结果。
- 获得剪贴板权限时显示“回复已复制”。
- 若公网 HTTP 环境下复制失败，改用 SSH 转发的 localhost 地址测试。

### P0-7 Explainable Risk Score

操作：

1. 切换到 `Risk Radar`。
2. 点击 `DEMO_001` 风险行。
3. 查看右侧 `WHY THIS RISK`。

期望结果：

- 显示 Risk 分数、等级、每个风险因素、权重和证据。
- 页面显示“情绪仅作为沟通上下文，不参与风险分数”的说明。
- Risk 被表述为运营分流指标，而不是投诉、流失或个人风险预测。

### P0-8 Risk Dashboard

操作：

1. 查看 Risk Radar 表格。
2. 逐行点击不同案例。
3. 点击“刷新风险状态”。

期望结果：

- 案例按风险分数从高到低排列。
- 顶部显示案件数、Critical、承诺超时、平均 Effort 和 Emerging 数量。
- 右侧随选中案例更新风险原因、时间线和闭环状态。

## 5. P1 功能验收

### P1-1 Journey Timeline

操作：

1. 服务重启恢复初始状态。
2. 打开 Risk Radar，点击 `DEMO_001`。
3. 查看右侧 `Journey Timeline`。

期望结果：

- 时间线显示业务事件、时间、来源类型和来源 ID。
- 初始案件覆盖 `CONVERSATION`、`IMAGE`、`ORDER`、`TICKET`。
- 派生时间不会伪装成原始系统时间。

### P1-2 Multi-source Fusion

操作：

1. 回到 Covenia Copilot。
2. 选择 `DEMO_001`。
3. 查看 `Multi-source Fusion` 卡片。

期望结果：

- 状态为 `COMPLETE · 100%`。
- 显示 Conversation、Image、Order、Ticket 四种来源及各自数量。
- 显示来源间关联关系和 `LINKED` 状态。
- 鼠标停留在来源区域时可查看对应来源 ID。

### P1-3 Promise-to-Action 创建

操作：点击“批准并创建责任”。

期望结果：

- 出现“责任已创建”提示。
- 页面出现 Promise-to-Action 卡片。
- 卡片显示执行方、截止时间、完成条件和 `Deadline Monitor: SCHEDULED`。
- 批准按钮变为不可用，避免重复创建责任。

### P1-4 Promise deadline 自动风险升级

先完成 P1-3，然后在本机另一个终端通过 SSH 转发地址执行：

```bash
curl -sS -X POST http://127.0.0.1:4173/api/monitor/deadlines/run \
  -H 'Content-Type: application/json' \
  -d '{"now":"2099-01-01T00:00:00Z"}'
```

操作：等待页面下一次轮询，最长约 5 秒；也可切到 Risk Radar 后点击“刷新风险状态”。

期望结果：

- 返回中的 `escalated_count` 为 `1`。
- 页面提示 Deadline Monitor 已自动升级风险。
- Monitor 状态变为 `ESCALATED`。
- 案件状态变为 `AT_RISK`，Risk Radar 的“承诺超时”增加。
- 审计时间线增加 `PROMISE_DEADLINE_ESCALATED`。

再次执行同一命令。

期望：`escalated_count` 为 `0`，不会重复升级或重复写入审计事件。

### P1-5 Promise 履约闭环

操作：

1. 重启服务恢复初始状态。
2. 重新选择 `DEMO_001` 并点击“批准并创建责任”。
3. 依次点击“模拟已揽收”和“模拟已送达”。

期望结果：

- 揽收后责任里程碑更新。
- 送达后 Resolution 变为 `RESOLVED`。
- Deadline Monitor 变为 `CLOSED`。
- Risk Radar 的闭环状态同步更新。

补充反向测试：重启后创建责任，不点“模拟已揽收”，直接点“模拟已送达”。期望系统拒绝非法状态跳转并给出错误提示。

### P1-6 Emerging Issue Detection

操作：

1. 打开 Risk Radar。
2. 查看 `Emerging Issue Detection` 面板。
3. 在浏览器打开 `http://127.0.0.1:4173/api/emerging-issues` 查看完整证据。

期望结果：

- 当前测试数据产生 `1` 个候选问题。
- 面板显示 `3` 位独立消费者，而不是简单按消息条数计数。
- 来源覆盖 Conversation、Image、Order、Ticket。
- 状态为 `EMERGING_CANDIDATE`。
- `requires_human_confirmation` 为 `true`，`prediction` 为 `false`。
- 页面明确披露使用团队构建的合成测试数据，不能直接视为产品质量结论。

## 6. API 快速验收

以下命令均在已经建立 SSH 转发的本机终端执行：

```bash
curl -sS http://127.0.0.1:4173/api/health
curl -sS http://127.0.0.1:4173/api/risk/cases
curl -sS http://127.0.0.1:4173/api/emerging-issues
curl -sS http://127.0.0.1:4173/api/monitor/deadlines
curl -sS -X POST http://127.0.0.1:4173/api/cases/analyze \
  -H 'Content-Type: application/json' \
  -d '{"case_id":"DEMO_001"}'
```

期望：所有请求均返回 HTTP 200、`error: null`，并带有唯一 `request_id`。

## 7. 完整验收通过标准

只有同时满足以下条件才视为本轮远端验收通过：

1. `npm test` 为 12/12 通过。
2. 首页和健康检查能通过远端链路访问。
3. P0 八项均符合上述期望结果。
4. Journey Timeline 覆盖四源并保留来源 ID。
5. Multi-source Fusion 为 COMPLETE、100%。
6. Deadline Monitor 能升级一次且保持幂等，履约后能关闭。
7. Emerging Issue 按独立消费者聚合，并明确要求人工确认、非预测、合成数据。
8. 浏览器控制台无未处理错误，页面不存在持续加载或空白状态。
