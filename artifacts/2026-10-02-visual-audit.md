# Covenia 视觉自检 · 2026-10-02

范围：千牛风格演示工作台中的 Covenia 插件。核对桌面 1440px、双栏 1024px、移动 390px 和窄屏 320px；截图见 `2026-10-02-final-desktop.png`、`2026-10-02-final-mobile.png` 和 `2026-10-02-atelier-v2-320.png`。

| 维度 | 发现与本轮处理 | 复核 |
|---|---|---|
| 排版 | 原正文多处只有 10–11px；提高聊天、历史、主动作和事实文字，保留三级信息权重。 | 桌面与移动截图中主问题、动作、依据可按顺序读出。 |
| 留白 | 去掉右栏相邻三张浅色小卡；证据集中成一个重点区域，负责人和更新时间改为两列简洁文字。 | 右栏不再由同权重卡片堆叠。 |
| 视觉层级 | 服务队列 → 当前动作 → 已有证据 → 责任与更新时间 → 判断详情。主动作是唯一深色按钮。 | 1440px 与 390px 首屏均可见当前动作。 |
| 色彩 | 工作台维持实用蓝；插件用暖白、深梅色和少量陶土色，状态颜色仍按业务语义使用。 | 品牌色不与工作台蓝混淆。 |
| 动效 | 案例动作切换使用短距离渐入；列表和详情短暂展开；尊重 `prefers-reduced-motion`。 | 无循环装饰性动效。 |
| 微交互 | 按钮有悬停、按下、焦点与禁用反馈；队列选择后收起，详情可展开。 | 浏览器实际点击队列切换至人工复核案例，动作随之切换；详情展开成功。 |
| 响应式 | 1050px 以下转横向会话列与双栏；840px 以下转纵向工作流。 | 1440/1024/768/390/320px 未见页面级横向溢出。 |
| 原创性 | Covenia 使用专门生成的双弧连续服务标识；主要视觉意象是服务记录、承诺与交接，而非通用 AI 光效。 | 标识在 42px 标题栏中仍有清晰轮廓。 |

已通过 `npm run build`（Vite 6.4.3，1586 个模块）与 `git diff --check`。本次是视觉与局部交互复核；完整业务自动化测试和独立产品验收另行进行。千牛图形仍是演示用自绘标识，不代表官方授权或真实千牛接入。

生成资产：`frontend/public/brand/covenia-continuity-mark-v3.png`。使用内置 `image_gen`，模式为新图生成、透明背景，无参考图。最终提示词：

> Use case: logo-brand. Design a single original icon for Covenia, a refined beauty retail service continuity tool. The icon is a small luxury-house-quality abstract mark: two carefully balanced concentric crescent strokes, an outer deep aubergine arc and an inner muted copper arc, both opening at the upper right, with their endpoints staggered to suggest a service promise carried forward. Geometric precision, graceful curves, consistent visual weight, unmistakable open negative space. At a 32px header size it must remain clean and legible, neither an eye nor a letter C. Flat solid vector-style color only: aubergine #3A2530 and copper #B87960. Centered, fills about 76% of the square canvas. Transparent alpha background. No text, no wordmark, no gradients, shading, texture, shadow, 3D, sparkle, chat icon, infinity sign, robot, or mockup.
