# BATCH-28 退回修复报告｜单案例真实 Qwen 图文验收

**本批由辅助调度器实现，非独立实现方；验收须由他方完成。**

> This batch was implemented by the auxiliary dispatcher and is not an independent
> implementation; verification must be performed by another party.

| 项 | 值 |
| --- | --- |
| 批次 | BATCH-28（退回修复轮） |
| 工作树 | `C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\w28` |
| 分支 | `codex/covenia-batch-28-aux` |
| 修复前 HEAD | `f76dd1c3f9de1bc548d8c11841b25ad733533c10`（工作树干净） |
| 解释器 | `C:\cv28\venv\Scripts\python.exe`（Python 3.13.5，隔离 venv） |
| 端点 | `http://127.0.0.1:8001/v1/chat/completions`（共享 shim，**未 kill**） |
| VERIFICATION_REPORT.json | **未写**（验收方专属） |

---

## 0. 一句话结论

**根因判定：(A) 提示词未要求承诺级 trace —— 白名单外，已停下回报，未越权修改。**

模型输出的 JSON **结构完全合法**，`observations` 每一条都有 trace，但
`candidate_promise_texts` **一条 trace 都没有**；服务端校验器要求两个集合逐条覆盖，
于是抛出 `MISSING_FIELD_TRACE`。反事实证明：**只补上那 2 条 promise trace，校验立即通过** ——
说明这是提示词措辞缺口，不是校验器要求过高，也不是请求构造有误。

---

## 1. 第一步：诊断（已留证）

### 1.1 方法：字节透明抓包

上一轮交付只保留了 `AttemptRecord` 的结构化字段，**没有留下模型原始 JSON 文本**，
因此根因无法从既有产物判定。本轮用一个**字节透明代理**（`127.0.0.1:8002` → 已注册端点
`127.0.0.1:8001`）原样转发并落盘两侧原始字节。代理不修改任何字节，因此可以把代理测得的
摘要与工具自己记录的摘要直接比对：

| 项 | 代理测得 | 工具记录 | 一致 |
| --- | --- | --- | --- |
| request_bytes | 360282 | 360282 | ✅ |
| request_sha256 | `db0383f99f3bb047…187c22ed` | `db0383f99f3bb047…187c22ed` | ✅ |
| response_bytes | 2056 | 2056 | ✅ |
| response_sha256 | `6df1455a152de414…b41f78e4` | `6df1455a152de414…b41f78e4` | ✅ |
| upstream_status | 200 | 200 | ✅ |

> 摘要逐字节一致 ⇒ **本报告引用的模型原始输出，就是工具实际收到的那一份**，不是推测。

### 1.2 逐条回答审查方的问题

**Q1：模型实际返回了哪些 `source_trace` 条目？`field` 值分别是什么？**

共 **4 条**，`field` 全部落在 `observations` 集合：

```json
"source_trace": [
  {"field": "observations[0]", "source_type": "IMAGE", "source_id": "S00001_IMG_PUMP_DETAIL"},
  {"field": "observations[1]", "source_type": "IMAGE", "source_id": "S00001_IMG_PACKAGE_CONTEXT"},
  {"field": "observations[2]", "source_type": "CHAT",  "source_id": "36199788469718.PNM"},
  {"field": "observations[3]", "source_type": "CHAT",  "source_id": "22703823958720.PNM"}
]
```

`candidate_promise_texts[*]` 的 trace：**0 条**。

**Q2：`candidate.candidate_promise_texts` 有几条？模型是否被要求为每条承诺单独给 trace？**

- 条数：**2 条**（`换货单已创建，48小时内发出` / `先给您发全新的，收到后用包裹里的面单把坏的寄回就好，运费我们出`）。
- 校验器**要求**：是，且是硬要求 —— `source_validation.py:103-111` 构造
  `expected_fields = {observations[i]} ∪ {candidate_promise_texts[j]}`，集合不等即
  `MISSING_FIELD_TRACE`。
- 提示词**明确要求**：**否**。只有第 37 行一句抽象表述（见 Q3），没有说明 `field` 必须逐条为
  `candidate_promise_texts[N]` 的精确编号引用。

**Q3：提示词里关于 `source_trace` 的指令原文？是否明确要求「每个 observation 与每个 promise 各一条」？**

`backend/src/covenia_b/model/prompts/candidate_extraction.py:26-37`，逐字原文：

```
  "source_trace": [
    {
      "field": "observations[0] or candidate_promise_texts[0]",
      "source_type": "CHAT, IMAGE, ORDER, or TICKET",
      "source_id": "one supplied trusted source identifier"
    }
  ],
  "candidate_promise_texts": ["verbatim agent-chat promise quotation"]
}

Every observation and candidate promise needs a source_trace entry. Cite only supplied
source identifiers.
```

**判定：不明确。** 三点缺口：

1. 指令是抽象的「Every … needs an entry」，**没有**说明 `field` 必须是
   `observations[N]` / `candidate_promise_texts[M]` 的逐条精确编号引用；
2. 同一句里 `an entry` 是**单数**，示意「一个字段一条」，模型据此按 observation 数量给了
   恰好一一对应的 4 条；
3. schema 示例中 `"field"` 的值是**单条字面量** `"observations[0] or candidate_promise_texts[0]"`，
   推不出「两个集合都要逐条覆盖」。

补充观察：本批真实输出里 `observations[2]`/`[3]` 与两条 promise 文本高度重合，模型很可能据此
认为 observation 的 trace 已经「覆盖」了承诺。

**Q4：一次 schema-repair 重试后的返回形状是什么？**

**本批从未跑过 schema-repair。** `tools/verification/live_smoke.py` 每个 attempt 只调用一次
`provider.extract_with_metadata`，**没有**使用 `BoundedCandidateExtractor`，因此
`SCHEMA_REPAIR_SYSTEM_PROMPT`（同文件 49-63 行）在本批**完全未被行使**。工具里的 2 次 attempt
是两次同提示词的独立新调用，不是 initial+repair 配对。上一轮观测到的
「observations 变对象 → `ModelResponseInvalid`」「丢 trace 数组」在本轮 **未复现**：4 次真实调用的
形状**结构完全一致**（adapter 解析通过、schema 合法、4 obs + 2 promise + 4 trace）。

### 1.3 复现次数与一致性

本轮 4 次真实调用（2 次诊断 + 2 次官方复核；上一轮另有 2 次），**全部** HTTP 200、
usage EXACT、被 `MISSING_FIELD_TRACE` 拒绝，且 trace 形状**每次完全相同**：

| # | provider_request_id | output_tokens | provider_ms | traced fields | promise traces |
| --- | --- | --- | --- | --- | --- |
| 1 | `chatcmpl-b0ac6129-…` | 400 | 10154 | observations[0..3] | 0 |
| 2 | `chatcmpl-48650709-…` | 416 | 10650 | observations[0..3] | 0 |
| 3 | `chatcmpl-5123d499-…` | 373 | 8975 | observations[0..3] | 0 |
| 4 | `chatcmpl-ed465f80-…` | — | 9596 | observations[0..3] | 0 |

这排除了偶发/采样噪声解释：**稳定行为缺陷**。

---

## 2. 根因判定

### 2.1 归入 (A)，并排除 (B)/(C)/(D)

**(C) 已排除 —— 请求构造/输入装配完全正确。**
用生产代码（`CaseAssembler` + `ManifestImageResolver` + `FactLoader` +
`build_candidate_model_input`）重建的 provider 文本共 **1079 字符 / 9 行**，与 wire 抓包的
text part **完全一致**，其中：

- `[trusted_source_ids]` 列出**全部 12 个** 合法来源 ID；
- `order_id=6920185815517983396`；
- **6 条**带 `speaker=` 的聊天行，三条 AGENT 消息**逐字在场**：
  - `[message_id=51831669257761.PNM … speaker=AGENT] 亲亲抱歉！麻烦拍下破损部位的照片发给测试客服，为您核实换货哈~`
  - `[message_id=22703823958720.PNM … speaker=AGENT] 收到亲，确认属包装破损，为您登记换货：先给您发全新的，收到后用包裹里的面单把坏的寄回就好，运费我们出~`
  - `[message_id=36199788469718.PNM … speaker=AGENT] 换货单已创建，48小时内发出，给您带来不便啦~`

模型引用的两条承诺**逐字可回溯**到对应 AGENT 消息（NFKC/casefold/空白归一化后包含），
即 `PROMISE_NOT_AGENT_QUOTE` 也不成立。**模型做 trace 所需要的一切都在请求里。**

**(B) 已排除 —— 校验器要求是可满足的。** 见 §2.2 反事实证明。

**(D) 无其他因素。**

### 2.2 反事实证明（关键证据）

把模型**真实的**候选（逐字取自字节验证过的抓包）加上**仅**那 2 条缺失的 promise trace，
用生产 `SanitizedModelInput` 重跑 `validate_candidate_sources`：

```
--- 1. UNMODIFIED candidate (what the model actually returned) ---
REJECTED: MISSING_FIELD_TRACE

--- 2. COUNTERFACTUAL: only add the two promise traces the model omitted ---
ACCEPTED: SourceValidationSummary(trusted_source_count=11, traced_field_count=6,
          agent_quote_count=2, image_observation_count=2)
```

⇒ **trace 覆盖是唯一未满足条件。** 其余规则（图片绑定、`source_type` 匹配、AGENT 引文包含、
重复检测、图片指令语言排除）**模型本来就全对**。所以这不是「校验器要求超出模型能力」，
而是「提示词没有把要求写成可操作的形式」。

### 2.3 归属与为什么不能自行修

| 文件 | 归属批次 | 依据 |
| --- | --- | --- |
| `backend/src/covenia_b/model/prompts/**` | **BATCH-11** | `batches.json:2035-2044` |
| `backend/src/covenia_b/model/source_validation.py` | **BATCH-11** | 同上 |

`MASTER_PLAN.md` 明文禁令：

- **:3637** 「仅调整测试/调用参数在既定协议范围内；模型质量问题回 BATCH-10/11 所属修复，**不在本批偷偷改 Prompt 或规则**。」
- **:3682** 「发现根因属于其他批则提交最小修复请求，**不越界改**。」

⇒ **按纪律停在此处，未修改任何白名单外文件。**

### 2.4 跨线 remap 是否影响本次 trace 问题？

**不影响。** `CROSS-LINE-FIXTURE-EVIDENCE-ID-MISMATCH-20261006` 确实改变了送入模型的图片
evidence id（`S00001_IMG_OVERVIEW/PUMP/PACKAGE` →
`S00001_IMG_PRODUCT_OVERVIEW/PUMP_DETAIL/PACKAGE_CONTEXT`），但：

1. 三个图片 ID **逐字出现在**请求文本的 `[trusted_source_ids]` 里；
2. 模型**已经正确引用了其中两个**（`S00001_IMG_PUMP_DETAIL`、`S00001_IMG_PACKAGE_CONTEXT`），
   证明它能读、能解析；
3. 缺陷**只发生在 `candidate_promise_texts` 集合**，4 次真实调用中**没有任何一条图片 trace 缺失**。

---

## 3. 四条标准逐条结果

| # | 标准 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 聊天+真实图片 → 候选 → `ExtractedJourney`，`cached_result=false`，可核对 Qwen revision | **NOT_ACHIEVED** | HTTP 200、schema 合法，但被 `MISSING_FIELD_TRACE` 拒绝；`extracted_journey` 未构造。失败即发现，不作粉饰 |
| 2 | 模型确实收到图片字节，不是观察 JSON；真实 usage/时延 | **PASS** | 见 §3.1 |
| 3 | 20 秒分析预算可达 | **本轮 FAIL** | `model_bound_ms=20810 > 20000` → exit 4；但**单次 attempt 均在预算内**（10155 / 10650 ms）。口径缺陷见 §4 |
| — | 负向演示（死端口必须非零退出） | **PASS** | 两条路径均 **exit 3**，未触碰 8001 shim |

### 3.1 标准 2 独立复核：28 项检查 27 项通过

| 检查 | 结果 |
| --- | --- |
| 请求体字节数 | 360282 |
| content parts | `["text", "image_url", "image_url", "image_url"]` |
| 图片 sha256 集合 == ACCEPTED manifest | ✅ 三张全部一致 |
| 图片字节长度 / 尺寸 / MIME == manifest | ✅ 三张全部一致 |
| 磁盘上的 JPEG 文件 sha256 == manifest | ✅ 三张全部一致 |
| wire 上的图片 sha256 集合 == 工具记录的集合 | ✅ |
| `observation_json_sent_as_image` | `false` |
| wire request_bytes == 工具 `request_bytes` | ✅ 360282 |
| 每次 attempt HTTP 200 + provider request id | ✅ |
| usage_status | 全部 `EXACT` |
| upstream usage（逐字） | `prompt_tokens=5589, completion_tokens=373, total_tokens=5962` |
| `prompt_tokens_details` | `{image_tokens: 4569, text_tokens: 1020, cached_tokens: 0}` |

> `image_tokens=4569` 是**真发了图**的独立旁证 —— 文本只有 1079 字符。
> `cached_tokens=0` 与 `--disable-cache` / `cached_result=false` 口径一致。

**唯一未通过的检查**：`recorded model_bound_ms (=20810) <= 20000` → 见 §4。

### 3.2 负向演示输出

```
### 死端口 8099，TCP 预检路径（spec docstring 形态）
endpoint error [endpoint_unreachable]: --require-live and the endpoint is not reachable:
  tcp 127.0.0.1:8099 unreachable (ConnectionRefusedError)
EXITCODE_PROBE=3

### 死端口 8099，客户端失败路径（--skip-endpoint-probe）
live-smoke-v1: ENDPOINT_UNAVAILABLE
  PASS        facts_and_image_binding
  FAIL        real_http_call
  attempt 1: ENDPOINT_TIMEOUT status=None wall_ms=2016 usage=None (NOT_ATTEMPTED)
EXITCODE_CLIENT=3
```

**8001 shim 全程未 kill、未重启、未改配置。**

---

## 4. 第二个缺陷（白名单内，**本轮未修**，等裁决）

`tools/verification/live_smoke.py` 的 `model_bound_ms` 是**跨 attempt 累加**的：

- `:1046` `model_bound_started = time.perf_counter()`（循环**之前**）
- `:1072` `run.model_bound_ms = round((time.perf_counter() - model_bound_started) * 1000)`（循环**之后**）
- `:1074-1079` 用它判预算；`backend/tests/live/test_real_extraction.py:258` 也拿它跟 20 s 比

而冻结语义是**单次请求**的上限（`docs/05-api-and-ui.md`；`covenia_b.api.analyze`
的 `DEFAULT_ANALYSIS_TIMEOUT_SECONDS`；`BoundedCandidateExtractor(total_timeout_seconds=…)`
在 `extraction.py:129-138` 把 initial + 至多一次 repair 包在**一个** timeout 里）。

后果：本轮真实时延升到 10.2 / 10.7 s，两次 attempt 累加 **20810 ms > 20000**
→ `BUDGET_EXCEEDED`（exit 4）。**单独每一次 attempt 都在预算内。**

> ⚠️ **这会挡住绿灯路径**：即使把提示词问题修好，默认 `--attempts 2`
> （`DEFAULT_ATTEMPTS`，`:101`）仍会累加到超预算并报 `BUDGET_EXCEEDED`。

**为什么不在这轮修**：它改的是**已交付证据的度量语义**，且在提示词缺口未闭合前**无法**把标准 1
变绿。按「修复范围严格限定」的纪律，我报告而不擅自改动。

**建议的最小改法**（白名单内，可立即执行）：

- 循环内为每次 attempt 单独计时，把该 attempt 的 model-bound ms 记到 `AttemptRecord`
  （新增一个字段，例如 `model_bound_ms`）；
- `:1072-1079` 令 `run.model_bound_ms` = 被接受 attempt（被拒时取单次最大）的 model-bound ms；
  另存全程累计值，例如 `document["budget"]["model_bound_ms_total_run"]`；
- `test_real_extraction.py:258` **无需改动**，因为彼时 `model_bound_ms` 才真正等于冻结预算的语义。

**风险 LOW**：只改变预算判据读哪个数，**不可能**凭空造出被接受的候选；
每次 attempt 的原始 wall/provider ms 仍全部留在产物里。

---

## 5. 白名单外修改方案（精确，待授权）

**推荐 OPTION 1。** 理由：校验器是对的且是精确的（反事实证明它是精准拦截而非一刀切），
削弱它会**真的**拿掉一道防线；而模型输出在其余各方面**毫无瑕疵**，所以把 trace 要求写成
可操作形式是杠杆最高、改动最小的方案。

### OPTION 1（推荐）：让提示词把「逐条 field 引用」写清楚

| 项 | 内容 |
| --- | --- |
| 文件 | `backend/src/covenia_b/model/prompts/candidate_extraction.py` |
| 行号 | **26-35**（schema 示例）与 **37**（指令句）；**并需同步 49-63**（`SCHEMA_REPAIR_SYSTEM_PROMPT`） |
| 最小改动 | ① 第 29 行 `field` 的值由单条字面量 `"observations[0] or candidate_promise_texts[0]"` 改为**按集合编号的占位符**，明确 observations 每条用 `observations[0]`、`observations[1]`…，promises 每条用 `candidate_promise_texts[0]`、`candidate_promise_texts[1]`…<br>② 第 37 行改为**可计数的硬要求**，例如：`Emit one source_trace entry for EVERY element of observations and EVERY element of candidate_promise_texts. If observations has 4 elements and candidate_promise_texts has 2, source_trace must contain 6 entries with fields observations[0..3] and candidate_promise_texts[0..1]. A trace for an observation does not also cover a promise.`<br>③ 49-63 行同步同一措辞<br>④ `prompt_manifest()` 的 `candidate_prompt_sha256` / `schema_repair_prompt_sha256` 自动变化，需同步持有该哈希的下游记录 |
| 理由 | 指令抽象 + 示例单数化，模型据 observation 数量给出恰好一一对应的 4 条，只覆盖 observations 集合；把「两个集合逐条覆盖」写成可计数硬要求即可闭合契约 |
| 风险 | **MEDIUM-LOW** —— 提示词哈希变化会让相关记录需同步；承诺须为 AGENT 逐字引用这一约束不变，而该行为在 4 次真实调用中已稳定正确 |
| 影响面 | `model/prompts/candidate_extraction.py`；`prompt_manifest()` 哈希的下游引用；BATCH-11 的 `tests/model/test_extraction.py`、`test_sources.py`；BATCH-28 需重跑取新证据 |

### OPTION 2（**不推荐**）：放宽校验器

| 项 | 内容 |
| --- | --- |
| 文件 | `backend/src/covenia_b/model/source_validation.py` |
| 行号 | **103-111** |
| 最小改动 | 期望集合中允许 `candidate_promise_texts[j]` 由一个已 trace 且引文包含该 promise 的 `observations[i]` 满足 |
| 风险 | **HIGH** —— promise 将不再拥有**独立**来源绑定，promise 与 observation 的证据链合并，来源校验的严格性下降 |
| 建议 | **不采用**；除非产品负责人判断「承诺级独立 trace」不是必需防线强度 |

### OPTION 3：把两个文件纳入 BATCH-28 白名单

需改 `MASTER_PLAN.md` / `batches.json` 的批次白名单，属流程变更，需产品负责人裁决。

---

## 6. 审查方要求记录的两条副产品

> 明确记录，**不作为验收结论**。

1. **live 通路是真的（HTTP 200 + 真实 usage），不是空跑。**
   本轮 4 次真实 HTTP 200，均带上游 provider request id 与 `EXACT` usage
   （input 5589；output 373/400/416）。字节透明抓包**独立复现**了与工具自身记录**完全相同**的
   `request_sha256` / `response_sha256` —— 抓到的字节就是工具实际收发的字节。

2. **来源校验确实在拦（`MISSING_FIELD_TRACE`）—— 防线有效，不是摆设。**
   每一个真实候选都被 `source_validation.py:110-111` 以
   `SourceValidationCode.MISSING_FIELD_TRACE` 拒绝。反证明同时表明该检查是**精确**的而非一刀切：
   恰好多补 2 条缺失 trace，判据即翻转为 `ACCEPTED`。

---

## 7. 交付物与哈希

| 文件 | 字节 | SHA256 |
| --- | --- | --- |
| `reports/batches/BATCH-28/live/model-output.redacted.json` | 14101 | `86c4332ae0f256b2ea1ca5ee2df3a4e0ef9cbf9af849879a473643db86c83327` |
| `reports/batches/BATCH-28/live/governance.redacted.jsonl` | 4941 | `cb26fa03ef12b9109c41c3d26369a26c4aa36a4eb260f37a66d0eb1192f9871b` |
| `reports/batches/BATCH-28/live/environment.json` | 6142 | `dffbf8609cd183f80942a67c8b1619c1f23f064185f65db84f3419ac9d8d9734` |
| `reports/batches/BATCH-28/live/raw-model-capture.redacted.json`（新增） | 8971 | `4f5524c2039696f8bfab727c1303972a0f80eecb28bbec00947f5f1c9b3b799c` |
| `reports/batches/BATCH-28/environment.json` | 6142 | `8350a8594a451171cf0719306c8e0401fdb6664b8eb469f4f916a4da3c4b16d3` |
| `reports/batches/BATCH-28/DIAGNOSTIC.json`（新增） | — | 见文件 |
| `reports/batches/BATCH-28/REPAIR_REPORT.json`（本文件） | — | — |

### 依赖锁文件

**`UNCHANGED`**

| 项 | 值 |
| --- | --- |
| 路径 | `backend/requirements-dev.lock` |
| 变更类型 | `UNCHANGED` |
| 提交内 blob SHA256 | `602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae`（725 字节） |
| 工作树 canonical LF SHA256 | `602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae` |
| 工作树原始字节 SHA256 | `a7524fec02641fe9edcf300be27ee17969ca1188630d3d411162d6bba26d447f`（759 字节，CRLF） |
| 只追加 diff | **无**（`appended_entries: []`） |
| 原因 | 本批未新增任何第三方依赖；工具与 live 测试只使用标准库 + 已钉住的既有依赖 |

> blob 与工作树 canonical LF 摘要相同，原始字节摘要因 Windows CRLF 检出而不同，属设计如此。

---

## 8. 命令与退出码

| 命令 | 退出码 | verdict |
| --- | --- | --- |
| `python tools/verification/live_smoke.py --require-live --disable-cache --output reports/batches/BATCH-28/live` | **4** | `BUDGET_EXCEEDED`（两次 attempt 均 `SOURCE_REJECTED`） |
| `python tools/verification/live_smoke.py --require-live --disable-cache --attempts 1 --output <诊断目录>` | **1** | `MODEL_OUTPUT_REJECTED`（预算内 8980 ms） |
| `python -m pytest tests/live/test_real_extraction.py -q -m live` | **1** | `2 failed, 5 passed` |
| 负向控制（死端口 8099，预检路径） | **3** | `ENDPOINT_UNAVAILABLE` |
| 负向控制（死端口 8099，`--skip-endpoint-probe`） | **3** | `ENDPOINT_UNAVAILABLE` |
| `git diff --check` | **0** | 无空白错误 |

pytest 失败详情（失败文本自己点出根因，未被绕过）：

```
FAILED tests/live/test_real_extraction.py::test_real_endpoint_answered_and_the_run_stayed_inside_the_budget
FAILED tests/live/test_real_extraction.py::test_accepted_candidate_is_uncached_and_bound_to_the_locked_revision
E   Failed: the live run did not produce an accepted extraction: MODEL_OUTPUT_REJECTED (exit 1)
E   last outcome=SOURCE_REJECTED rejection=MISSING_FIELD_TRACE
```

---

## 9. 本轮**故意未做**的事

- ✗ 未改 `backend/src/covenia_b/model/prompts/candidate_extraction.py`
- ✗ 未改 `backend/src/covenia_b/model/source_validation.py`
- ✗ 未改 `schemas/**`、`domain/**`、`api/**`、`services/**`、`model/**`、`fixtures/**`、计划文件、`CLAUDE*.md`
- ✗ 未写 `reports/batches/BATCH-28/VERIFICATION_REPORT.json`
- ✗ 未做任何验收结论
- ✗ 未 kill / 重启 8001 shim

## 10. 待调度方裁决

1. **授权 BATCH-11** 按 OPTION 1 修改提示词（含 schema-repair 变体），随后 BATCH-28 重跑取新证据；
2. **授权修正 `model_bound_ms` 预算口径**（§4）—— 否则修好提示词后默认 2 次 attempt 仍会
   `BUDGET_EXCEEDED`；
3. 确认 `CROSS-LINE-FIXTURE-EVIDENCE-ID-MISMATCH-20261006` 仍由 A 线持有（本批只能用
   `file_name` 绑定并如实记录 remap）。
