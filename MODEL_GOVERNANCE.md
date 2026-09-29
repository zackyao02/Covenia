# Covenia 模型、算力与许可证治理

## P0 模型

- 默认模型：`Qwen/Qwen2-VL-2B-Instruct`。
- 用途：聊天旅程、图片证据、承诺、体验成因和潜在需求的统一结构化抽取。
- 官方模型页：https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct
- 许可证：Apache-2.0。
- 推理方式：阿里云算力部署、本地 Transformers，或团队控制的兼容推理服务。

阿里云学生资源补贴用于算力和 AI 服务，不描述为无限免费 API。团队最终只登记实际使用的模型、区域、版本和费用来源。

## Provider 边界

业务系统只依赖统一 `ModelProvider` 与 `ExtractedJourney` Schema。云端与本地可以切换，但正式演示不同时编排多个模型，也不依赖随机免费路由。

## 输出边界

模型可以输出：

- 商品与组件观察、图片可读性和证据覆盖。
- 消费者意图、体验表达、服务成因和潜在需求。
- 承诺原文、时间、条件、承诺类型建议和来源。

模型不得直接输出：

- 最终证据有效性。
- 当前责任方或最终服务责任。
- 是否退款、赔偿、补发或医疗处置。
- 体验防线最终决策。

## JEV Governance

Jev 只能用于“有限选项空间中的模糊判断”，不能替代规则、人工确认或业务系统事实。

核心原则：

> Rule 处理确定事实，Jev 处理有限空间中的模糊判断，LLM 负责理解和语言生成。

### 可交给 Jev 的判断

- 图片或聊天证据的有限分类候选，例如 `readability: HIGH / LOW / UNKNOWN`。
- 情绪趋势候选，例如 `STABLE / WORSENING / IMPROVING / UNKNOWN`。
- 证据是否需要人工复核的软信号。
- Emerging Issue 的人工确认前候选排序。

### 不可交给 Jev 的判断

- 最终业务责任方。
- 是否退款、赔付、补发、关闭工单。
- Deadline 是否超时。
- 物流是否揽收或送达。
- 体验防线最终 `INTERVENE / ALLOW / HUMAN_REVIEW`。

### Typed choices

所有 Jev 输出必须是 typed choices，不接受自由文本结论：

```json
{
  "choice": "NEED_HUMAN_REVIEW",
  "allowed_choices": ["VALID", "MISMATCHED", "NEED_HUMAN_REVIEW"],
  "probability": 0.72,
  "confidence": "MEDIUM",
  "threshold": 0.8,
  "fallback": "HUMAN_REVIEW"
}
```

### Probability、threshold 与 fallback

- `probability` 低于阈值时，一律走 `fallback`。
- `confidence` 只能用于解释和调试，不能单独驱动业务动作。
- 高风险场景默认阈值更高；不良反应、赔付、退款和关单必须人工确认。
- Jev 不可用、输出非法或超时时，回退到规则或人工复核。

### Human Review 与 audit log

Jev 每次调用必须记录：

- 输入来源 ID，不记录未脱敏原文。
- allowed choices、choice、probability、threshold、fallback。
- 是否被规则采纳。
- 最终人工确认结果。
- request_id、模型版本、prompt/version 或评估器版本。

人工覆盖 Jev 后，人工事实优先级高于 Jev 输出；后续状态重算以人工事实为准。

## 数据边界

- 赛事 Excel 是官方提供的全量 Mock 数据。
- 工作簿中的 `image_path` 仅为引用，未提供实际图片文件。
- 多模态 Demo 使用团队自制或合成图片，并与赛事原始记录分别标记。
- 真实访谈、问卷和聊天案例必须匿名化。
- 手机号、收货地址、支付宝账号、就医与不良反应描述先进行字段级掩码；掩码命中数写入每次调用的治理记录。原始敏感字段默认不进入模型。确需保留语义时，只发送最小化的脱敏占位表达，且限制访问。
- 数据不得用于训练通用模型，除非获得单独授权。

## 提交前登记

- 模型精确版本或提交哈希。
- Transformers、PyTorch 与图像依赖版本。
- 运行设备、阿里云产品与区域。
- Prompt 版本。
- 数据来源标签。
- 30 个标注案例、错误案例和人工覆盖记录。

## 灾备

缓存抽取结果只用于模型失败时的演示灾备。响应中的 `model_metadata.cached_result`、界面的“缓存抽取结果”角标和治理记录必须同时出现；缺任一项即视为失败。至少一个主演示案例必须完成真实图文推理。
