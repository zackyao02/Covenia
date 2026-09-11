# B transport contract — BATCH-03

Contract version: `8314c76502cbc9d47d8432b7fe53f7d9fb82de82 / BATCH-03 contract-lock-v1`.
This is a machine-contract artifact, not a business-service implementation or
an independent verification result. There remain exactly four business POST
interfaces.

| Interface | Request schema | 200 `data` schema | Non-200 result |
|---|---|---|---|
| `POST /api/cases/analyze` | `analyze-case-request.schema.json` | `analyze-case-response.schema.json` | `ApiEnvelope` error |
| `POST /api/actions/evaluate` | `evaluate-action-request.schema.json` | `decision-result.schema.json` | `ApiEnvelope` error |
| `POST /api/resolutions/approve` | `approve-resolution-request.schema.json` | `approve-resolution-response.schema.json` | `ApiEnvelope` error |
| `POST /api/events/shipment` | `shipment-event-request.schema.json` | `shipment-event-response.schema.json` | `ApiEnvelope` error |

Every response is the strict `api-envelope.schema.json` shape. A 200 has a
non-null `data` and `error: null`; an error has `data: null`. In particular,
`E0_NO_RULE_MATCHED` is a 200 `ALLOW` result, while a P0 prohibition is
`400 / P0_PROHIBITED_ACTION` and has no successful `DecisionResult` body.

## Trusted-input and Challenge boundary

`evaluate` first normalizes `challenge_mode` to `false` when absent. When it
is false, it discards `challenge_overrides` before inspecting its nested shape
and ignores the five compatibility fields: `accountability_state`,
`evidence_status`, `active_commitments`, `prohibited_actions`, and
`current_scope`. The response echoes `challenge_mode: false` and must have the
same `data` as the corresponding request without those ignored fields.

Only an explicit `challenge_mode: true` validates and applies the restricted
override shape. The server then loads case facts and derives all rule inputs;
it does not take a client-supplied state, evidence status, responsibility, or
prohibited action as truth. This is the A21/A34 boundary, not a new endpoint.

`analyze` accepts only its existing case input shape. Any candidate produced by
the model is non-authoritative: the model may supply observations, source
references, time expressions, and conditions, while the server enriches the
public journey and alone derives evidence, commitment class, activation,
responsibility, rule decision, and final resolution.

## Approval, clock, notification, and replay semantics

- `approve` revalidates `candidate_type` against current server facts. A stale
  candidate, unknown case, missing/empty approver, or invalid allowed edit is
  `400 / VALIDATION_ERROR`, with no partial write.
- The trusted, timezone-aware server clock creates `approved_at`. It is exposed
  by the `at` field of the `RESOLUTION_APPROVED` audit entry, not as a
  client-writable request field or a new top-level response field.
- A shipment event carries timezone-aware `event_time`, which cannot regress
  below the event high-water mark. `event_id` is independently deduplicated by
  `(case_id, event_id)`; a different event with the same identity is
  `409 / IDEMPOTENCY_CONFLICT`.
- The replay key is `(case_id, endpoint, idempotency_key)` plus a normalized
  request-body digest that excludes `X-Request-Id`. Matching replays return the
  first complete response and its first request ID without another audit entry.
- A proactive notification is a response-only draft with
  `requires_human_approval: true`. Until a C-owned local confirmation is
  recorded, it does not enter the consumer-visible receipt. Its
  `commits_next_update_at` equals both `open_obligation.next_check_at` and
  `service_progress_receipt.next_update_by`.

## C and A synchronization handoff

No C or A file was edited by BATCH-03. Their external gates remain truthful:
`X-C-CONTRACT`, `X-C-UI`, `X-A-FIXTURES`, and `X-A-IMAGES` are not accepted by
this contract artifact.

| Owner | Exact pending file(s) | Contract-vector source to consume |
|---|---|---|
| C | `frontend/src/api/contracts.ts` | `tests/contract-vectors/analyze.json`, `evaluate.json`, `approve.json`, `shipment.json` |
| C | `frontend/src/api/examples/01-analyze-case.json` | `tests/contract-vectors/analyze.json` |
| C | `frontend/src/api/examples/02-evaluate-action.json` | `tests/contract-vectors/evaluate.json` |
| C | `frontend/src/api/examples/03-approve-resolution.json` | `tests/contract-vectors/approve.json` |
| C | `frontend/src/api/examples/04-shipment-event.json` | `tests/contract-vectors/shipment.json` |
| A | `fixtures/demo-cases.json` and `fixtures/ground-truth.json` remain A-owned | No BATCH-03 vector may rewrite or substitute their facts; consume only after A's own gate and acceptance evidence exist. |

C must synchronize the two D04 action types, A34 normalisation, required cache
visibility, the two new success-data schemas, audit-based `approved_at`, and
the error/replay mappings above, then issue its own signed `X-C-CONTRACT`
handoff. A remains responsible for the approved fixture/ground-truth alignment
and does not acquire a B-generated substitute from these synthetic vectors.
