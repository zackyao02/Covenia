# BATCH-28 跨线修复报告（提示词 v2 + settings 同步）

> **本批由辅助调度器实现，非独立实现方；验收须由他方完成。**
>
> 本文件是实现证据，不是验收结论。`reports/batches/BATCH-28/VERIFICATION_REPORT.json` 属于独立验收方，本轮**未创建、未修改**。

## 0. 为什么这份报告不叫 `REPAIR_REPORT.json`

`reports/batches/BATCH-28/REPAIR_REPORT.json` 与 `.md` **已存在**，由**同一 worktree 内另一个并发实现会话**在 `ab3dba9`（2026-10-06T14:39:01+08:00）提交，内容与本轮不同。覆盖它会毁掉他方交付物，因此本轮另立文件名，两者并存：

| 文件 | 作者 | 内容 |
| --- | --- | --- |
| `REPAIR_REPORT.json/.md`、`DIAGNOSTIC.json`、`prompt-v1-run/`、`prompt-v2-run/`、`prompt-v2-passing-run/` | 并发会话 | v1 根因诊断、原样原始输出、跨批修复提案 |
| `AUX_CROSS_LINE_REPAIR_REPORT.json/.md`（本文件） | 本轮（辅助调度器实现方） | 授权跨线改动、v2 前后哈希、修复后全部 live 运行日志、四条标准逐条结果 |

**并发事实**：本轮工作期间 HEAD 由 `f76dd1c3` 被推到 `ab3dba9`；`tools/verification/live_smoke.py` 在 14:39:57 被该会话改动（未提交）；14:40:20 起该会话在 `127.0.0.1:8002` 另起抓包代理。本轮**未覆盖**其任何产物、**未提交**其未提交改动、**未 kill 8001 的共享 shim**。

## 1. 授权改动（提交 `8326e7360d26c96f6f379340bf8db8559bcb4b6f`）

仅 2 个文件、27 增 13 删：

1. `backend/src/covenia_b/model/prompts/candidate_extraction.py`
   - JSON 示例改为**三条具体条目、具体下标**（`observations[0]`、`observations[1]`、`candidate_promise_texts[0]`），**删除 `"or"`**；
   - 两段正文各补一句：`Emit one source_trace entry per observation and one per candidate promise; a single entry never covers two fields.`；
   - `PROMPT_VERSION`：`candidate-extraction-v1` → **`candidate-extraction-v2`**。
2. `backend/src/covenia_b/settings.py:56`
   - `model_prompt_version` 默认值 → `candidate-extraction-v2`（`runtime.py:589` 会与 `prompt_manifest()["prompt_version"]` 比对，不同步即 `RuntimeConfigurationError`；实测比对结果 **WOULD_PASS**）。

**未改**：`source_validation.py`、任何 schema / domain / 契约向量、其他批次产物、`CLAUDE*.md`。`backend/requirements-dev.lock` = **UNCHANGED**。

## 2. v1 → v2 哈希对照

| 项 | v1（被取代） | v2（当前） |
| --- | --- | --- |
| `prompt_version` | `candidate-extraction-v1` | `candidate-extraction-v2` |
| candidate prompt sha256 | `743d8c9668739b29a926261b5e99cf227eeb7cddda24d49a9e6b5fcb5ae34f5e` | `415814b938ef6fd85cdd4e299259308efae75c75190063f3b4b969ef3ca08f9e` |
| schema_repair prompt sha256 | `e3eba756c7e2e14411e93677b83c6b58a20a2fddcc1a9f75678651f5cdf5ab18` | `66b01ba18f434f8c1475429cd03230693bdd88c8d075838cdf46c607c3f86889` |

- 落点：`reports/batches/BATCH-28/prompt-manifest-v2.json`（新建）。
- **方法自校验**：v1 两个哈希由 `git show f76dd1c3:backend/src/covenia_b/model/prompts/candidate_extraction.py` 重新计算，与既有记录**逐字相符**，证明哈希方法正确后才用于 v2。
- **未改写** `reports/batches/BATCH-11/prompt-manifest.json`：它是 BATCH-11 自己的历史证据，全仓无消费者，保持原样。

## 3. 修复后真实 live 运行日志（含失败，未做筛选）

| # | 时间 (UTC) | 命令 / 来源 | 工具版本 | 尝试 | 结果 |
| --- | --- | --- | --- | --- | --- |
| A | 06:39:27 | 本轮官方 run 1：`live_smoke.py --require-live --disable-cache --output reports/batches/BATCH-28/live` | 提交态工具 `56163478…` | 2 | 两次 `SOURCE_REJECTED` / `MISSING_FIELD_TRACE`；exit 1；12514 ms |
| D | 06:40:06 | 并发会话 `prompt-v2-run` | 并发会话 | 1 | `SOURCE_REJECTED` / `MISSING_FIELD_TRACE`；6723 ms |
| E | 06:40:32 | 并发会话 8002 抓包运行 | 并发会话 | 1 | 拒绝；原始响应体经解码确认只有 `observations[0..2]` 三条 trace |
| **B** | **06:42:17** | **本轮：`pytest backend/tests/live/test_real_extraction.py -q -m live`** | 含并发会话未提交修复 `dd621368…` | **1** | **ACCEPTED → PASS**；`7 passed in 8.07s`；exit 0；6711 ms `WITHIN_BUDGET` |
| F | 06:43:02 | 并发会话 `prompt-v2-passing-run` | 并发会话 | 2 | 第 1 次拒绝、**第 2 次 ACCEPTED → PASS**；12856 ms |
| C | 06:43:04 | 本轮官方 run 2（同 A 命令） | 含并发会话未提交修复 `dd621368…` | 2 | 两次拒绝；exit 1；12879 ms |

对照 v1 基线（**5 次尝试，0 次接受**）：`f76dd1c3` 提交的 2 次、`prompt-v1-run/` 的 2 次、原始抓包的 1 次，全部 `MISSING_FIELD_TRACE`。

**尝试级统计**：v1 = 0/5 接受；v2 = **2/9** 接受。
**如实解读**：v2 让标准 1 **可达**（两次真实接受），但**不可靠**——9 次里 7 次仍是同一拒绝，且 v1(0/5) 与 v2(2/9) 在这个样本量下**不构成统计上的分离**。本轮**不主张** v2 提高了接受概率，只主张"两次真实达标 + 主失败模式依然存在"。

## 4. 四条标准逐条结果

| 标准 | 结果 | 依据 |
| --- | --- | --- |
| **1. 真实聊天+真实图片 → 200 → schema 合法候选 → 构造 `ExtractedJourney` → `cached_result=false` → 可核对 revision** | **达成两次，但不稳定** | 运行 B：HTTP 200（`chatcmpl-5d50c29b-…`）、`candidate_schema=PASS`、`source_validation=PASS`（traced 4 / image_obs 2 / agent_quote 1 / trusted 11）、`extracted_journey=PASS`、`accountability_state=PASS`（ACTION_REVIEW / NEED_HUMAN_REVIEW）、**`cached_result=false`**、revision `qwen3-vl-plus-2025-12-19` 与配置一致、prompt v2 与 manifest 一致。运行 F 同样 PASS。运行 A、C、D、E 未达成。 |
| **2. 图片字节真的送达** | **达成** | 独立复核脚本 `aux_verify_criteria_2_3.py` 从磁盘重算：**19/19**（官方 run 2）、**16/16**（接受的 live gate run）、19/19（v1 基线）。图片 sha256 三方一致（artifact == `handoff/a/images-manifest.json` == 磁盘文件，注册表存大写、产物存小写，按大小写无关比较）；请求体 360711 字节；content parts `[text, image_url ×3]`；`observation_json_sent_as_image=false`。 |
| **3. 真实 usage 与时延 + 20 秒预算** | **达成** | usage 全部 `EXACT` 且取自上游（输入 5684；输出 237/270），时延同时记录上游上报（6058–6708 ms）与本地上限，二者相差 1–2 ms；无任何估算值。接受运行 **6711 ms `WITHIN_BUDGET`**；官方 run 12514 / 12879 ms，因两次尝试均各自在预算内，判定为 `NOT_ACHIEVED_OUTPUT_REJECTED`（不再是 `BUDGET_EXCEEDED`）。 |
| **4. 负向演示** | **达成** | 端口偏离说明见下。默认探针路径：exit **3**、`ENDPOINT_UNAVAILABLE`、0 次尝试、`tcp 127.0.0.1:8099 unreachable (ConnectionRefusedError)`；`--skip-endpoint-probe` 路径（真 HTTP 客户端）：exit **3**、第 1 次尝试 `ENDPOINT_TIMEOUT` 2008 ms。**8001 共享 shim 全程未动。** |

**端口偏离（如实说明）**：审查意见要求指向未监听的 **8002**，但并发会话正用 8002 跑抓包代理（14:40:20 起），8002 当前**并非**未监听端口，故改用 **8099**（该会话上一轮亦如此），并由工具自身探针证明其未监听。

## 5. 审查方指定的两条副产品

**① live 通路是真的 —— HTTP 200 + 真实 usage，不是空跑。**
每次到达端点的尝试都返回 HTTP 200 并带 provider request id（如 `chatcmpl-5d50c29b-4d54-9272-83fc-89d8a2810349`）；每次都有上游真实 usage（`EXACT`，输入 5684 / 输出 237 或 270）与上游自报时延；请求体 360711 字节、1 个 text part + 3 个 image_url data part，图片摘要与已接受注册表一致；并发会话的字节透明代理抓到了同形状请求与响应体，线上字节可查而非自称。

**② 来源校验确实在拦 —— `MISSING_FIELD_TRACE` 证明防线有效；正因为防线有效，才暴露出提示词缺陷。**
本批每一次拒绝都是同一个稳定代码 `MISSING_FIELD_TRACE`，由 `source_validation.py:110` 在"已 trace 字段集合 ≠ 期望集合"时抛出；模型返回的是 **schema 合法**的候选（HTTP adapter 已接受），但承诺一条 trace 都没有，校验器**拒绝而不是猜测**。v1 5/5、v2 7/9 被拦，说明它不是走过场。正因为它拒绝并留下缺失字段名，提示词侧缺陷才得以定位与修复。校验器本轮**未做任何改动**。

## 6. 留给独立验收方的开放问题

1. 上游请求体在不含 `metadata`（共享 shim 转发前会剥掉 run id）时对同一输入**逐字相同**，却出现"两次接受 / 七次同样拒绝"的双峰：v1 抓包 `cached_tokens=0`、v2 抓包 `cached_tokens=5120`，上游前缀缓存是否参与造成该双峰，**本轮证据不足以判定**。
2. `reports/batches/BATCH-28/live/**` 目前放的是官方 run C（**拒绝**）；两次接受分别保存在 `aux-cross-line-v2/pytest-live-run-accepted/`（本轮）与并发会话的 `prompt-v2-passing-run/`。是否要把"跑到达标为止"的那次放进 `live/`，属于验收方的取舍，本轮**没有**为了好看而搬动文件。
3. **提交态工具无法达到 exit 0**：`tools/verification/live_smoke.py` 调用 `service._compile_from_server_facts` / `_enrich_extracted_journey` / `_aggregate_server_evidence`，但这三个是 `covenia_b.services.analyze` 的**模块级函数**，不是 `AnalyzeService` 成员（实测：`AnalyzeService` 上只有 `_validate_candidate`）。候选一旦被接受，提交态工具会在构造 journey 前抛 `AttributeError`。并发会话在工作树里有未提交修复，本轮两次接受都是在该修复存在的情况下取得的。**请验收方裁定以哪个工具修订版为验收对象**：由未提交修订版产生的接受产物，无法从提交复现。

## 7. 本轮有意未做

- 未改 `source_validation.py` / schema / domain / 契约向量；
- 未改写 BATCH-11 的 `prompt-manifest.json`；
- 未覆盖并发会话的任何产物；
- **未提交**并发会话未提交的 `tools/verification/live_smoke.py` 改动（把它记在本轮名下属于错误归属）；
- 未 push、未动其他 worktree、任何地方都**没有**用 `git add .`；
- run C 之后**不再追加 live 调用**：样本到此为止，而不是"跑到绿为止"，因此上面的接受率统计没有经过筛选。

## 8. 证据清单

```
reports/batches/BATCH-28/AUX_CROSS_LINE_REPAIR_REPORT.json / .md   ← 本报告
reports/batches/BATCH-28/prompt-manifest-v2.json                   ← 升版清单（v2 与 v1 哈希、原因、提交）
reports/batches/BATCH-28/aux-cross-line-v2/PROVENANCE.json         ← 下列文件的 sha256 与来源
reports/batches/BATCH-28/aux-cross-line-v2/official-run-1-rejected/**      运行 A
reports/batches/BATCH-28/aux-cross-line-v2/official-run-2-rejected/**      运行 C
reports/batches/BATCH-28/aux-cross-line-v2/pytest-live-run-accepted/**     运行 B（接受）
reports/batches/BATCH-28/aux-cross-line-v2/v1-baseline/**                  v1 基线快照（取自提交 ab3dba9）
reports/batches/BATCH-28/aux-cross-line-v2/concurrent-session-runs/**      并发会话运行 D / F 的快照
reports/batches/BATCH-28/aux-cross-line-v2/aux_verify_criteria_2_3.py      标准 2/3 独立复核脚本
reports/batches/BATCH-28/aux-cross-line-v2/aux-criteria-2-3.log            其输出
reports/batches/BATCH-28/live/**                                          运行 C（官方命令落点）
```

**自包含说明**：并发会话正在持续重排它自己的目录（本轮期间它已把 `prompt-v1-run/` 的文件 staged 成 rename 到 `prompt-v2-run/`、`prompt-v2-passing-run/`），因此本报告引用的每一份证据都在 `aux-cross-line-v2/` 内留有逐字节副本，逐文件 sha256 见 `PROVENANCE.json`。这些副本只是可追溯快照，**不是本轮自己的结果**，表格中一律标注为并发会话产出。

`backend/requirements-dev.lock`：**UNCHANGED**（`appended_entries=[]`；worktree 规范化 LF sha256 = 提交 blob sha256 = `602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae`；`git diff --numstat` 为空）。

离线闸门：`pytest backend/tests integration/tests -q -m "not live and not http and not e2e"` → **857 passed, 7 deselected, exit 0**；改动文件 `ruff check` → 0 错（全仓 54 条告警均为既有，位于 `reports/batches/BATCH-08|18|19|26|27|30/verification-evidence/**` 与两个 `backend/tests/domain` 文件，非本轮所触）。
