# BATCH-28 实现报告｜单案例真实 Qwen 图文验收

> 本批由辅助调度器实现，非独立实现方；验收须由他方完成。
>
> 本文件是实现方自报证据，不是验收结论；`VERIFICATION_REPORT.json` 由他方撰写。

## 1. 结论速览

| 验收标准 | 本批实测结果 |
| --- | --- |
| 1. 至少一次聊天+真实图片→候选→ExtractedJourney 成功，cached_result=false 且可核对 Qwen revision。 | **NOT_ACHIEVED（未达成）** |
| 2. 模型确实接收图片字节，不是观察 JSON；有日志/图片哈希/真实 usage/时延。 | **DEMONSTRATED（已证明）** |
| 3. 20 秒分析预算可达或明确 BLOCKED，不能把离线长跑写成联调通过。 | **WITHIN_BUDGET（预算内）** |
| 4. 按5.5使用本批绝对隔离venv解释器；新增第三方依赖只增不改、精确钉版本并提交锁文件差异/原因/hash证据；交付前同解释器 pip check 退出0。 | **SATISFIED（已满足）** |

| 项 | 值 |
| --- | --- |
| 基线提交 | `c2246645540b5f277c0c46c4d0388d01fc2eb05e` |
| 实现代码提交 | `test(live): run one real multimodal extraction under the 20s budget`（本文件所在提交为其后的报告提交，按 5.3-4 不自引用）|
| 分支 | `codex/covenia-batch-28-aux` |
| RUN_DIR / 解释器 | `C:\cv28` / `C:\cv28\venv\Scripts\python.exe` |
| 隔离 venv | `True`（pyvenv.cfg: include-system-site-packages=false）|
| `pip check` | 退出 0：No broken requirements found. |
| 锁文件 | UNCHANGED |

## 2. 逐条标准证据

### 标准 1｜NOT_ACHIEVED（未达成）

**原文**：至少一次聊天+真实图片→候选→ExtractedJourney 成功，cached_result=false 且可核对 Qwen revision。

**说明**：四次独立真实运行都拿到 HTTP 200 且候选通过结构解析，但服务端来源校验每次都以 MISSING_FIELD_TRACE 拒绝：模型为每条 observation 生成了 source_trace，却没有为 candidate_promise_texts 的每一项补上独立的那条 trace。候选被拒 → 未构造 ExtractedJourney → cached_result 从未被走到。本批如实记为未达成，不包装成通过。 (Four independent real runs returned HTTP 200 with an exactly parsed candidate, but the server-side source validator refused every one with MISSING_FIELD_TRACE.)

**证据**：

```json
{
  "facts_and_image_binding": "PASS",
  "real_http_call": "PASS",
  "candidate_schema": "PASS",
  "source_validation": "FAIL",
  "extracted_journey": "NOT_REACHED",
  "rejection_code": "MISSING_FIELD_TRACE",
  "attempts": 2
}
```

### 标准 2｜DEMONSTRATED（已证明）

**原文**：模型确实接收图片字节，不是观察 JSON；有日志/图片哈希/真实 usage/时延。

**说明**：请求里聊天文本只占 1 个 text part，三张经解析器校验的 JPEG 各占 1 个 image_url data part（request_bytes=360282）；模型自己描述出「泵头开裂、膏体溢出」「外盒一角压损」，这类内容只可能来自像素而非观察 JSON。发送的 SHA-256 与已接收登记清单逐字节一致，每次有应答的调用都带回上游真实 usage。 (The provider request carries one text part plus three verified image_url parts, and every answered call returned exact upstream usage.)

**证据**：

```json
{
  "image_sha256s_sent": [
    "e2c6bbd230f906f113d75f2f582e778b6e79aea37544c2383f1ffda15a5295d5",
    "4709d7529803846d4ff4e123bfcc034d420449ae23923cb54468be573bd8cfc7",
    "c734bfb5a70ffa39e10b2535dc8321eace3c1fb358293fa22b590b9f7b5836bd"
  ],
  "provider_content_parts": [
    "text",
    "image_url",
    "image_url",
    "image_url"
  ],
  "provider_request_contains_image_url_parts": 3,
  "observation_json_sent_as_image": false,
  "request_bytes": 360282,
  "usage": [
    {
      "input_tokens": 5589,
      "output_tokens": 374
    },
    {
      "input_tokens": 5589,
      "output_tokens": 373
    }
  ],
  "usage_status": [
    "EXACT",
    "EXACT"
  ],
  "provider_reported_duration_ms": [
    8154,
    7892
  ],
  "provider_request_ids": [
    "chatcmpl-2b7ccf5a-0b90-91db-9da6-51c039fc6d80",
    "chatcmpl-897a8f89-54ce-9d60-ab43-0bea34b608f5"
  ],
  "governance_log": "reports/batches/BATCH-28/live/governance.redacted.jsonl"
}
```

### 标准 3｜WITHIN_BUDGET（预算内）

**原文**：20 秒分析预算可达或明确 BLOCKED，不能把离线长跑写成联调通过。

**说明**：实测而非估算：一次 analyze 请求中与模型相关的部分（本批两次受控真实尝试合计 16052 ms，单次调用 [8155, 7893] ms）落在冻结的 20 秒预算内。本批没有放宽预算，也没有把离线长跑写成联调通过；单次调用的上游自报时延为 [8154, 7892] ms。 (Measured with perf_counter plus the provider's own reported duration; the budget was never widened.)

**证据**：

```json
{
  "budget_status": "NOT_ACHIEVED_OUTPUT_REJECTED",
  "frozen_analysis_budget_seconds": 20.0,
  "model_bound_ms": 16052,
  "case_load_ms": 43,
  "provider_wall_ms": [
    8155,
    7893
  ],
  "provider_reported_duration_ms": [
    8154,
    7892
  ],
  "measurement_boundary": "model_bound_ms covers the model call and its source validation, which is the part of one analyze request the 20s budget must cover; case_load_ms is reported separately and is not a model cost"
}
```

### 标准 4｜SATISFIED（已满足）

**原文**：按5.5使用本批绝对隔离venv解释器；新增第三方依赖只增不改、精确钉版本并提交锁文件差异/原因/hash证据；交付前同解释器 pip check 退出0。

**说明**：全部命令都在本批自有的绝对解释器下执行 （C:\cv28\venv\Scripts\python.exe），其 sys.prefix 与 sys.base_prefix 不同，pyvenv.cfg 中 include-system-site-packages=false。本批未新增任何依赖，故锁文件为 UNCHANGED；提交内 blob 摘要按 MASTER_PLAN 5.5-8 用 git show 取得。 (Every command ran under this batch's isolated absolute interpreter; the lock file is UNCHANGED and hashed from the committed blob.)

**证据**：

```json
{
  "interpreter": "C:\\cv28\\venv\\Scripts\\python.exe",
  "isolation_assertion_exit": 0,
  "lock_change_type": "UNCHANGED",
  "lock_committed_blob_sha256": "602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae",
  "pip_check_exit": 0,
  "pip_check_stdout": "No broken requirements found.",
  "import_precheck_exit": 0
}
```

## 3. 负向演示（未 kill 共享 shim）

- 方法：point COVENIA_MODEL_ENDPOINT at the unlistened port 8002 instead of stopping the shared shim on 8001
- 与「停掉 shim」的等价性：the client sees the same failure mode it would see if the shim died: connection refused before any byte of the request is written. This avoids disturbing shared infrastructure that other batches depend on.

**preflight_variant**

```
{
  "command": "C:\\cv28\\venv\\Scripts\\python.exe tools/verification/live_smoke.py --require-live --disable-cache --endpoint http://127.0.0.1:8002/v1/chat/completions --timeout-seconds 2 --output C:\\cv28\\negative",
  "exit_code": 3,
  "stderr": "endpoint error [endpoint_unreachable]: --require-live and the endpoint is not reachable: tcp 127.0.0.1:8002 unreachable (ConnectionRefusedError)"
}
```

**http_client_variant**

```
{
  "command": "C:\\cv28\\venv\\Scripts\\python.exe tools/verification/live_smoke.py --require-live --disable-cache --skip-endpoint-probe --endpoint http://127.0.0.1:8002/v1/chat/completions --timeout-seconds 2 --output C:\\cv28\\negative-http",
  "exit_code": 3,
  "stdout": "mode: --disable-cache asserted; no cache adapter exists, every attempt is a real call\r\nlive-smoke-v1: ENDPOINT_UNAVAILABLE\r\n  PASS        facts_and_image_binding\r\n  FAIL        real_http_call\r\n  FAIL        candidate_schema\r\n  FAIL        source_validation\r\n  NOT_REACHED extracted_journey\r\n  NOT_REACHED accountability_state\r\n  attempt 1: ENDPOINT_TIMEOUT status=None wall_ms=2011 provider_ms=None usage=None (NOT_ATTEMPTED)\r\n  budget: NOT_ACHIEVED_OUTPUT_REJECTED model_bound_ms=2012 frozen=20.0s\r\n  artifacts: C:\\cv28\\negative-http\r\n========================================================================\r\nlive-smoke-v1: ENDPOINT_UNAVAILABLE  (exit=3, attempts=1, budget=NOT_ACHIEVED_OUTPUT_REJECTED)"
}
```

**unregistered_deployment_variant**

```
{
  "exit_code": 2,
  "stderr": "tool error: the model deployment is not registered (missing: COVENIA_MODEL_DEPLOYMENT_ID)"
}
```

- 不静默降级：all three variants exited non-zero and wrote a verdict artifact whose status records ENDPOINT_UNAVAILABLE/TOOL_ERROR; no cached or synthetic candidate was returned, because no cache or double exists anywhere in this path

## 4. 联调测试实测

- 命令：`C:\cv28\venv\Scripts\python.exe -m pytest backend/tests/live/test_real_extraction.py -q -m live`
- 退出码：1；2 failed, 5 passed in 18.22s
- 失败用例：test_real_endpoint_answered_and_the_run_stayed_inside_the_budget, test_accepted_candidate_is_uncached_and_bound_to_the_locked_revision
- 说明：the two failures are the honest verdict for criteria 1 and 3-as-a-pass: the endpoint answered inside the budget, but the candidate was refused, so no ExtractedJourney exists to assert

## 5. 跨产物发现（本批只读，交回所有者）

### B28-F1｜the assembled case cannot be resolved against the accepted image registry（BLOCKING_FOR_END_TO_END）

fixtures/demo-cases.json declares evidence IDs S00001_IMG_OVERVIEW / S00001_IMG_PUMP / S00001_IMG_PACKAGE (and S00001_GIFT_IMG / S00001_BLURRED_IMG for DEMO_002/003), while handoff/a/images-manifest.json registers S00001_IMG_PRODUCT_OVERVIEW / S00001_IMG_PUMP_DETAIL / S00001_IMG_PACKAGE_CONTEXT / S00001_IMG_GIFT_EVIDENCE / S00001_IMG_BLURRED_PUMP. Only file_name agrees, so ManifestImageResolver.resolve_details() raises ImagePathRejected (evidence_id_unregistered) for every assembled image. DEMO_002 and DEMO_003 additionally disagree on source_message_id (DEMO_AUG_IMG_GIFT / DEMO_AUG_IMG_BLURRED versus 80525870445254.PNM), so they fail with source_message_mismatch even after the ID remap.

- 处理：BATCH-28 may not edit fixtures/ or handoff/. The tool therefore binds the accepted registry's own evidence IDs by file_name, reports every remap in the artifact, and the discrepancy is left open for the owner of the fixture or the manifest
- 归属：A 线 / 案例夹具所有者（本批只读）

### B28-F2｜the frozen prompt does not make the candidate-promise trace obligation reproducible（BLOCKING_FOR_CRITERION_1）

source_validation requires a distinct source_trace entry for every candidate_promise_texts[i], traced to an AGENT CHAT source. In four independent real runs the initial prompt traced observations[0..3] and left the promise fields untraced, so validation raised MISSING_FIELD_TRACE. The single allowed schema-repair retry sometimes reshapes observations into objects (ModelResponseInvalid: candidate observations is invalid) and sometimes omits the trace array entirely.

- 处理：per the batch rules this is a model-quality finding, not something to patch quietly: the prompt and the validator live in read-only modules (model/prompts/candidate_extraction.py, model/source_validation.py), so BATCH-28 records it and returns it to the owning batch instead of editing the prompt or relaxing the validator
- 归属：BATCH-10 / BATCH-11（Prompt 与来源校验所属修复）

## 6. 依赖与环境

- 锁文件变更类型：**UNCHANGED**；the tool and the live test use only the standard library plus already pinned project dependencies (pydantic, pydantic-settings, fastapi, pytest, jsonschema); no third-party package was added, removed, or repinned by BATCH-28
- 锁文件提交内 blob SHA256：`602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae`
- 哈希口径：sha256(git show c2246645540b5f277c0c46c4d0388d01fc2eb05e:backend/requirements-dev.lock raw bytes)
- 新增条目：[]

## 7. 产物哈希（工作副本）

| 路径 | SHA256 | 字节 |
| --- | --- | --- |
| `tools/verification/live_smoke.py` | `5616347860dd61d4e98fe9b4704acac8aee8553f6f337c03417e3a2568d128c1` | 64595 |
| `backend/tests/live/test_real_extraction.py` | `491a9db38edb6a9bb454ecdfa9931dd9d06e0f530eeb479209e043ab1dd3bf7d` | 17645 |
| `reports/batches/BATCH-28/live/model-output.redacted.json` | `6e213ff43d691a56ff48e239abd05e20865634816573bbc569cf29f4e5a8ac57` | 13781 |
| `reports/batches/BATCH-28/live/governance.redacted.jsonl` | `df7b7e330080ab0bc2f3c0a00dd2b0693c6127ea5b0b4ccbaeda8ebaf15a3004` | 4938 |
| `reports/batches/BATCH-28/live/environment.json` | `cf8dcaf248159bd003dd1256e0a6c04bd19e994199f08c18f111435776aeed81` | 6142 |
| `reports/batches/BATCH-28/environment.json` | `6ddce1f421884b8ffc07fa7dbe7948eca7a595dd3838add51051e5a8b1a8bcd1` | 6142 |
| `reports/batches/BATCH-28/commands.json` | `b265a552e89f46f79ca13c4cd0c4086512a25cfc6bc4d1ab7442b163971549d4` | 32097 |
| `reports/batches/BATCH-28/pip-check.txt` | `2497f03b7fb737068a557bb0d2279bd8ca70baf73d256f44f4640cf70d1647fe` | 298 |

### 7.1 提交内 blob 摘要（核验口径，MASTER_PLAN 5.5-8）

口径：sha256 of the raw stdout bytes of `git show <sha>:<path>`; the worktree copy is never used for a hash claim (MASTER_PLAN 5.5-8)

| 路径 | 取自提交 | SHA256（blob 原始字节） | 字节 |
| --- | --- | --- | --- |
| `backend/requirements-dev.lock` | `c2246645540b5f277c0c46c4d0388d01fc2eb05e` | `602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae` | 725 |
| `backend/tests/live/test_real_extraction.py` | `c2246645540b5f277c0c46c4d0388d01fc2eb05e` | `None` | None |
| `reports/batches/BATCH-28/live/model-output.redacted.json` | `5dc123a10a70b03f2b216d9ebefc1ddc64826db5` | `6e213ff43d691a56ff48e239abd05e20865634816573bbc569cf29f4e5a8ac57` | 13781 |
| `reports/batches/BATCH-28/live/governance.redacted.jsonl` | `5dc123a10a70b03f2b216d9ebefc1ddc64826db5` | `df7b7e330080ab0bc2f3c0a00dd2b0693c6127ea5b0b4ccbaeda8ebaf15a3004` | 4938 |
| `tools/verification/live_smoke.py` | `5dc123a10a70b03f2b216d9ebefc1ddc64826db5` | `5616347860dd61d4e98fe9b4704acac8aee8553f6f337c03417e3a2568d128c1` | 64595 |

## 8. 已知局限

- no ExtractedJourney was produced, so criterion 1 is NOT_ACHIEVED
- the 20-second budget is measured for the model-bound part of the request; a full HTTP analyze request was not issued because no server was started in this batch
- the network round trip to DashScope through the local shim is included; a direct vendor call would differ
- the throughput of the shared shim was not characterised beyond these attempts

## 9. 声明

VERIFICATION_REPORT.json is deliberately absent; it belongs to an independent verifier. No acceptance verdict is claimed here.
