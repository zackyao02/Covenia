# 演示案例资产说明

`demo-cases.json` 以赛事会话 `S00001` 为原型，但所有扩充内容都带来源标记。运行输入不包含承诺有效性、证据最终状态、责任方或体验防线结果。

赛事工作簿只提供 `mock_images/broken_pump/S00001_03.jpg` 路径引用，没有附带图片文件。正式 Demo 需要团队自制或合成以下素材：

- `s00001-product-overview.jpg`
- `s00001-pump-detail.jpg`
- `s00001-package-context.jpg`
- `s00001-gift-evidence.jpg`
- `s00001-blurred-pump.jpg`

前三张用于英雄场景；赠品图用于范围变化放行；模糊图用于人工复核。图片不得包含真实消费者身份信息。

`ground-truth.json` 只用于运行完成后的评测，不得传入模型、状态构建器或体验防线。

`synthetic-pattern-card.json` 同时区分两类内容：赛事数据能够直接支持的工单状态统计，以及人工标注压力测试形成的流程假设。后者不代表真实业务发现。
