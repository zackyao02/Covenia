# BATCH-18 SQLite local ledger

Implementation evidence; independent verification and integration remain separate gates.

## Entry points and atomicity

`SQLiteLedgerRepository(absolute_db_path)` implements BATCH-04 `LedgerRepository`.
Use an existing parent directory. Each operation owns/closes its connection. WAL,
`synchronous=FULL`, foreign keys and a 10-second busy timeout are enabled. Schema
initialization is transactional; unidentified or future-version databases are refused.

`save(snapshot, expected_version=...)` supports initialization/re-analysis. Creation
uses snapshot version 0 / expected version None; the repository returns version 1.
Updates carry the current version and increment it. Existing state and audit history
cannot be discarded. Changed state/commitments require an appended audit entry.

Approve/shipment services use `execute(case_id, operation, idempotency_key,
request_body, mutate, event=None, expected_version=None)` with keyword arguments.
Operations are `analyze`, `evaluate`, `approve`, `shipment`. Shipment requires an
`EventRecord` matching its request. The callback receives a detached, locked current
snapshot and returns `Mutation(snapshot, StoredResponse(body, status_code, headers))`.
The service must validate effective requests, business rules and logistics transitions
inside this callback, without network calls or external side effects.

Sequence: `BEGIN IMMEDIATE` → request replay → event replay → optional version/time
guard → callback → response serialization → state/version/audit/event/reply writes
→ COMMIT. Exceptions and pre-commit process death roll back every write. SQLite errors
map to `LedgerUnavailable`; version/time/history errors to `LedgerConflict`.
`IdempotencyConflict` subclasses `LedgerConflict` and exposes `IDEMPOTENCY_CONFLICT`;
HTTP/error-envelope mapping belongs to the service. Callback business exceptions propagate.

Replays return the historical snapshot and first full response, including first
request_id, status and headers. `load(case_id)` returns current state separately.
`load_version`, `audit_history` and `event_history` are local repository methods.

## Version 1 layout

| Table | Primary key | Stored content |
| --- | --- | --- |
| cases | case_id | Current version, high-water mark, snapshot JSON |
| case_versions | case_id, version | Each committed snapshot, including compiled commitments |
| audit_entries | case_id, sequence | Append-only audit JSON and originating version |
| events | case_id, event_id | Digest, original type/time, version, first full response |
| idempotent_requests | case_id, idempotency_key | Operation, digest, version, first full response |

`application_id=0x434F5642`, `user_version=1`; snapshot JSON has `format_version=1`.
Only the request digest is persisted in the idempotency table. IDs remain strings.

## Fingerprints, history and ordering

The authorized task and current plan/package require `(case_id,idempotency_key)`
uniqueness. Operation is included in the SHA-256 digest. Old BATCH-03 docs/semantic
lock still describe endpoint-scoped identity: this known discrepancy is preserved
in the report, with current explicit user authorization governing implementation.
Consumers must use distinct keys across operations.

Request canonicalization uses UTF-8 JSON, sorted object keys, compact separators
and rejects NaN. Arrays, nested business fields and scalar types are retained.
Only top-level request_id / X-Request-Id (case-insensitive) are excluded. The caller
supplies its validated, normalized effective body; storage does not implement Challenge
normalization or fill defaults. Same key/body replays; changed body/operation conflicts.

Independent `(case_id,event_id)` deduplication uses event type and exact UTC timestamp.
Offsets/fractional trailing zeros normalize; precision beyond microseconds is retained.
Lexical leap seconds normalize to the following second. Equivalent event replay under
a new request key stores only an alias to the original response/version, without a
new state/version/audit/event. Replay checks precede current-state guards. The time
high-water mark is the maximum of previous/proposed marks, audit times and event time;
new events/audits cannot regress it. Equal instants are accepted by storage; the service
decides whether the actual state transition is legal.

## Schema compatibility

The clean original tree at bfc1f911 was safely fast-forwarded to authorized
`f507e37d94c0532f377a9475de2129c52f75d584` before implementation. Its terminal receipt
next_update_by can be null. The frozen shared DTO is still non-nullable. Storage-local
`StoredReceipt` / `StoredAccountabilityState` subclasses validate the current schema
and preserve null during snapshot/response round trips; ordinary snapshots retain the
shared DTO. Shared domain, ports and schemas were not edited. Terminal-producing services
must use a schema-compatible model until the domain owner aligns its shared DTO.

## Local backup / restore

Use the consumer's own absolute isolated interpreter. CLI shape:

```text
<absolute-venv-python> -m covenia_b.storage.admin backup --db <absolute-db> --backup <new-absolute-backup>
<absolute-venv-python> -m covenia_b.storage.admin restore --db <absolute-db> --backup <absolute-backup> --before-restore <new-absolute-safety-backup>
```

Parents must exist. Online SQLite backup includes committed WAL data and checks schema,
integrity and foreign keys before no-overwrite publication. Same-file/hardlink aliases
and sidecar destinations are rejected. Existing restore targets require a new safety
backup; stop application writers for maintenance. A private validated backup is attached
read-only and owned rows are replaced in one write transaction. Safety backup is taken
with the target write lock held. Restore failure rolls back original rows. DB files/WAL
sidecars are not deleted/replaced; existing connections remain usable. A new target needs
no safety path. This is local maintenance only; no reset/query HTTP endpoint was added.

## Delivery evidence

38 passing real SQLite adapter tests use synthetic service callbacks. There is no live
model or integrated HTTP claim. Tests occupy only run/b18/t1 and run/b18/t2. The original
Oct 1 final test run is retained rather than repeated during the Oct 2 manual resume.
All 29 existing exact pins were installed from verified compatible cached wheel archives
after two stalled network attempts. No new third-party dependency or lock write occurred.
commands/environment/pip-check/freeze evidence retain prior errors and approved recovery.
Six inaccessible pip temporary directories were preserved, without deletion or ACL changes.
