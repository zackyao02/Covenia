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

另有 `GET /api/health` 用于运行状态检查。

## 实现边界

- Emotion、Effort 与 Risk 使用可解释的确定性演示规则，结果附原因和证据；权重属于比赛假设，需要真实数据校准。
- 数据状态存于进程内存，服务重启后恢复到 fixture 初始状态。
- 不自动退款、赔付、补发或认定责任；需要审批的动作保留人工确认。
- 不接入千牛、CRM、仓库或物流生产系统；页面为真实接口驱动的比赛演示壳。
- 模型调用暂由 `DETERMINISTIC_DEMO_ENGINE` 代替，接口保留 `model_metadata`，后续可接入受治理的模型 Provider。
