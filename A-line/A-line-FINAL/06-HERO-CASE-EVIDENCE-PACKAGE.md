# A-06｜英雄案例证据包（DEMO_001 / S00001）

对应任务：`TEAM_AND_TIMELINE.md` 9/12–9/18 A 线交付项「交付英雄案例证据」
机器可校验版本：`06-HERO-CASE-EVIDENCE-PACKAGE.json`
交付日期：2026-09-17
素材交付日期：2026-09-12（团队，位于 B 线 `frontend/public/evidence/`）

> **纯 Ground Truth 提醒**：本包含 `expected_image_observations` 等评测答案，不得传入模型 Prompt、状态构建器或体验防线，不得作为接口请求体。依据 `docs/06-evaluation-and-research.md` 第 6 节。

---

## 1. 这个包解决什么问题

`docs/07-demo-and-delivery.md` 的门 2 要求「至少一个案例从原始聊天和**实际图片文件**生成 `ExtractedJourney`」。赛事工作簿只给了一条 `image_path` 字符串，不含图片文件，所以英雄案例的证据链此前是断的。

团队已于 2026-09-12 交付 5 张团队自制素材。本包做三件事：

1. 把 5 张素材逐张登记为可核验的证据资产（文件名、`evidence_id`、来源消息、来源类型、哈希、尺寸、可测量属性）。
2. 给出英雄案例 `evidence_status = VALID` 的完整推导链，并写明每张图覆盖了哪些证据项。
3. 记录 A 线在做文件级核验时发现的 7 项事实与 6 项待办。

---

## 2. 英雄案例事实（来自赛事数据）

| 项 | 值 |
|---|---|
| 演示案例 | `DEMO_001`（原型会话 `S00001`） |
| 场景 | 补发换货 / 破损换货 |
| 订单 | `6920185815517983396` |
| 正装 | `XC33003` 测试轻透粉底液30ml #N02自然色（`PRIMARY`） |
| 赠品 | `GIFT-B5-MASK-2`（赛事工单口径 `XLG5004`）测试B5面膜体验装2片 |
| 换货工单 | `BH919209358357`，状态「进行中」，补发物流单号 `YT7667875838478` |
| 当前问题 | `PACKAGE_DAMAGE`，`affected_component = PUMP` |
| 承诺 | 「换货单已创建，48小时内发出」`STANDARD_APPROVED` / `ACTIVE`，截止 `2026-05-07T10:27:37+08:00` |

赠品两种代号指向同一商品，对照关系见 `02-DATA-MAPPING-TABLE.md` 第 5.1.1 节。

---

## 3. 证据资产登记

### 3.1 团队交付的 5 张素材

| # | 文件名 | `evidence_id` | 用于 | 声明视图类型 | 来源类型 | 来源消息可回溯 | 尺寸 | 字节 | 清晰度 | sha256（前 16 位） |
|---|---|---|---|---|---|---|---|---:|---:|---:|---|
| EV-01 | `s00001-product-overview.jpg` | `S00001_IMG_OVERVIEW` | DEMO_001 | `PRODUCT_OVERVIEW` | `TEAM_SYNTHETIC_RECREATION` | ✅ `80525870445254.PNM` | 1254×1254 | 121586 | 50.2 | `5de52d1775d10491` |
| EV-02 | `s00001-pump-detail.jpg` | `S00001_IMG_PUMP` | DEMO_001 | `ISSUE_DETAIL` | `TEAM_SYNTHETIC_AUGMENTATION` | ✅ `80525870445254.PNM` | 1254×1254 | 108768 | 43.5 | `c4e627200c2bdf37` |
| EV-03 | `s00001-package-context.jpg` | `S00001_IMG_PACKAGE` | DEMO_001 | `PACKAGE_CONTEXT` | `TEAM_SYNTHETIC_AUGMENTATION` | ✅ `80525870445254.PNM` | 1254×1254 | 213606 | 174.4 | `b71de6a18df65c16` |
| EV-04 | `s00001-gift-evidence.jpg` | `S00001_GIFT_IMG` | DEMO_002 | `PACKAGE_CONTEXT` | `TEAM_SYNTHETIC_AUGMENTATION` | ❌ `DEMO_AUG_IMG_GIFT` | 1254×1254 | 240707 | 177.0 | `da5d552e16308237` |
| EV-05 | `s00001-blurred-pump.jpg` | `S00001_BLURRED_IMG` | DEMO_003 | `ISSUE_DETAIL`（实际构图 `PRODUCT_OVERVIEW`） | `TEAM_SYNTHETIC_AUGMENTATION` | ❌ `DEMO_AUG_IMG_BLURRED` | 1254×1254 | 88339 | 15.8 | `4e9bbb5e184a6880` |

只有 EV-01 保留了赛事路径引用 `mock_images/broken_pump/S00001_03.jpg`（`competition_reference_path`），其余为纯团队扩充。完整 sha256 见 JSON。

### 3.2 A 线派生的 2 张答辩级资产

放在本目录的 `EVIDENCE-ASSETS/`，**不替换**上表任何文件：

| # | 文件名 | 派生方式 | 用途 | 清晰度 |
|---|---|---|---:|
| EV-06 | `s00001-pump-detail-blurred.jpg` | 对 EV-02 施加高斯模糊 radius=1.0 | 与泵头特写同构图的模糊版本；若要让 DEMO_003 保持 `ISSUE_DETAIL`，用它替换 EV-05 即可满足「同角度、只差清晰度」 | 17.1 |
| EV-07 | `s00001-pump-detail-assertion.jpg` | 在 EV-02 底部叠加一行断言文字，其余像素不变 | 验收 A26 的对照组：与 EV-02 相比，`evidence_status` 必须一致 | 192.1 |

---

## 4. 文件级核验方法与结论

核验方法（A 线 2026-09-17 在本地执行，可复现）：

1. 逐文件读取并 JPEG 解码，确认不是只有文件名的空壳；
2. 读取宽高与色彩模式；
3. 计算 sha256，作为后续比对基线；
4. 计算清晰度（Laplacian 方差）与边缘密度；
5. 用 256×256 灰度缩略图做两两相关系数与 MSE，判断构图相似性。

结论：

- 5 张素材**全部存在、可解码**，尺寸统一为 1254×1254 RGB JPEG，无格式异常。
- 清晰度分层明显：EV-03 / EV-04（174.4 / 177.0）为细节丰富图，EV-01（50.2）为商品整体，EV-02（43.5）为泵头特写，EV-05（15.8）明显低于全部清晰图。
- 构图相关性矩阵的关键值：

| 对比 | MSE | 相关系数 | 结论 |
|---|---:|---:|---|
| EV-01 ↔ EV-05 | 42.3 | 0.985 | **同一构图**（对 EV-01 轻微模糊后 MSE 降至 13.3） |
| EV-02 ↔ EV-05 | 925.8 | 0.382 | 不同构图 |
| EV-01 ↔ EV-02 | 993.9 | 0.368 | 不同构图 |

---

## 5. `evidence_status = VALID` 的推导链

| 判定步骤 | 结果 |
|---|---|
| 是否存在可读性为 LOW 的图片 | 否（三张均为 HIGH） |
| 是否存在 SKU 不匹配 | 否（三张均 `MATCH`） |
| 覆盖项并集 | `{PRODUCT_IDENTITY, AFFECTED_COMPONENT, DAMAGE_DETAIL, PACKAGE_CONTEXT}` |
| 是否包含要求的三项 | 是（`PRODUCT_IDENTITY`、`AFFECTED_COMPONENT`、`DAMAGE_DETAIL`） |
| 是否有图片的问题组件与 `current_issue` 一致且问题可见 | 是（EV-02，`PUMP`，`issue_visible = true`） |
| 结论 | **`VALID`** |

推导顺序取自 `CLAUDE-REVIEW-1.md` 的 C1 建议判定表，并与 B 线参考输出、D 线期望值 T01 / T07 一致。

三张图的期望观测量（完整字段见 JSON 的 `expected_image_observations`）：

| `evidence_id` | 可读性 | 商品可辨 | SKU | 角色 | 问题可见 | 组件 | 覆盖项 | 置信度 |
|---|---|---|---|---|---|---|---|---:|
| `S00001_IMG_OVERVIEW` | HIGH | true | MATCH | PRIMARY | false | UNKNOWN | `PRODUCT_IDENTITY` | 0.93 |
| `S00001_IMG_PUMP` | HIGH | true | MATCH | PRIMARY | true | PUMP | `AFFECTED_COMPONENT`, `DAMAGE_DETAIL` | 0.95 |
| `S00001_IMG_PACKAGE` | HIGH | true | MATCH | PRIMARY | true | OUTER_PACKAGE | `PACKAGE_CONTEXT` | 0.91 |

**状态标记：`EXPECTED_PENDING_MODEL_RUN`。** B 线当前的 `analyze` 是克隆固定样例响应，尚未真正从图片像素推理；这些数值是待验证的期望值，不是已观测值。

---

## 6. 两个挑战案例的证据

| 案例 | 素材 | 期望证据状态 | 期望决策 | 客观依据 |
|---|---|---|---|---|
| `DEMO_002` 范围变化 | `s00001-gift-evidence.jpg` | `MISMATCHED` | `ALLOW` / `E2` / 100 | 证据指向赠品，当前问题是正装泵头；差异项为「正装/赠品」 |
| `DEMO_003` 图片模糊 | `s00001-blurred-pump.jpg` | `NEED_HUMAN_REVIEW` | `HUMAN_REVIEW` / `H1` / **350** | 清晰度 15.8 对清晰图 43.5 / 50.2，边缘密度 1.99 对 2.85 / 3.41 |

---

## 7. 核验发现（7 项）

| 编号 | 级别 | 结论 | 归属 |
|---|---|---|---|
| F-01 | 信息 | 5 张素材全部可解码，尺寸统一，哈希已登记 | — |
| F-02 | **需要裁决** | `s00001-blurred-pump.jpg` 实际构图与商品整体图一致，却被声明为 `ISSUE_DETAIL`；H1 结论不受影响，但覆盖项会被误判 | 产品负责人 / B 线 |
| F-03 | 信息 | 「除清晰度外一致」的对照由 EV-01 ↔ EV-05 这一对满足，而不是 EV-02 ↔ EV-05 | D 线 |
| F-04 | 信息 | DEMO_001 的 `VALID` 推导成立，与 B/C/D 期望一致 | — |
| F-05 | 待验证 | 参考输出把三张图的 `integrity_concern` 全置 true、`hygiene_risk_signal` 全置 MEDIUM，属较强假设 | B 线 + A 线 |
| F-06 | 信息 | A26 所需「有文字 / 无文字」对照素材已补齐（EV-07 对 EV-02） | — |
| F-07 | **需要修复** | DEMO_002 / DEMO_003 的 `source_message_id` 不在各自 `conversation` 中，证据无法回溯 | 产品负责人 / B 线 |

F-02 的两个可选方案：

- **方案 A**：把 `DEMO_003` 的 `declared_view_type` 改为 `PRODUCT_OVERVIEW`，继续使用现有素材；
- **方案 B**：改用 A 线派生的 `s00001-pump-detail-blurred.jpg`，维持 `ISSUE_DETAIL` 语义。

---

## 8. 待办与跨线提醒（6 项）

| 编号 | 事项 | 影响 | 归属 |
|---|---|---|---|
| G-01 | 真实模型运行尚未发生，`analyze` 仍返回固定样例 | 门 2 目前不成立；抗演员段落不能使用缓存结果 | B 线 |
| G-02 | DEMO_003 证据声明与素材不符 | 见 F-02 | 产品负责人 / B 线 |
| G-03 | D 线期望值仍写 `H1 = 200` | 按旧值比对会把正确实现判为失败 | D 线 |
| G-04 | `fixtures` 中 DEMO_001 评估时间 11:00 与 P0-4 的 09:40 不一致 | 承诺到期叙事受影响 | 产品负责人 / B 线 |
| G-05 | 素材放在工程仓库内，与 D 线「图片不要塞进工程仓库」的建议冲突 | 来源分离原则弱化 | B 线 / D 线 |
| G-06 | `next_check_at = 10:30` 已统一，但 `docs/04` 回执样例文字仍写 10:27 | 文案滞后 | 产品负责人 |

---

## 9. 使用方式

| 角色 | 怎么用 |
|---|---|
| B 线 | 把本包的 `expected_image_observations` 作为模型输出对齐目标（**只在评测侧使用，不得进 Prompt**）；接入真实图片推理后逐项回填 `status` |
| C 线 | 右栏展开证据时引用 `evidence_id` 与 `file_name`；图片加载失败时保持已有占位回退 |
| D 线 | 用 sha256 核对素材未被替换；用第 5 节的覆盖项推导核对 `VALID`；用 F-03 修正对照项配对；按 G-03 更新期望值 |
| 答辩 | 用第 3、5 节说明「证据从哪来、覆盖了什么、为什么判定成立」，用第 7 节主动交代已知问题 |

数据来源与表述边界见 `05-EVIDENCE-SOURCE-STATEMENT.md`。
