# BATCH-24 implementation report

Implemented `POST /api/resolutions/approve` as a transport adapter over one injected `ApprovalService`.

The route parses its own JSON body so missing or blank `approver_id` maps to the frozen `400 VALIDATION_ERROR` envelope, rather than FastAPI's default 422. It rejects schema-invalid edits at the boundary, maps candidate validation to 400, idempotency conflicts to 409, and safe transaction/infrastructure failures to retryable 503. It returns the persisted first envelope on replay and does not create a client-side resolution or treat a failed transaction as approved.

The allowed-path API tests execute requests through ASGI without an unpinned HTTP-client dependency. They cover validation, stale candidate, replay with a changed `X-Request-Id`, conflict, and `LedgerUnavailable` failure behavior.

Implementation checks passed: 4 targeted tests, Ruff, strict contract checking (14 schemas / 18 vectors), and isolated-venv `pip check`. This is implementation evidence only; it is not an independent verification result.

Runtime composition is intentionally handed off: call `install_approve_router(app, approval_service=...)` once from an authorized application-composition change. `main.py` is outside this batch's allowed paths.
