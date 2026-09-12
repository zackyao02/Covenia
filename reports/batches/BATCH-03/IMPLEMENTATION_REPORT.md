# BATCH-03 dependency remediation implementation report

Status: `COMPLETED` for the authorized dependency repair. This is an implementation record, not independent verification or an acceptance PASS.

The BATCH-03 strict checker imports `jsonschema` and `referencing`, while the 24-line `backend/requirements-dev.lock` did not pin that dependency closure. In a new, isolated BATCH-03 venv, `jsonschema==4.25.0` added exactly five freeze-measured pins:

- `attrs==26.1.0`
- `jsonschema==4.25.0`
- `jsonschema-specifications==2025.9.1`
- `referencing==0.37.0`
- `rpds-py==2026.6.3`

They were appended in alphabetical order. All 24 original pins are text-identical; the lock diff is additions only. `pip check` reports no broken requirements. The venv information and before/after freeze evidence are in `reports/batches/BATCH-03/evidence/`.

Byte-level lock evidence is recorded in `reports/batches/BATCH-03/evidence/lock-diff.txt`. For the base commit `ff4f2a99caeb4d820749c2d0ae6fa5431dafef4d` and after commit `6a726b8e6c781dfd723aa5d542e2ce1bad324494`, the named `sha256_git_blob_lf` values are respectively `A35011CDECBC6ED34EEB2CD7130650BDE531F902BF8839890FB3A02A6421CA55` and `177865457F146985726B02EF5C640363624E2A0C9B76B67FBED3929DADA13D04`; the named `sha256_worktree_crlf` values are respectively `088E3DEF0F1F4ECED2D3B0A5B50DBA4065A86E01286497517D3FF13E79682C7F` and `886A9FC311F16DA186158EFF8478F3058FF8E0AEFA00091830BBF87863CD0C5D`. There is no unqualified single `sha256_after`: the evidence states the byte representation and calculation method for each value.

No tools, schemas, vectors, tests, assertions, business files, third-party business semantics, plans, contracts, or verifier-owned artifacts changed. `VERIFICATION_REPORT.json` and `verification-evidence/**` remain untouched.

The live `MASTER_PLAN.md` and `batches.json` SHA-256 values observed at the delegated base differ from the historical values supplied in the delegation; this remediation neither changes nor resolves that provenance discrepancy.

The same venv re-ran the strict contract checker successfully (14 schemas, 18
vectors) and contract pytest successfully (16 progress markers, exit 0).

Remaining gate: independent BATCH-03 verification is still `NOT_RUN`.
