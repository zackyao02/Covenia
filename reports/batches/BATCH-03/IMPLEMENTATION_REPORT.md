# BATCH-03 F-B03-001 repair implementation report

Status: `COMPLETED` (implementation repair only; not independent verification)

Repair code commit: `e5cda914877321a2424627be5cc885ac59a00975`

This repair changes only the approved D03 repeated-evidence contract. A same-scope
`ASK_EVIDENCE` now returns HTTP 200 with a `DecisionResult` of
`INTERVENE / E1 / 300`. `ASK_SAME_EVIDENCE` remains a display-only prohibited
item and does not independently cause `P0_PROHIBITED_ACTION`.

The strict checker directly reads approved D03, the locked firewall statement,
and `evaluate-d03-repeat-evidence-e1`; it rejects a regression to HTTP 400.
The P0 precedence vector now uses the actual
`SHIFT_FOLLOW_UP_TO_CONSUMER` prohibited action against H1.

Required checks: strict contract check, JSON formatting, diff check, and the
post-code-commit status check passed. The exact default pytest command could
not run because `D:\python\python.exe` lacks `pytest`; F-B03-002 remains
an out-of-scope reproducibility risk and no dependency lock was changed.

No business service, route, frontend file, fixture, docs/02 file, approval
record, dependency lock, independent verification report, or verifier evidence
was changed. A coordinator must create a fresh independent BATCH-03 verifier
for the repair commit.
