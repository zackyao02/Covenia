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
TYPESAFE_MODEL_VERSION=systemone
TYPESAFE_TIMEOUT_SECONDS=10
```

`.env` 已加入 `.gitignore`，不要把真实 key 提交到 GitHub。未配置 key、TypeSafe 超时或返回异常时，接口会继续返回规则降级结果：`decision_advisory.status = "FALLBACK"`，不会阻断客服工作台。

运行验证：

```powershell
python -m pytest backend/tests -q
```
