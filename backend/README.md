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

运行验证：

```powershell
python -m pytest backend/tests -q
```
