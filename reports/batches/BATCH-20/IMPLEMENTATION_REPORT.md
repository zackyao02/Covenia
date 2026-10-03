# BATCH-20 implementation report

Status: `IMPLEMENTED_PENDING_INDEPENDENT_VERIFICATION`.

Implementation code commit: `4140835c03a0b80d24b1220c92d62f061feda109` on `codex/covenia-batch-20`, based on `integration/covenia-b` at `16ee07cb4553ddaad74d0dc54323867c55095923`.

## Delivered behavior

`covenia_b.cache.CachingExtractionProvider` decorates only the model-extraction port. It always invokes the upstream provider first and may read an `ExtractionStore` only after `ModelUnavailable`. Its opaque key covers normalised safe text, resolved image content hashes, source/scope facts, model revision, prompt version, schema version, and policy version.

Only a schema-valid, source-valid, version-matching, non-PII `CandidateExtraction` can be stored. It does not cache `AnalyzeCaseResponse`, a decision, a responsibility/ledger snapshot, deadlines, human edits, or shipment events. A fallback keeps the source extraction's `run_id`, sets `cached_result=true`, and writes a redacted relation to the current request before returning the candidate. BATCH-19's downstream orchestration therefore remains responsible for recomputing all live state.

`LIVE` mode forcibly disables both cache reads and writes. Cold/mutated/unsafe/incompatible cache conditions are explicit failures rather than substituted content.

## Implementation evidence

- `pytest backend/tests/cache -q`: 17 passed.
- `ruff check backend/src/covenia_b/cache backend/tests/cache`: passed.
- Isolated short-path CPython 3.13.5 venv: `pip check` passed.
- No third-party dependency or `backend/requirements-dev.lock` change.

See [cache-invalidation-matrix.json](cache-invalidation-matrix.json), [fallback-governance.redacted.jsonl](fallback-governance.redacted.jsonl), [commands.json](commands.json), [environment.json](environment.json), and [pip-check.txt](pip-check.txt).

This is implementation evidence only. No `VERIFICATION_REPORT.json`, independent verdict, integration receipt, or integration smoke result was produced.
