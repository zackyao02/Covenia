# 09｜可运行前后端

## 目标

本实现把 V1.1 报告中的比赛 P0 落为两个页面：

- `Covenia Copilot`：面向一线客服，展示 Consumer Story、Emotion Journey、Customer Effort、已知事实、Don't Ask Again、Next Best Action、基于状态的共情回复和 Promise-to-Action。
- `Covenia Risk Radar`：面向主管与运营，展示风险排序、可解释 Risk Factors、Journey Timeline 和闭环状态。

实现读取 `fixtures/demo-cases.json`，不把模拟数据表述为生产数据或真实市场发生率。

## 启动

要求 Node.js 20 或更高版本，无第三方依赖。

```bash
npm start
```

打开 `http://127.0.0.1:4173`。

默认只监听本机回环地址。需要在受控局域网内让其他设备访问时，可显式运行：

```bash
HOST=0.0.0.0 PORT=4173 npm start
```

然后在另一台设备打开 `http://<运行服务的设备IP>:4173`。当前 Demo 没有登录、HTTPS 或访问控制，不应把该端口直接暴露到公网。远程服务器验收优先使用 SSH 端口转发，完整步骤见 `docs/12-remote-acceptance-guide.md`。

运行测试：

```bash
npm test
```

## 接口

保留原有四个核心接口：

- `POST /api/cases/analyze`
- `POST /api/actions/evaluate`
- `POST /api/resolutions/approve`
- `POST /api/events/shipment`

比赛 V1.1 增加一个只读接口：

- `GET /api/risk/cases`
- `GET /api/emerging-issues`
- `GET /api/monitor/deadlines`
- `POST /api/monitor/deadlines/run`

另有 `GET /api/health` 用于运行状态检查。

## 实现边界

- Emotion、Effort 与 Risk 使用可解释的确定性演示规则，结果附原因和证据；权重属于比赛假设，需要真实数据校准。
- Emotion 明确区分原文依据与系统推断，只辅助客服表达；不进入 Risk Score，不覆盖体验防线。详见 `docs/10-emotion-evidence-and-action-boundary.md`。
- 数据状态存于进程内存，服务重启后恢复到 fixture 初始状态。
- 不自动退款、赔付、补发或认定责任；需要审批的动作保留人工确认。
- 不接入千牛、CRM、仓库或物流生产系统；页面为真实接口驱动的比赛演示壳。
- 模型调用暂由 `DETERMINISTIC_DEMO_ENGINE` 代替，接口保留 `model_metadata`，后续可接入受治理的模型 Provider。
- P1 Journey Timeline、Multi-source Fusion、Deadline Monitor 与 Emerging Issue 的设计和验收见 `docs/11-p1-continuity-intelligence.md`。
