# BATCH-23 implementation

Result: `IMPLEMENTED_AWAITING_INDEPENDENT_VERIFICATION`.

Code commit: `99c661abd63973cb590f5fa4ff717b72e6e328b0` on `codex/covenia-batch-23`, based on `integration/covenia-b` `16ee07cb4553ddaad74d0dc54323867c55095923`.

The new `ApprovalService` revalidates the requested candidate from the current ledger snapshot inside the BATCH-18 transaction callback. It only accepts a nonblank approver and the approved `executor`, `next_check_at`, and `recovery_if_missed` human edits. Responsibility, financial outcomes, arbitrary state, and client-generated approval timestamps are absent from the accepted request contract and are rejected at the service boundary.

For a legal fulfillment approval, the service records the Clock-derived approval audit, updates the obligation and stored compiled responsibility, and uses the BATCH-17 projector to synchronize receipt and pending notification-draft times. The draft is human-gated and never sent. The first complete success envelope is persisted with the snapshot; same-body replays return its original request ID, while same-key body changes conflict without mutation.

Evidence run with the batch-exclusive isolated venv:

- `pytest backend/tests/services/test_approve.py -q` — 11 passed.
- `ruff check` for the two changed source paths — passed.
- `pip check` — passed.

No third-party dependency was added. No `VERIFICATION_REPORT.json`, verifier evidence, integration receipt, push, main change, or downstream Batch was created. This is implementation evidence only; independent verification and coordinator integration remain required.
