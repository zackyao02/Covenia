# BATCH-21 implementation report

Status: `COMPLETED` implementation evidence only. Commit: `e5bded363a7ededc12ee8451345794eb6c2097d0`.

This batch adds an unregistered, dependency-injected ASGI router factory for `POST /api/cases/analyze`. It validates the frozen request model before invoking the service, uses the existing request-ID seam, envelopes every result, preserves response runtime metrics and cache provenance from the service projection, maps safe model errors, and limits the awaited analysis to 20 seconds.

The six ASGI/TestClient tests pass using labelled transport doubles. They are not real-model tests. The strict contract checker validates 14 schemas and 18 vectors; `pip check` passes in the fresh `C:\r21b\venv` interpreter, created only with `D:\python\python.exe -m venv`. `VERIFICATION_REPORT.json` and verification evidence were intentionally not created because they are verifier-owned and forbidden by this Batch's scope.
