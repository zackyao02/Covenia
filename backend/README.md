# Covenia B 线本地服务

该服务实现冻结范围内的四个接口，供千牛右侧插件使用：

```powershell
cd frontend
npm run dev -- --host 127.0.0.1
```

另开一个终端：

```powershell
cd backend
python -m uvicorn backend.main:app --app-dir .. --host 127.0.0.1 --port 8000
```

在 `frontend/.env.local` 写入：

```dotenv
VITE_API_MODE=http
VITE_API_BASE_URL=http://127.0.0.1:8000
```

服务使用 `fixtures/demo-cases.json` 装载案例事实；评估函数不按案例编号返回固定结论。当前图文抽取为赛事本地演示的可复现实例提取器；手机号、收货地址、账号与不良反应文本会在进入抽取器前计数并以 `pii_masked_count` 记入服务端治理日志。尚未配置外部 Qwen 推理服务或真实消费者数据。

## TypeSafe / JEV Decision Layer

BC Core 接口不直接依赖 JEV。新增的 `backend/decision/` 只作为 Decision Layer：

- `jev_client.py`：读取环境变量，负责和 TypeSafe/JEV 通信。
- `questions.py`：统一维护 Covenia 自己的 typed-choice questions。
- `engine.py`：组合确定性规则、JEV 软信号、threshold、fallback 与 audit log。
- `policy.py`：集中维护阈值与降级策略。

本地真实接入时，在仓库根目录复制 `.env.example` 为 `.env`，或直接在终端导出：

```dotenv
TYPESAFE_API_KEY=你的真实key
TYPESAFE_API_URL=https://api.typesafe.ai/v1/systemone
TYPESAFE_MODEL_VERSION=jev-latest
TYPESAFE_TIMEOUT_SECONDS=10
```

`.env` 已加入 `.gitignore`，不要把真实 key 提交到 GitHub。未配置 key、TypeSafe 超时或返回异常时，接口会继续返回规则降级结果：`decision_advisory.status = "FALLBACK"`，不会阻断客服工作台。

2026-10-02 更新：JEV 输入先对手机号、账号、明确标记的地址和健康描述脱敏，治理审计记录 `pii_masked_count`；此掩码尚需真实数据验证覆盖率。只有符合官方 Noul/Choice 响应形状的结果才标记 `READY`。降级时情绪趋势为 `UNKNOWN`、概率为 `null`，规则建议不带虚构的模型概率。阈值尚未经业务数据校准。缓存包含消息内容与问题版本，成功结果保留五分钟，失败结果十五秒后可重试。

发送检查支持可选 `draft_reply`；仅明确的进度回复可直接在本地记录，索证/结案继续受规则控制，新承诺及未知文本需要人工确认。当前识别器是保守关键词规则，未实现通用语义识别。人工修改的 `consumer_reply`、`executor`、`next_check_at` 写入批准结果、服务回执和审计；人工确认不能绕过硬规则。切换已有案件会保留其服务状态；状态仍在进程内保存，重启后不保留。

运行验证：

```powershell
python -m pytest backend/tests -q
```

## 本地模拟时间扩展（2026-10-05）

`POST /api/demo/clock/advance` 接受 `{case_id, step: "NEAR_DUE" | "OVERDUE", idempotency_key}`。仅允许尚未揽收、已人工批准的换货义务，分别推进至原截止前 10 分钟或之后 1 分钟。返回统一响应外壳下的 `service_clock`、责任、Customer State、期限、优先队列、跟进/升级候选与待确认通知。

重置案例会清除模拟时钟和对应幂等记录；倒退、越级或时序矛盾会拒绝。通知更新时间、回执和义务同步，重复逾期检查不重复生成升级。此接口是手动模拟检查，不是生产定时调度或真实仓库任务。

扩展返回契约见 `schemas/demo-clock-advance-response.schema.json` 与 `schemas/demo-accountability-state.schema.json`。冻结的基础责任 Schema 保持原样；不要用它校验新增的本地模拟审计事件。
