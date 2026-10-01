# BATCH-18 implementation handoff

Result: **IMPLEMENTED** (implementation only; independent verification pending).

Code/test commit: `3712a170969998e32b56d33e3d59c7b21a04f19d`. Original branch `codex/covenia-batch-18`, schema baseline `f507e37d94c0532f377a9475de2129c52f75d584`.
Report-only commit: obtain the delivery HEAD from the final Git handoff; code_commits deliberately identifies the code/test commit only.

SQLite schema/versioned snapshots, append-only audit/history, case-scoped request fingerprints and first complete responses, independent event deduplication/high-water marks, serialized callback transactions, rollback/restart recovery, and the local backup/restore CLI are implemented. No HTTP reset endpoint or new third-party dependency was added.

Retained functional test: **38 passed**, exit 0, executed 2026-10-01 23:12 +08:00. The Oct 2 manual continuation preserves that run and does not reimplement/retest SQLite. Delivery ruff passed after regular approval of the same command that failed under the normal sandbox.

All nine acceptance commands have recorded successful outcomes. Lock installation recovered using the 29 previously cached compatible exact-pin wheels after two retained stalled attempts. Every old pin matches freeze-before, freeze-after and installed metadata. Lock raw Git-blob SHA-256 is unchanged: `177865457F146985726B02EF5C640363624E2A0C9B76B67FBED3929DADA13D04`. Freeze adds only the local editable project. The conditional dependency lock was not acquired/activated; lockfile stayed read-only.

Environment: `C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\run\b18\venv\Scripts\python.exe`; RUN_DIR length 46, venv one level deep, longest path **183 < 250**; CPython 3.13.5 / SQLite 3.49.1; no system/user site or PYTHONPATH. Retained pip check exit 0: “No broken requirements found.”

BATCH-04 PASS/integration receipt and code ancestry are verified. The accepted f507e37 terminal-null schema change is present in this existing worktree. Current integration cc82915b adds only BATCH-09 observability/evidence; it does not overlap this delivery, and this task performed no new integration.

Two consumer boundaries need attention: the explicitly authorized case-scoped key differs from older BATCH-03 endpoint-scoped prose; and storage-local schema-compatible subclasses preserve terminal null while the shared DTO still needs owner alignment. Services must validate requests/business rules/transitions inside the callback. See storage-layout.md.

No Hero rule or model behavior was changed; this module supplies persistence for later services. There is no claim of live inference, HTTP integration, or end-to-end acceptance.

Six unreadable pip temporary directories remain intact. Their Permission denied warnings, the normal-sandbox ruff failure, the approved recovery, and the Oct 1 platform quota error/retry time (Oct 2 03:29) are retained. Actual quota restoration time and unknown prior automatic-resume count remain null. No directory cleanup, ACL change, run-state modification, push/main operation, verifier report, or subsequent Batch was performed.

All 23 template fields are present in IMPLEMENTATION_REPORT.json, plus resume_history as the 24th field. commands.json, environment.json, pip-check.txt, transaction-replay-evidence.json, storage-layout.md and resume-evidence.json hold detailed handoff evidence. Raw Git-blob hashes cover code, dependency and evidence artifacts; the report files exclude themselves to avoid self-reference.

Remaining gates: independent BATCH-18 verdict, then coordinator integration receipt/smoke. This report does not authorize downstream work.
