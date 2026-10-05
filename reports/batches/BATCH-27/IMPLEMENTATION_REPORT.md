# BATCH-27 implementation report — four-endpoint composition root and startup preflight

**本批由辅助调度器实现，非独立实现方；验收须由他方完成。**

- Status: `IMPLEMENTED (implementation evidence only; not an acceptance verdict)`
- Branch: `codex/covenia-batch-27-aux`
- Base integration SHA: `f259e9b7101172be144f70a46f495593a07754d0`
- Implementation commit: `cb7c30cbcdb9cf91b42daf165a9f5f2d506d218b`
- Interpreter: `C:\cv27\venv\Scripts\python.exe` (isolated venv, Python 3.13.5)
- Dependency lock: **UNCHANGED** (`602C268B684D60E2D1B8BBFC6820663A622EB24093144A87C111F43D3C06FDAE`, empty append diff)
- `VERIFICATION_REPORT.json`: **not written** (verifier-owned)

## What was implemented

- backend/src/covenia_b/runtime.py (new): the single composition root. It injects the process-owned SQLite ledger, clock, model provider, bound image resolver, verified-journey store, metrics sink and workbook-backed case source into the four reviewed router factories, installs CORS and the request-ID trace middleware, and refuses to compose anything other than the frozen four POST routes.
- backend/src/covenia_b/main.py: create_app now returns the composed application (previously an empty scaffold) and python -m covenia_b.main serves it on a loopback-only listener.
- backend/src/covenia_b/settings.py: added the local data paths, model deployment identity, service budgets, listen host/port and the approved CORS origin list; existing field names and defaults are unchanged and no secret is stored.
- backend/src/covenia_b/preflight.py (new): the CLI startup preflight and the route-inventory producer.
- backend/tests/test_composition.py (new): 17 tests over the composed application.

## Mounted endpoints (exactly four business POST routes)

| Method | Path | Handler |
| --- | --- | --- |
| POST | `/api/actions/evaluate` | `evaluate_action` |
| POST | `/api/cases/analyze` | `analyze_case` |
| POST | `/api/events/shipment` | `record_shipment_event` |
| POST | `/api/resolutions/approve` | `approve_resolution` |

The interactive documentation endpoints are disabled by construction (docs_url=redoc_url=openapi_url=None on the application factory), so no fifth business API and no schema UI is served. Setting any of those arguments would re-open them; competition runs keep them closed.

CORS preflight is answered by Starlette's CORSMiddleware before routing, so no OPTIONS route exists in the mounted route table; it is framework behaviour for the four POST routes, not a fifth business API.

## CORS and request tracing

- Allowed origins: http://127.0.0.1:4173, http://localhost:4173, http://localhost:5173 (credentials disabled)
- `X-Request-Id` is normalized once by the transport seam, echoed in the response header and in the envelope, and appended to the JSONL request trace log (`runtime/logs/requests.jsonl`) with method, path and status only.

## Authentication boundary

The competition build has no authentication or authorization boundary. The listener is loopback-only (COVENIA_LISTEN_HOST defaults to 127.0.0.1); any local process that can reach the port may call all four endpoints. Do not expose this process beyond the local host.

## Acceptance commands (exact command, exit code, result)

| # | Command | Exit | Result |
| --- | --- | --- | --- |
| 1 | `C:\cv27\venv\Scripts\python.exe -c "import sys; from pathlib import Path; assert Path(sys.executable).resolve() == Path(sys.argv[1]).resolve() and sys.prefix != sys.base_prefix; print(sys.executable); print(sys.version)" C:\cv27\venv\Scripts\python.exe` | 0 | C:\cv27\venv\Scripts\python.exe | 3.13.5 (tags/v3.13.5:6cb20a2, Jun 11 2025, 16:15:46) [MSC v.1943 64 bit (AMD64)] |
| 2 | `C:\cv27\venv\Scripts\python.exe -m pip install --no-deps -r backend/requirements-dev.lock` | 0 | Requirement already satisfied: wheel==0.45.1 in c:\cv27\venv\lib\site-packages (from -r backend/requirements-dev.lock (line 34)) (0.45.1) |
| 3 | `C:\cv27\venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e backend` | 0 | Successfully installed covenia-b-0.0.0 |
| 4 | `C:\cv27\venv\Scripts\python.exe -c "import pytest, jsonschema; print('pytest/jsonschema import OK')"` | 0 | pytest/jsonschema import OK |
| 5 | `C:\cv27\venv\Scripts\python.exe -m pytest backend/tests/test_composition.py -q` | 0 | 17 passed in 0.94s |
| 6 | `C:\cv27\venv\Scripts\python.exe -m covenia_b.preflight --offline --workbook data/tianchi-track1-mock-data.xlsx` | 0 | preflight: BLOCKED |   routes: reports\batches\BATCH-27\route-inventory.json |
| 7 | `C:\cv27\venv\Scripts\python.exe -m ruff check backend/src` | 0 | All checks passed! |
| 8 | `C:\cv27\venv\Scripts\python.exe -m pip list --format=json` | 0 | 34 distributions |
| 9 | `C:\cv27\venv\Scripts\python.exe -m pip check` | 0 | No broken requirements found. |
| 10 | `git diff --check` | 0 | no output |
| 11 | `git status --short` | 0 | 7 worktree entries |

Raw stdout/stderr and exit codes: `commands.json`.

## Actual preflight output in this environment

```text
preflight: BLOCKED
  READY   workbook
  READY   case_source
  READY   image_manifest
  READY   sqlite
  BLOCKED model
  READY   short_paths
  READY   composition
  BLOCKER model: the model deployment is not registered; analyze will answer MODEL_UNAVAILABLE and no candidate is substituted
  venv longest path: 144 (< 250)
  interpreter: C:\cv27\venv\Scripts\python.exe
  report: reports\batches\BATCH-27\preflight.json
  routes: reports\batches\BATCH-27\route-inventory.json
```

`preflight-variants.json` records the same command with a registered deployment (READY offline) and without `--offline` (BLOCKED: endpoint unreachable), so the model gate is demonstrably real rather than a constant.

## Acceptance-criteria evidence map

### 恰好四个业务 POST 端点；框架文档/OPTIONS 不属于第五业务 API，比赛运行可关闭文档页面。

- route-inventory.json: business_post_routes has exactly four entries (POST /api/cases/analyze, POST /api/actions/evaluate, POST /api/resolutions/approve, POST /api/events/shipment); all_mounted_operations equals the same four.
- runtime.verify_single_composition() raises RuntimeConfigurationError unless the mounted table equals the frozen expectation set, so a fifth route cannot be composed silently.
- The application is constructed with docs_url=redoc_url=openapi_url=None; test_documentation_and_schema_routes_are_closed_at_construction asserts /docs, /redoc and /openapi.json all answer 404.
- OPTIONS is answered by Starlette CORSMiddleware before routing, so the mounted table contains no OPTIONS route; the report states this and the CORS test exercises a real preflight.

### 可启动服务，模型或图片缺失预检明确列阻塞，不静默返回假结果。

- preflight.json in this environment: status BLOCKED with the single blocker 'model: the model deployment is not registered; analyze will answer MODEL_UNAVAILABLE and no candidate is substituted' (missing_settings: COVENIA_MODEL_DEPLOYMENT_ID).
- preflight-variants.json: with COVENIA_MODEL_DEPLOYMENT_ID and COVENIA_MODEL_REVISION registered the same command reports READY offline, and without --offline it reports BLOCKED because the registered endpoint is unreachable -- the model check is a real gate, not a constant.
- test_an_unregistered_model_deployment_is_a_blocker_not_a_substitute: analyze answers 503 MODEL_UNAVAILABLE (retryable) with data=null, no ledger snapshot and an empty verified-journey store.
- Image inputs are checked the same way: the manifest status, the per-image no-PII declaration, file presence and declared sha256/byte length are all blocking checks in check_image_manifest().
- A missing workbook, catalog or image manifest is turned into a typed port error by the lazy adapters instead of a fabricated candidate.

### CORS 允许 127.0.0.1:4173 与批准的 localhost Origin；请求 ID 跨日志可追踪。

- route-inventory.json cors.allowed_origins = ['http://127.0.0.1:4173', 'http://localhost:4173', 'http://localhost:5173'], allow_credentials=false, allow_methods=['POST','OPTIONS'].
- test_cors_preflight_allows_the_approved_origin_and_refuses_another: the approved origin receives access-control-allow-origin and a disallowed origin receives 400 with no allow-origin header.
- test_request_id_is_returned_logged_and_traceable: the client X-Request-Id is echoed in the response header, in the error envelope, and appended to runtime/logs/requests.jsonl; no request body or PII is logged.

### 按5.5使用本批绝对隔离venv解释器；新增第三方依赖只增不改、精确钉版本并提交锁文件差异/原因/hash证据；交付前同解释器 pip check 退出0。

- Interpreter: C:\cv27\venv\Scripts\python.exe; sys.prefix=C:\cv27\venv; include-system-site-packages=false; identity assertion exit 0.
- environment.json: dependency lock status UNCHANGED with identical raw git-blob SHA-256 before and after (602C268B684D60E2D1B8BBFC6820663A622EB24093144A87C111F43D3C06FDAE), an empty append-only diff and a recorded reason; no name==version line was added, removed or re-pinned.
- environment.json: pip check exit 0 ('No broken requirements found.') and pip list --format=json captured with the same interpreter.
- venv longest real path 144 < 250 (MASTER_PLAN 5.5-9), measured by the shared repaired short-path tool inside preflight.json.

No PASS/FAIL is asserted here. Every criterion row above lists implementation evidence only; the independent verifier owns the verdict.

## Known limits and handoff

- backend/tests/test_bootstrap.py::test_application_factory_has_no_business_or_documentation_routes still asserts the pre-composition scaffold (application.routes == []). That file is outside BATCH-27's allowed_paths, so it was not edited and now fails (1 failed, 3 passed). An authorized owner of backend/tests/test_bootstrap.py must re-baseline that assertion; it is a deliberate consequence of composing the four endpoints, not a hidden change.
- Cross-batch evidence gap (not fixable inside this batch's read-only modules): services/analyze.py::_server_image_observations always emits readability='UNKNOWN', and evidence/aggregation.py treats readability != 'HIGH' as missing coverage, so every analyzed case with an evidence image lands on evidence_status=NEED_HUMAN_REVIEW. services/approve.py::_current_fulfillment_candidate requires evidence_status == 'VALID', therefore analyze -> approve -> shipment is not reachable from a real analyze response. The composition test drives approve and shipment from a seeded ledger snapshot (the same technique as the reviewed BATCH-24/26 tests) and does not fake the missing rule. BATCH-19/23 owners must decide the intended production bridge.
- The verified-journey seam is process-owned and in memory: after a restart, analyze must run again before evaluate. The persisted ledger alone cannot supply a verified extraction and this root does not invent one.
- cache_mode other than 'disabled' has no locked ExtractionStore adapter yet, so the composition root records that as a notice and calls the provider directly; it never serves a cached candidate.
- There is no authentication or authorization boundary (competition build); the listener is loopback-only and must not be exposed beyond the local host.
- runtime/covenia.sqlite3 and runtime/logs/requests.jsonl appear as untracked files after a live/preflight run; they are runtime artifacts and are intentionally not committed (.gitignore does not cover the repository-root runtime/ directory).
- reports/batches/BATCH-27/preflight.json is produced by the acceptance command itself, so every run rewrites its generated_at field. A consecutive re-run on this machine differed only in that field (1 insertion / 1 deletion in git diff); route-inventory.json carries no timestamp and is byte-identical across runs. A verifier who re-runs the preflight should therefore expect preflight.json to show as modified, not as a content change.

## Local runbook and demo reset

- Start: `"C:\cv27\venv\Scripts\python.exe" -m covenia_b.main --host 127.0.0.1 --port 8000   # or: "C:\cv27\venv\Scripts\python.exe" -m uvicorn covenia_b.main:app --host 127.0.0.1 --port 8000`
- Preflight: `"C:\cv27\venv\Scripts\python.exe" -m covenia_b.preflight --offline --workbook data/tianchi-track1-mock-data.xlsx`
- Environment variables: COVENIA_MODEL_ENDPOINT (default http://127.0.0.1:8001); COVENIA_MODEL_DEPLOYMENT_ID (empty = unregistered model = analyze 503); COVENIA_MODEL_REVISION; COVENIA_MODEL_PROMPT_VERSION (default candidate-extraction-v1); COVENIA_MODEL_API_KEY (read in runtime, never stored in Settings); COVENIA_SQLITE_PATH, COVENIA_REQUEST_LOG_PATH, COVENIA_WORKBOOK_PATH, COVENIA_DEMO_CASES_PATH, COVENIA_CASE_MANIFEST_PATH, COVENIA_IMAGE_MANIFEST_PATH, COVENIA_IMAGE_EVIDENCE_ROOT; COVENIA_ALLOWED_ORIGINS (comma separated), COVENIA_ALLOWED_ORIGIN; COVENIA_LISTEN_HOST, COVENIA_LISTEN_PORT, COVENIA_DEMO_CLOCK; COVENIA_ANALYSIS_TIMEOUT_SECONDS (<=20), COVENIA_EVALUATE_BUDGET_SECONDS
- Demo reset (offline only): Offline only: stop the process, move runtime/covenia.sqlite3 aside with a timestamped name (or point COVENIA_SQLITE_PATH at a fresh isolated directory), and restart; covenia_b.storage.admin provides local backup/restore. No reset, health or query HTTP endpoint exists, and the route table proves it.
