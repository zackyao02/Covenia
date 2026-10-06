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
| 本报告轮次的提交 | 见 §11 提交记录 |
| 解释器 | `C:\cv28\venv\Scripts\python.exe`（Python 3.13.5，隔离 venv） |
| 端点 | `http://127.0.0.1:8001/v1/chat/completions`（共享 shim，**未 kill**） |
| VERIFICATION_REPORT.json | **未写**（验收方专属） |

---

## 0. 结论摘要

本轮定位并处理了**三个**阻塞点：

| # | 阻塞点 | 归属 | 状态 |
| --- | --- | --- | --- |
| 1 | **提示词未把「承诺级 trace」写成可操作要求** → `MISSING_FIELD_TRACE` | **BATCH-11（白名单外）** | 由**他人**在工作树改成 v2；**v2 只解决 1/3**，见 §5 |
| 2 | **`live_smoke.py` 把 4 个模块级函数当成 `AnalyzeService` 静态方法** → `AttributeError`，journey 永远构造不出来 | **BATCH-28（白名单内）** | ✅ **本轮已修**，见 §4 |
| 3 | `model_bound_ms` 跨 attempt 累加，与 20 秒**单请求**预算口径不符 | **BATCH-28（白名单内）** | ⚠️ 未修，已给精确方案，见 §4.3 |

**标准 1 已达成**（在 v2 提示词 + 本轮的 journey 修复下）：
`HTTP 200 → schema 合法 → 来源校验 PASS → ExtractedJourney 构造成功 → cached_result=false`，
Qwen revision 可核对。**但请务必读完 §5 的可靠性限制** —— 这次通过依赖了一个 1/3 概率的
提示词行为，不能当作稳定的绿灯。

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

### 1.2 逐条回答审查方的问题（v1 基线）

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

`backend/src/covenia_b/model/prompts/candidate_extraction.py:26-37`（v1），逐字原文：

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

补充观察：真实输出里 `observations[2]`/`[3]` 与两条 promise 文本高度重合，模型据此认为
observation 的 trace 已经「覆盖」了承诺。

**Q4：一次 schema-repair 重试后的返回形状是什么？**

**本批从未跑过 schema-repair。** `tools/verification/live_smoke.py` 每个 attempt 只调用一次
`provider.extract_with_metadata`，**没有**使用 `BoundedCandidateExtractor`，因此
`SCHEMA_REPAIR_SYSTEM_PROMPT`（同文件 49-63 行）在本批**完全未被行使**。工具里的 2 次 attempt
是两次同提示词的独立新调用，不是 initial+repair 配对。上一轮观测到的
「observations 变对象 → `ModelResponseInvalid`」「丢 trace 数组」在本轮 **未复现**。

### 1.3 复现次数与一致性

v1 提示词下 4 次真实调用（上一轮 2 次 + 本轮 2 次），**全部** HTTP 200、usage EXACT、
被 `MISSING_FIELD_TRACE` 拒绝，且 trace 形状**每次完全相同**：

| # | provider_request_id | output_tokens | provider_ms | traced fields | promise traces |
| --- | --- | --- | --- | --- | --- |
| 1 | `chatcmpl-b0ac6129-…` | 400 | 10154 | observations[0..3] | 0 |
| 2 | `chatcmpl-48650709-…` | 416 | 10650 | observations[0..3] | 0 |
| 3 | `chatcmpl-5123d499-…` | 373 | 8975 | observations[0..3] | 0 |
| 4 | `chatcmpl-ed465f80-…` | — | 9596 | observations[0..3] | 0 |

---

## 2. 根因判定（针对 v1 基线）

### 2.1 归入 (A)，并排除 (B)/(C)/(D)

**(C) 已排除 —— 请求构造/输入装配完全正确。**
用生产代码（`CaseAssembler` + `ManifestImageResolver` + `FactLoader` +
`build_candidate_model_input`）重建的 provider 文本共 **1079 字符 / 9 行**，与 wire 抓包的
text part **完全一致**，其中：

- `[trusted_source_ids]` 列出**全部 12 个** 合法来源 ID；
- `order_id=6920185815517983396`；
- **6 条**带 `speaker=` 的聊天行，三条 AGENT 消息**逐字在场**；
- 模型引用的两条承诺**逐字可回溯**到对应 AGENT 消息，即
  `PROMISE_NOT_AGENT_QUOTE` 也不成立。

**(B) 已排除 —— 校验器要求是可满足的。** 见 §2.2。

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
重复检测、图片指令语言排除）**模型本来就全对**。

### 2.3 归属

| 文件 | 归属批次 | 依据 |
| --- | --- | --- |
| `backend/src/covenia_b/model/prompts/**` | **BATCH-11** | `batches.json:2035-2044` |
| `backend/src/covenia_b/model/source_validation.py` | **BATCH-11** | 同上 |

`MASTER_PLAN.md` 明文禁令：

- **:3637** 「…模型质量问题回 BATCH-10/11 所属修复，**不在本批偷偷改 Prompt 或规则**。」
- **:3682** 「发现根因属于其他批则提交最小修复请求，**不越界改**。」

⇒ 我**没有**修改这两个文件（工作树里出现的 v2 改动**不是本轮修复所为**，见 §5）。

### 2.4 跨线 remap 是否影响本次 trace 问题？

**不影响。** 三个图片 ID **逐字出现在**请求文本的 `[trusted_source_ids]` 里；模型**已正确引用
其中两个**；缺陷**只发生在 `candidate_promise_texts` 集合**，4 次真实调用中**没有任何一条图片
trace 缺失**。

---

## 3. 四条标准逐条结果

| # | 标准 | v1 基线 | v2 + journey 修复 |
| --- | --- | --- | --- |
| 1 | 聊天+真实图片 → 候选 → `ExtractedJourney`，`cached_result=false`，可核对 Qwen revision | **NOT_ACHIEVED** | ✅ **ACHIEVED**（附可靠性限制，见 §5） |
| 2 | 模型确实收到图片字节，不是观察 JSON；真实 usage/时延 | PASS | PASS |
| 3 | 20 秒分析预算可达 | FAIL（累加口径 20810 ms） | ✅ PASS（`model_bound_ms=12856`） |
| — | 负向演示（死端口必须非零退出） | PASS（exit 3） | PASS（exit 3） |

### 3.1 标准 1 的达成证据（`prompt-v2-passing-run`）

```
status  : PASS
stages  : {"accountability_state":"PASS","candidate_schema":"PASS",
           "extracted_journey":"PASS","facts_and_image_binding":"PASS",
           "real_http_call":"PASS","source_validation":"PASS"}
budget  : WITHIN_BUDGET  model_bound_ms=12856  frozen=20.0s
```

| 项 | 值 |
| --- | --- |
| accepted attempt | 2（attempt 1 被 `MISSING_FIELD_TRACE` 拒绝） |
| prompt_version | `candidate-extraction-v2` |
| candidate prompt SHA256 | `415814b938ef6fd85cdd4e299259308efae75c75190063f3b4b969ef3ca08f9e` |
| `model_metadata.model_id` | `qwen3-vl-plus` |
| `model_metadata.model_revision` | `qwen3-vl-plus-2025-12-19`（与 `configuration.model_revision` 一致） |
| **`model_metadata.cached_result`** | **`false`** |
| `extracted_journey.case_id` | `DEMO_001`（== `input_binding.case_id`） |
| `extracted_journey.model_metadata.cached_result` | `false` |
| `extracted_journey.source_trace` 长度 | 15 |
| `image_observations` / `promise_events` | 3 / 5 |
| `extracted_scope` | `order_id=6920185815517983396`、`sku_id=XC33003`、`issue_type=PACKAGE_DAMAGE` |
| `source_validation` | `trusted_source_count=11`、`traced_field_count=4`、`agent_quote_count=1`、`image_observation_count=3` |
| `accountability_state.case_id` | `DEMO_001` |
| `case_status` / `evidence_status` | `ACTION_REVIEW` / `NEED_HUMAN_REVIEW` |
| `run_id` | `qwen-427e1e79df88495488ae485b9672e89d` |

> attempt 2 的 4 条 trace：`observations[0]`、`observations[1]`、`observations[2]`（IMAGE）
> + **`candidate_promise_texts[0]`（CHAT `36199788469718.PNM`）** —— 正是缺失的那类条目。

### 3.2 标准 2 独立复核：28 项检查 27 项通过（v1 基线）

图片 sha256 / 字节长度 / 尺寸 / MIME 与 ACCEPTED manifest **及磁盘文件**三方一致；
wire 上 `content parts = [text, image_url×3]`、`observation_json_sent_as_image=false`；
usage 全部 `EXACT`；上游 `prompt_tokens_details = {image_tokens: 4569, text_tokens: 1020,
cached_tokens: 0}` —— `image_tokens=4569` 是**真发了图**的独立旁证（文本只有 1079 字符）。

### 3.3 负向演示输出

```
### 死端口 8099，TCP 预检路径
endpoint error [endpoint_unreachable]: ... tcp 127.0.0.1:8099 unreachable (ConnectionRefusedError)
EXITCODE_PROBE=3

### 死端口 8099，客户端失败路径（--skip-endpoint-probe）
live-smoke-v1: ENDPOINT_UNAVAILABLE
  attempt 1: ENDPOINT_TIMEOUT status=None wall_ms=2016 usage=None (NOT_ATTEMPTED)
EXITCODE_CLIENT=3
```

**8001 shim 全程未 kill、未重启、未改配置。**

---

## 4. 白名单内的修复（本轮实际改动）

### 4.1 缺陷：把模块级函数当成 `AnalyzeService` 的静态方法

原代码（`tools/verification/live_smoke.py:1152-1159`）：

```python
service = modules["AnalyzeService"]
source_summary = service._validate_candidate(candidate, loaded)
compilation = service._compile_from_server_facts(...)      # AttributeError
journey = service._enrich_extracted_journey(...)           # AttributeError
evidence = service._aggregate_server_evidence(...)         # AttributeError
```

`backend/src/covenia_b/services/analyze.py`（**git 状态干净，未被任何人修改**）里：

| 名称 | 行 | 实际种类 |
| --- | --- | --- |
| `_DEFAULT_POLICY` | 72 | 模块级 `CommitmentPolicy` |
| `_compile_from_server_facts` | 399 | 模块级函数 |
| `_enrich_extracted_journey` | 410 | 模块级函数 |
| `_aggregate_server_evidence` | 539 | 模块级函数 |
| `_validate_candidate` | 321-327 | ✅ 真的是 `@staticmethod` |

实测报错：`AttributeError: type object 'AnalyzeService' has no attribute '_compile_from_server_facts'`

**这是标准 1 的硬阻塞**：即使提示词完全修好，只要进入 journey 构造就必然抛异常。
v1 时它被 `MISSING_FIELD_TRACE` 挡在前面所以没暴露 —— 也就是说
**`_enrich_extracted_journey` 这条路径在上一轮交付里从未被执行过**。

### 4.2 修复

- 在 `_load_modules()` 中一并导入这 4 个模块级对象并放进 `modules` 字典；
- 调用点改为经 `modules[...]` 解析；
- **另加** `except Exception` 兜底处理器：先 `_write_failure_document(...)` 落盘失败证据，
  **再 `raise`**。此前 v2 崩溃时**一个产物都没写**，真实缺陷看起来像「没跑」——
  这个漏洞会让任何意外异常变成不可审计的缺失。工具**不把崩溃变成 verdict**，traceback 仍留在 stderr。

修复后 `py_compile` 通过，`_load_modules()` 实测 4 个对象全部解析成功。

### 4.3 未修：`model_bound_ms` 预算口径（白名单内，等你裁决）

- `:1046` 计时器在循环**之前**启动，`:1072` 在循环**之后**停止 ⇒ **跨 attempt 累加**；
- `:1074-1079` 与 `test_real_extraction.py:258` 拿它跟**单请求**的 20 秒冻结预算比。

实测：v1 两次 attempt 累加 **20810 ms > 20000** → `BUDGET_EXCEEDED`（exit 4），
而**单次 attempt 都在预算内**（10155 / 10650 ms）。

建议改法：循环内为每次 attempt 单独计时；`run.model_bound_ms` 取被接受 attempt
（被拒时取单次最大）的值，全程累计值另存 `budget.model_bound_ms_total_run`。
`test_real_extraction.py:258` 无需改动。**风险 LOW**，不可能凭空造出被接受的候选。

> 注：在 v2 下两次 attempt 各约 6.4 s，累加 12.8 s 仍在预算内，所以这个问题**这一次没有触发**；
> 但它对时延敏感，仍应修正。

---

## 5. ⚠️ 关键限制：v2 提示词**不可靠**，标准 1 的通过带运气成分

我**没有**修改提示词（见 §2.3）。工作树中的 **v2** 改动是**他人在本轮作业期间**写入的，
且**从未提交**（`git log -S'candidate-extraction-v2' --all` 为空）。见 §7。

v2 把指令强化为「Emit one source_trace entry per observation and one per candidate promise;
a single entry never covers two fields」，并在 schema 示例里加了 `candidate_promise_texts[0]`。
但**这仍然不够**。我用**同一份真实输入、仅更换系统提示词**做了对照实验
（走 shim，不读也不落盘密钥）：

| 变体 | 通过校验规则的轮次 | promise trace 数 | 图片 trace |
| --- | --- | --- | --- |
| **A：v2 现状** | **1/3** ❌ | `[0, 1, 0]` | 3 |
| **B：v2 + 完整 worked example** | **7/7** ✅ | 全 1 | 3（保留） |
| C：v2 + 只补 promise trace 指令 | 3/3 ✅ | 全 1 | **observations 被压成 2 条**（丢一条图片观察） |

**v2 失败的样子**（字节级抓包，第 4 次真实调用）：系统提示词里明明写着那条硬要求，
示例里也有 `candidate_promise_texts[0]`，模型**仍然**只输出 3 条 trace 对应 3 条 observation，
**promise trace = 0**。

**模型的系统性倾向**：把「引用了同一句 AGENT 原话的 observation」当成已覆盖该 promise。
观测完全一致 —— v1 是 4 obs + 2 promise → 4 traces；v2 是 3 obs + 1 promise → 3 traces，
**恒为「每个 observation 一条」**。

⇒ **v2 是 1/3 的抛硬币。** 本轮 `pytest -m live` 之所以 7/7 通过，是因为工具的
`--attempts 2` 循环里 **attempt 1 被拒、attempt 2 恰好被接受**（见 `prompt-v2-passing-run`）。
**这不是稳定的绿灯，不能据此认定标准 1 已稳定达成。**

### 5.1 与并行轮次的独立测量对照（样本合并）

同一工作树里还有**另一个辅助轮次**（`reports/batches/BATCH-28/AUX_CROSS_LINE_REPAIR_REPORT.json`，
它把本会话称作 "the concurrent implementation session"）。它**独立**统计了 v2 下的接受率：

| 来源 | v2 前（v1） | v2 后 |
| --- | --- | --- |
| 本轮变体 A 对照实验 | — | **1/3** |
| 另一轮次的 attempt 级统计 | 0/5 | **2/9** |

两者一致指向 **v2 下约 1/4 的接受率**。另一轮次的措辞我完全同意，并在此原样重申其结论：
**0/5 与 2/9 在这么小的样本量下不构成统计区分**，因此本批**不声称** v2 提高了接受概率；
只声称：**判据在真实调用下两次被达成**，且主导失败模式依然存在。

> 两轮独立得到同一量级，比任何单轮结论都更可信：**提示词修复是必要的，但不充分。**

**所需的增量很小**：把下面这段（变体 B，实测 7/7）并入 v2 即可：

```
Worked example. If the source text contains exactly one AGENT message that
makes a promise, and you produce:

  "observations": ["a", "b", "c"],
  "candidate_promise_texts": ["the promise"]

then source_trace MUST contain exactly four entries, one per element:

  "source_trace": [
    {"field": "observations[0]",            "source_type": "IMAGE", "source_id": "<id>"},
    {"field": "observations[1]",            "source_type": "IMAGE", "source_id": "<id>"},
    {"field": "observations[2]",            "source_type": "CHAT",  "source_id": "<id>"},
    {"field": "candidate_promise_texts[0]", "source_type": "CHAT",  "source_id": "<id>"}
  ]

The fourth entry is required even when observations[2] already quotes the same
agent sentence. An observation trace never satisfies the promise trace.
```

---

## 6. 审查方要求记录的两条副产品

> 明确记录，**不作为验收结论**。

1. **live 通路是真的（HTTP 200 + 真实 usage），不是空跑。**
   本轮共 **10 次**真实 HTTP 200（4 次 v1 诊断/复核 + 1 次 v2 诊断 + 5 次对照实验/通过轮），
   均带上游 provider request id 与 `EXACT` usage。字节透明抓包**独立复现**了与工具自身记录
   **完全相同**的 `request_sha256` / `response_sha256` —— 抓到的字节就是工具实际收发的字节。
   上游 `image_tokens=4569`（文本仅 1079 字符）进一步证明图片字节真的送达。

2. **来源校验确实在拦（`MISSING_FIELD_TRACE`）—— 防线有效，不是摆设。**
   v1 下**每一个**真实候选都被 `source_validation.py:110-111` 以
   `SourceValidationCode.MISSING_FIELD_TRACE` 拒绝；v2 下仍是 1/3 拦截率。反证明同时表明
   该检查是**精确**的而非一刀切：恰好多补那条缺失 trace，判据即翻转为 `ACCEPTED`。

---

## 7. 重要：工作树被并发修改（**不是本轮修复所为**）

本轮作业期间，以下变更**由他人**写入工作树：

| 路径 | 状态 |
| --- | --- |
| `backend/src/covenia_b/model/prompts/candidate_extraction.py` → **v2** | 已改，**未提交** |
| `backend/src/covenia_b/settings.py` → `candidate-extraction-v2` | 已改，**未提交** |
| `reports/batches/BATCH-28/prompt-v1-run/**`（4 个文件） | 突然出现；**内容是我 v1 产物的副本**，`generated_at` 完全相同（`2026-10-06T06:35:43.462679+00:00`） |

- v2 改动**从未提交**（`git log -S'candidate-extraction-v2' --all` 为空）。
- 我的第一次提交**误将 `prompt-v1-run/**` 一并 stage**（我只想 add 自己写的报告）。
  这是我的操作失误：这些文件**不是我创建**的，我已在下一次提交中把它们从索引移除
  （磁盘保留，交由创建者处置）。
- 由于提示词被改成 v2，本报告 §1/§2/§3.2 的 v1 证据**保留在 `live/`**（其 `generated_at`
  早于 v2 改动），而 v2 结果放在 `prompt-v2-run/` 与 `prompt-v2-passing-run/`，两者不混淆。

---

## 8. 交付物与哈希

| 文件 | 字节 | SHA256 |
| --- | --- | --- |
| `live/model-output.redacted.json`（v1 基线） | 14101 | `86c4332ae0f256b2ea1ca5ee2df3a4e0ef9cbf9af849879a473643db86c83327` |
| `live/governance.redacted.jsonl` | 4941 | `cb26fa03ef12b9109c41c3d26369a26c4aa36a4eb260f37a66d0eb1192f9871b` |
| `live/environment.json` | 6142 | `dffbf8609cd183f80942a67c8b1619c1f23f064185f65db84f3419ac9d8d9734` |
| `live/raw-model-capture.redacted.json`（新增） | 8971 | `4f5524c2039696f8bfab727c1303972a0f80eecb28bbec00947f5f1c9b3b799c` |
| `prompt-v2-run/model-output.redacted.json`（v2 单次诊断，仍被拒） | 见文件 | — |
| `prompt-v2-passing-run/model-output.redacted.json`（新增，**标准 1 达成证据**） | 23832 | `4bbee112972b77b8da32e514beb49f56d446f68f3164e3a8fae53e86a273ad10` |
| `prompt-v2-passing-run/governance.redacted.jsonl` | 4938 | `bc257be6c6d47e92cd5c14a277f894579338436f2c430abb881ea3c80ff42d5a` |
| `prompt-v2-passing-run/environment.json` | 6142 | `83bdea14ae107364a1956654c4b61f839cc867813b1528a69fec1cb3ccc328c6` |
| `reports/batches/BATCH-28/environment.json` | 6142 | `8350a8594a451171cf0719306c8e0401fdb6664b8eb469f4f916a4da3c4b16d3` |
| `DIAGNOSTIC.json`（新增） | 见文件 | — |
| `REPAIR_REPORT.json` / `.md`（本文件） | 见文件 | — |

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

---

## 9. 命令与退出码

| 命令 | 退出码 | verdict |
| --- | --- | --- |
| `live_smoke.py --require-live --disable-cache --output reports/batches/BATCH-28/live`（v1） | **4** | `BUDGET_EXCEEDED`（两次 attempt 均 `SOURCE_REJECTED`） |
| `live_smoke.py --attempts 1`（v1，诊断） | **1** | `MODEL_OUTPUT_REJECTED`（预算内 8980 ms） |
| `live_smoke.py --attempts 1 --output …/prompt-v2-run`（v2，journey 修复后） | **1** | `MODEL_OUTPUT_REJECTED`（6723 ms，仍 `MISSING_FIELD_TRACE`） |
| **`pytest tests/live/test_real_extraction.py -v -m live`（v2 + 修复）** | **0** | ✅ **7 passed in 14.41s** |
| 负向控制（死端口 8099，预检路径） | **3** | `ENDPOINT_UNAVAILABLE` |
| 负向控制（死端口 8099，`--skip-endpoint-probe`） | **3** | `ENDPOINT_UNAVAILABLE` |
| `git diff --check` | **0** | 无空白错误 |

`pytest -m live` 逐项（全 PASS）：

```
test_live_tool_is_invoked_uncached_under_this_interpreter                      PASSED
test_real_endpoint_answered_and_the_run_stayed_inside_the_budget               PASSED
test_the_model_received_registered_image_bytes_not_observation_json            PASSED
test_usage_and_latency_are_taken_from_upstream                                 PASSED
test_accepted_candidate_is_uncached_and_bound_to_the_locked_revision           PASSED
test_a_rejected_run_is_reported_honestly                                       PASSED
test_governance_log_is_redacted_and_complete                                   PASSED
```

---

## 10. 本轮**故意未做**的事

- ✗ 未改 `backend/src/covenia_b/model/prompts/candidate_extraction.py`（工作树里的 v2 是他人所为）
- ✗ 未改 `backend/src/covenia_b/model/source_validation.py`
- ✗ 未改 `schemas/**`、`domain/**`、`api/**`、`services/**`、`fixtures/**`、计划文件、`CLAUDE*.md`
- ✗ 未写 `reports/batches/BATCH-28/VERIFICATION_REPORT.json`
- ✗ 未做任何验收结论
- ✗ 未 kill / 重启 8001 shim
- ✗ 未读取、未复制、未落盘 `DASHSCOPE_API_KEY`（对照实验走 shim，由 shim 注入凭据）

---

## 11. 待调度方裁决

1. **是否把 §5 的 worked example 增量并入 v2 提示词**（白名单外，BATCH-11 归属）。
   这是让标准 1 **稳定**达成的必要步骤；v2 现状只有 1/3。
2. **是否授权修正 `model_bound_ms` 累计口径**（§4.3）。
3. **`prompt-v1-run/**` 与 v2 未提交改动如何处置**（§7）——
   我已在后续提交中把 `prompt-v1-run/**` 移出索引但保留在磁盘。
4. 确认 `CROSS-LINE-FIXTURE-EVIDENCE-ID-MISMATCH-20261006` 仍由 A 线持有。

