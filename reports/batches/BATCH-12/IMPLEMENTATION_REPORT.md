# BATCH-12 implementation report

## Result

`IMPLEMENTED` — implementation-side result only. This report is not an independent verification PASS and does not unlock BATCH-14 or any other consumer.

The new pure `aggregate_evidence()` function compares the frozen scope sequence (`order_id`, `sku_id`, `fulfillment_item_id`, `issue_type`) before aggregating structured image observations. It returns `VALID`, `MISMATCHED`, or `NEED_HUMAN_REVIEW`, together with ordered scope traces and matched, missing, mismatched, and conflicting source IDs.

The decision table requires reliable compatible coverage for product identity, affected component, and damage detail. Explicit scope, SKU, role, or component changes yield `MISMATCHED`; conflicting, internally inconsistent, unreadable, incomplete, or unknown facts yield `NEED_HUMAN_REVIEW`. Candidate IDs, evidence-valid declarations, file names, confidence, and hygiene signals do not determine status. `ADVERSE_REACTION` remains a scope fact for the later H1 rule; this module does not make a medical conclusion.

## Verification performed

- `C:\\cov-run\\batch-12\\venv\\Scripts\\python.exe -m pytest backend/tests/evidence -q` — `16 passed in 0.51s`
- `C:\\cov-run\\batch-12\\venv\\Scripts\\python.exe -m ruff check backend/src/covenia_b/evidence backend/tests/evidence` — passed
- `C:\\cov-run\\batch-12\\venv\\Scripts\\python.exe -m pip check` — no broken requirements
- Isolated venv preflight passed: longest venv path is 156 characters, below 250; no dependency or lock-file change was needed.

## Scope and handoff

The code/test commit is `5b150e669c089aff0c410adabf16f16aaa82b20c`. Only allowed evidence source/test paths and this batch's implementation artifacts changed. No API, schema, domain/port, frontend, fixture, plan, model, notification, or external state changed.

Use [evidence-truth-table.json](evidence-truth-table.json) for the exact combination policy and [scope-traces.json](scope-traces.json) for representative traces. Independent verification and coordinator integration/retest remain required.
