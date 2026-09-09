# Covenia 千牛右侧插件

Competition MVP 的 C 端实现。页面模拟千牛三栏工作台，重点交付 360–420px 的右侧消费者体验责任插件。

## 本地运行

```bash
npm install
npm run dev
```

打开 `http://127.0.0.1:4173/`。

验证命令：

```bash
npm test
npm run build
```

## 可演示流程

### 主案例 S00001

1. 客服准备再次索取粉底液泵头图片。
2. 点击发送，调用动作评估并得到 `INTERVENE`。
3. 查询补发进度或生成解决回复。
4. 人工确认责任方、执行方、截止时间和消费者回复。
5. 确认后创建服务责任、倒计时和服务进度回执。
6. 推送“已揽收”、“仍未揽收”和“已送达”事件，观察责任升级及闭环。

### Challenge Case

- 赠品图片与正装泵头不匹配：`ALLOW`，只请求当前范围缺失证据。
- 同一商品图片模糊：`HUMAN_REVIEW`，创建人工证据复核，不直接重复索证。

## 接口模式

默认使用 `mock`：

```env
VITE_API_MODE=mock
```

接入 B 端时复制 `.env.example` 为 `.env.local`，设置：

```env
VITE_API_MODE=http
VITE_API_BASE_URL=http://127.0.0.1:8000
```

页面统一调用 `src/api/client.ts`，组件不直接依赖 Mock。改变责任状态的人工确认和物流事件会按 v0.8 契约在请求体携带 `idempotency_key`。

四个端点均使用 `{ data, error, request_id }` 响应外壳。正常案例只传 `case_id`；两个压力测试变体显式使用 `challenge_mode` 与受限 `challenge_overrides`，右栏同步显示 `Challenge Mode`。

## 加载与错误演示

点击右侧插件标题栏的更多按钮，可以切换：

- 正常响应
- 慢响应
- 缓存结果
- 模型超时
- 状态冲突

这些选项只影响本地 Mock，不属于正式接口字段。

## 图片素材

正式图片放入 `public/evidence/`：

- `s00001-product-overview.jpg`
- `s00001-pump-detail.jpg`
- `s00001-package-context.jpg`
- `s00001-gift-evidence.jpg`
- `s00001-blurred-pump.jpg`

图片到位前，页面使用不包含真实身份信息的视觉占位图。

## 基础视觉规范

- 工作台目标分辨率：1366×768。
- 右侧插件宽度：404px，允许范围 360–420px。
- 第一屏只回答“已经知道什么、现在不能做什么、下一步做什么”。
- 主色：`#5549CA`；正文：`#182230`；次要文字：`#667085`。
- 拦截：图标＋`INTERVENE`＋中文原因，使用 `#B42318`。
- 放行：图标＋`ALLOW`＋中文原因，使用 `#067647`。
- 人工复核：图标＋`HUMAN_REVIEW`＋中文原因，使用 `#B54708`。
- 颜色不作为唯一状态表达。
- 主操作使用实心按钮；次操作使用描边按钮；催办只在满足条件时出现。
- 服务回执不展示内部姓名、置信度、情绪标签或规则推理。
- “模拟数据”标识固定出现在插件标题栏，不重复打断操作。

## 等待 B 端确认

- `ApiResult` 响应外壳和 HTTP 状态码。
- 人工修改字段及批准后的责任状态。
- 物流催办候选和主管升级候选结构。
- `CHECK_REPLACEMENT_PROGRESS` 是否在动作评估接口内执行查询。
- 模型超时、缓存结果和状态冲突的真实返回方式。
