# BATCH-06 implementation report

Status: `COMPLETED` / `IMPLEMENTED`.

The implementation commit is `652994839aedf6416b0919473a105d1049e2044d` on `codex/batch-06-case-input`, based on `integration/covenia-b@948bc416788a698d364f916c895f692489e45f99`.

It adds a data-driven case catalog and session-first assembler. Competition messages, orders, and all five ticket-sheet categories are read from BATCH-05 normalized workbook records; the accepted A fixture supplies only directory, augmentation, image, and declared-scope metadata. The assembler validates source-session/order/ticket relations, excludes post-evaluation facts, validates the locked CaseInput Schema, and produces an explicit diagnostic instead of fabricating a P0 input.

Evidence produced:

- `case-input.redacted.json` contains schema-valid redacted outputs for the three catalog cases, including S00001 with order `6920185815517983396` and ticket `BH919209358357`.
- `association-trace.json` records source coordinates and source kinds without raw conversation text; it reports 138 source-session importability outcomes, with one catalog-backed P0-ready source session.
- Unit tests cover aliases, reversed order/ticket relations, temporal filtering, all five ticket sheets, schema validation, redaction, and diagnostics.

Final implementation tests: 7 focused tests and 81 backend tests passed. Ruff passed, `pip check` passed, and no dependency was added or lock-file entry changed.

`fixtures/**` and `handoff/a/**` remained read-only. Ground truth and frontend prefill examples were not used as backend facts. This is not independent verification or an integration receipt; no later Batch was started.
