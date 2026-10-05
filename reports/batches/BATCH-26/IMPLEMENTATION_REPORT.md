# BATCH-26 implementation report — shipment HTTP transaction endpoint

**本批由辅助调度器实现，非独立实现方；验收须由他方完成。**

## What was implemented

`POST /api/events/shipment` now has a real write boundary:

- `backend/src/covenia_b/services/shipment.py` — `ShipmentEventService` binds one validated request to one BATCH-18 serialized transaction. The idempotency lookup, the `event_id` identity lookup, the pure reducer call, the audit append, the ledger write, and the first-response persistence all commit or roll back together. The persisted ledger snapshot is converted back into the reducer's `ShipmentLedger` (state contract, event high-watermark, derived existing ticket id); no client-supplied status, milestone, receipt, or candidate value is trusted.
- `backend/src/covenia_b/api/shipment.py` — `create_shipment_router` / `install_shipment_router` own HTTP parsing and the frozen envelope only. Schema-invalid bodies become `SCHEMA_INVALID`/400, reused keys and reused `event_id` with different content become `IDEMPOTENCY_CONFLICT`/409, illegal or out-of-order events become `INVALID_EVENT_TRANSITION`/409, and ledger unavailability becomes a retryable `INTERNAL_ERROR`/503.
- Terminal compatibility reuses the existing storage codec rule for a delivered shipment whose `next_update_by` is `null`; no schema, domain, port, storage, or settings file was touched.

Replays return the first persisted envelope verbatim, including its original `request_id`. A retry with a different `X-Request-Id` therefore cannot grow the audit trail or re-decide the event.

## Acceptance criteria mapping (implementation evidence, not a verdict)

1. **Two independent legal sequences** — `SHIPMENT_NOT_PICKED_UP 09:30 → SHIPMENT_PICKED_UP 10:06 → SHIPMENT_DELIVERED 11:00` (on-track → in transit with a 10:36 commitment → resolved/terminal) and `SHIPMENT_PICKED_UP 09:40 → SHIPMENT_DELIVERED 10:10` (keeps the later 10:05 check → resolved) both pass over the real HTTP boundary, with per-step status, milestone, receipt, draft, and audit evidence recorded in `shipment-http-sequences.json`.
2. **Reproducible rejection vectors** — direct delivery (409 with the frozen message and zero partial writes), reverse order (409, unchanged counters and watermark, first response still replayable), same `event_id` with different content (409), repeated key with new content (409, first body preserved), concurrency (two threads: one transition, identical bodies, one shared `request_id`), and fault rollback (missing ledger 409 with no row, injected `LedgerUnavailable` 503 retryable, injected `LedgerConflict` 409).
3. **Replay stability** — three separate tests assert that a replay returns the identical first envelope and `request_id` while the audit trail, row counts, and ledger version stay unchanged, including after the shipment is terminal.
4. **Environment and dependency discipline** — every command used `C:\cv26\venv\Scripts\python.exe` with `sys.prefix != sys.base_prefix` and `include-system-site-packages=false`; `backend/requirements-dev.lock` is `UNCHANGED` (raw git-blob SHA-256 `177865457F…3D04`, empty append diff); the same interpreter's `pip check` exited 0 (`pip-check.txt`); RUN_DIR is the 7-character path `C:\cv26` with `venv` directly beneath it and a 144-character longest venv path.

## Recorded commands (all exit 0)

Interpreter isolation · pinned lock install · editable install · `import pytest, jsonschema` · `pytest backend/tests/api/test_shipment.py -q` (10 passed) · `tools/contracts/check_contracts.py --strict` (14 schemas / 18 vectors) · `pip list --format=json` (31 distributions) · `pip check` · anti-shortcut scan (no hits) · Ruff · `git diff --check` · `git status --short` · lock blob SHA-256 probe. Raw transcript: `command-log.txt`; machine-readable summary: `commands.json`.

A supplementary per-directory regression run passed for every backend test directory (api 17, cache 17, commitments 15, contracts 16, domain 23, evidence 16, images 14, importing 14, model 27, observability 10, privacy 24, receipts 15, resolutions 7, rules 155, services 17, shipments 13, state 4, storage 38, bootstrap 4).

## Known limits and handoff

- `main.py` is outside this batch's allowed paths, so the application factory still installs only the transport seams. An authorized composition change must call `install_shipment_router(app, shipment_service=ShipmentEventService(repository=...))` once with a process-owned repository.
- Durable `event_id` replay belongs to the storage layer, so the reducer's in-memory replay path is intentionally not exercised through this service.
- `pytest backend/tests` over the whole tree still fails at collection time from a pre-existing duplicate module basename (`tests/api/test_approve.py` vs `tests/services/test_approve.py`); both files are unmodified and the per-directory runs are unaffected.
- Write scope stayed inside `backend/src/covenia_b/services/shipment.py`, `backend/src/covenia_b/api/shipment.py`, `backend/tests/api/test_shipment.py`, and `reports/batches/BATCH-26/**`. No `VERIFICATION_REPORT.json` and no `verification-evidence/**` were created.
