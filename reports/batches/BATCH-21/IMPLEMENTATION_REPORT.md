# BATCH-21 implementation report

Status: `COMPLETED` implementation evidence only. Commit: `e5bded363a7ededc12ee8451345794eb6c2097d0`.

This batch adds an unregistered, dependency-injected ASGI router factory for `POST /api/cases/analyze`. It validates the frozen request model before invoking the service, uses the existing request-ID seam, envelopes every result, preserves response runtime metrics and cache provenance from the service projection, maps safe model errors, and limits the awaited analysis to 20 seconds.

The six ASGI/TestClient tests pass using labelled transport doubles. They are not real-model tests. The strict contract checker validates 14 schemas and 18 vectors; `pip check` passes in the fresh `C:\r21b\venv` interpreter, created only with `D:\python\python.exe -m venv`. `VERIFICATION_REPORT.json` and verification evidence were intentionally not created because they are verifier-owned and forbidden by this Batch's scope.

---

## Repair addendum (codex/covenia-batch-21-repair-2)

**本批由辅助调度器修复，非独立实现方；验收须由他方完成。**

This addendum is written by the auxiliary dispatcher repair executor. It records a scope-limited repair only; it is not an acceptance conclusion and no PASS is asserted. Independent verification by another party is still required.

### Scope basis

The only repair basis was `reports/batches/BATCH-21/VERIFICATION_REPORT.json` at `031c43d37d170adbcae2ec1c35de8868e6573424` (branch `codex/verify-batch-21-ascii`), specifically its `findings` and `minimal_fix_request`, together with the product-owner repair decision. Nothing else was changed.

Baseline: `35d03b541f3e5d95d253bbeb9c3477812ddf3ea7` (BATCH-21 implementation evidence).
Repair commit: `69ba7d9a22f3079104ece8e73595f6de28e92a46` — `fix(analyze): validate response contract at the HTTP boundary`.

### What changed

`create_analyze_router` no longer forwards `result.to_contract()` to the client unchecked. The exact payload is now re-validated against the locked `analyze-case-response.schema.json` at the HTTP boundary using the already-present `covenia_b.domain.validation.validate_contract_payload` helper. A projection outside the contract raises `ContractValidationError` (a `ValueError` subclass), which the pre-existing handler already maps onto the existing safe `INTERNAL_ERROR` envelope: HTTP 500, `data: null`, `error.retryable: false`, fixed message, no validation detail and no invalid payload in the response.

No error code was invented, no contract or schema was touched, no dependency was added, and no route registration or `main.py` wiring was introduced.

### Finding-by-finding outcome

1. **Response-schema boundary (formal FAIL item) — repaired.** A pre-fix ASGI probe returned HTTP 200 with `{"data":{"transport_double":true},"error":null}`; the identical post-fix probe returns HTTP 500 with `{"data":null,"error":{"code":"INTERNAL_ERROR","message":"analysis response could not be safely serialized","retryable":false}}`. A negative regression test,
   `test_schema_invalid_service_response_becomes_safe_internal_error` in `backend/tests/api/test_analyze.py`, pins this behaviour. Its positive control uses the locked BATCH-03 vector `analyze-live-success` (`tests/contract-vectors/analyze.json`), so the positive path also exercises a genuinely schema-valid payload. With the new validation call temporarily replaced by a no-op the test failed with `assert 200 == 500` (`1 failed, 6 passed`); the call was restored and the suite re-ran green.
2. **Missing BATCH-20 integration receipt — out of scope, not addressed.** That artifact is coordinator/integration-owned (`runs/{run_id}/integration-receipts/BATCH-20.json`) and lies outside this batch's `allowed_paths`. It must be produced by the coordinator, not by this repair.

### Commands and results (interpreter `C:\cv21r\venv\Scripts\python.exe`, `TEMP=TMP=C:\cv21r\tmp`)

| Command | Exit | Result |
| --- | --- | --- |
| interpreter identity assertion | 0 | `C:\cv21r\venv\Scripts\python.exe`; CPython 3.13.5; isolated |
| `-m pip install --no-deps -r backend/requirements-dev.lock` | 0 | pinned distributions installed |
| `-m pip install --no-deps --no-build-isolation -e backend` | 0 | `covenia-b-0.0.0` editable |
| `-c "import pytest, jsonschema"` | 0 | import OK |
| `-m pytest backend/tests/api/test_analyze.py -q` | 0 | **7 passed** (6 pre-existing + 1 new negative regression) |
| `tools/contracts/check_contracts.py --strict` | 0 | 14 schemas, 18 vectors |
| `-m pip list --format=json` | 0 | 34 distributions |
| `-m pip check` | 0 | No broken requirements found. |
| `ruff check` + `ruff format --check` (both changed files) | 0 | clean |
| `git diff --check` | 0 | clean |
| `git status --short` | 0 | only the two allowed code/test paths before the repair commit |

Supplementary: `-m pytest backend/tests -q --import-mode=importlib` → 436 passed, exit 0. The default import mode aborts during collection because `backend/tests/api/test_analyze.py` and `backend/tests/services/test_analyze.py` share a basename; both files exist unchanged at the baseline commit, so this is a pre-existing repository condition and not a repair regression.

### Dependency lock

`backend/requirements-dev.lock` is **UNCHANGED**: the raw git blob SHA-256 is `602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae` both before and after, identical to the hash recorded by the verifier. The baseline branch additions (`certifi==2025.1.31`, `httpcore==1.0.7`, `httpx==0.28.1`) are preserved. No line was appended, removed, or re-pinned.

### Artifact hashes at the repair commit (raw git blob bytes)

| Path | SHA-256 | Bytes |
| --- | --- | --- |
| `backend/src/covenia_b/api/analyze.py` | `c8be83123f190c664ca558a194bbbe7ef3155474481b99ecd2f897fb8463a55b` | 5243 |
| `backend/tests/api/test_analyze.py` | `4715de4fc93fa6b96d7589c8a9a3f3774869430c84f7b034fd61d6372b8d7532` | 7812 |
| `backend/requirements-dev.lock` | `602c268b684d60e2d1b8bbfc6820663a622eb24093144a87c111f43d3c06fdae` | 725 |

This checkout materializes CRLF, so the worktree files hash differently from the LF blobs; the worktree SHA-256 values are recorded in `IMPLEMENTATION_REPORT.json` for a verifier who hashes the working files directly.

### Remaining state

The repaired code, the negative regression test, this report, `commands.json`, `environment.json` and `pip-check.txt` are the complete deliverable. `VERIFICATION_REPORT.json`, verification evidence, and any PASS/FAIL conclusion remain owned by an independent verifier; none was written or implied by this repair.
