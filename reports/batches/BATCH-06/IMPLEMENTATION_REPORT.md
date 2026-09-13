# BATCH-06 implementation report

Status: `COMPLETED` / `IMPLEMENTED`.

The implementation commit is `652994839aedf6416b0919473a105d1049e2044d` on `codex/batch-06-case-input`. This report-evidence repair is based on `integration/covenia-b@78f7754233ed430254043f8548ccb2e08eebbd13`; it changes no business code, tests, schemas, fixtures, locks, plans, gate records, or verifier-owned evidence.

## Provenance repair

`plan_sha256` is computed over the raw plan blobs obtained with `git show <review SHA>:MASTER_PLAN.md` and `git show <review SHA>:batches.json`, never working-copy bytes. The blobs inherited unchanged from `78f7754233ed430254043f8548ccb2e08eebbd13` are:

- `MASTER_PLAN.md`: 210264 bytes, SHA-256 `DAAE3CCF0A11710BFE5B48098AC9668CBD0AFBFEA63C66B74EDFF57C94885A5A`
- `batches.json`: 202033 bytes, SHA-256 `1E711436F72BD9946052ABE9D120E13B199028FFA9D3795C1382308B8247EEB6`

The required X-A-FIXTURES gate is sourceably recorded as `ACCEPTED` in [`reports/batches/X-A-FIXTURES/GATE_ACCEPTANCE_RECEIPT.json`](../X-A-FIXTURES/GATE_ACCEPTANCE_RECEIPT.json) at `integration/covenia-b@78f7754233ed430254043f8548ccb2e08eebbd13`, accepted by `产品负责人` on `2026-09-13`. Its Git-blob evidence is:

- `fixtures/demo-cases.json`: 10588 bytes, SHA-256 `AE06EC6EF7D2DB344B8F57820B2D549CACE662EEFCD2F31BFF0C65D74E658707`
- `fixtures/ground-truth.json`: 3312 bytes, SHA-256 `0E6E8170FC7B113EE700087289B027FE93D412AA18C2F39D64D80D01C57C3311`
- `handoff/a/cases-manifest.json`: 11957 bytes, SHA-256 `4169EFF9CF424271381046A32B36B5617A015C03BDB847F704C55CAA0E1641F6`

The earlier receiving-side registration transcribed `0E6E817FC7...` as a 63-character value and omitted one `0`; the delivered artifact was not modified.

It adds a data-driven case catalog and session-first assembler. Competition messages, orders, and all five ticket-sheet categories are read from BATCH-05 normalized workbook records; the accepted A fixture supplies only directory, augmentation, image, and declared-scope metadata. The assembler validates source-session/order/ticket relations, excludes post-evaluation facts, validates the locked CaseInput Schema, and produces an explicit diagnostic instead of fabricating a P0 input.

Evidence produced:

- `case-input.redacted.json` contains schema-valid redacted outputs for the three catalog cases, including S00001 with order `6920185815517983396` and ticket `BH919209358357`.
- `association-trace.json` records source coordinates and source kinds without raw conversation text; it reports 138 source-session importability outcomes, with one catalog-backed P0-ready source session.
- Unit tests cover aliases, reversed order/ticket relations, temporal filtering, all five ticket sheets, schema validation, redaction, and diagnostics.

Final implementation tests: 7 focused tests and 81 backend tests passed. Ruff passed, `pip check` passed, and no dependency was added or lock-file entry changed.

`fixtures/**` and `handoff/a/**` remained read-only. Ground truth and frontend prefill examples were not used as backend facts. This is a report-evidence repair, not independent verification or an integration receipt; the original tests and probes were not rerun here and await fresh independent review of the new review SHA. No later Batch was started.
