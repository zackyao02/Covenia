# Covenia B module ports

This document records the BATCH-04 ownership boundary for the public domain
types and module ports. It does not add an endpoint, business rule, provider,
or persistence implementation. The locked contract source is
`docs/contracts/b-contract-lock.json` at integration commit
`853f1bcb746050f0ee421cd499e1836843176894`.

## Public contract entry points

`covenia_b.domain.types.SchemaBackedModel.from_contract()` validates incoming
data against its locked Draft 2020-12 schema before parsing. `to_contract()`
serializes the typed model and validates it again. This is the required
bidirectional boundary for consumers; normal `model_validate()` is useful for
trusted in-process construction but does not replace the contract entry point.

| Schema | Public model |
|---|---|
| `api-envelope.schema.json` | `ApiEnvelope[T]` |
| `runtime-metrics.schema.json` | `RuntimeMetrics` |
| `case-input.schema.json` | `CaseInput` |
| `accountability-state.schema.json` | `AccountabilityState` |
| `extracted-journey.schema.json` | `ExtractedJourney` |
| `prepared-action.schema.json` | `PreparedAction` |
| `decision-result.schema.json` | `DecisionResult` |
| `evaluate-action-request.schema.json` | `EvaluateActionRequest` |
| `analyze-case-request.schema.json` | `AnalyzeCaseRequest` |
| `analyze-case-response.schema.json` | `AnalyzeCaseResponse` |
| `approve-resolution-request.schema.json` | `ApproveResolutionRequest` |
| `approve-resolution-response.schema.json` | `ApproveResolutionResponse` |
| `shipment-event-request.schema.json` | `ShipmentEventRequest` |
| `shipment-event-response.schema.json` | `ShipmentEventResponse` |

All identifiers, including long numeric-looking order, SKU, event, message,
and request identifiers, use strict strings. They are never parsed as numeric
types. Public timestamp fields use strict RFC 3339 strings with an offset and
are checked by the same `jsonschema` date-time checker used for the locked
contracts.

`EvaluateActionRequest` preserves the five deprecated compatibility fields as
opaque input only. When `challenge_mode` is absent or false,
`challenge_overrides` is preserved but not structurally interpreted. An
explicit true applies the locked override shape. `AnalyzeCaseRequest` requires
an explicit true `challenge_mode` whenever it contains `case_input`.

## Candidate and server-owned DTO boundary

The following types are internal only and are not API-envelope data:

| Internal DTO | Ownership rule |
|---|---|
| `ImportedDataset`, `RowProvenance` | Import provenance only; no derived decision. |
| `CandidateExtraction` | Model candidate only; it has `candidate_only=True` and cannot be a ledger fact. |
| `EvidenceSummary` | Server-owned aggregation of sources, unread images, and conflicts. |
| `CompiledCommitments` | Server-owned compilation after evidence validation. |
| `LedgerSnapshot` | Persistence-only state, including internal `version` and `event_high_watermark`. |
| `ResolvedImage`, `SanitizedModelInput` | Adapter-safe image handle and redacted model input. |

No internal version or high-watermark appears in a public schema model. The
later state builder, commitment compiler, and rule module own business
semantics; this batch only supplies their data boundary.

## Frozen module ports

All ports live under `covenia_b.ports` and are runtime-checkable Python
protocols. They import only domain types and standard-library abstractions;
they do not import FastAPI or frontend code.

| Port | Input and output | Responsibility | Documented adapter errors |
|---|---|---|---|
| `Workbook` | sheet name -> source rows | Read workbook rows without interpreting business meaning. | `WorkbookUnavailable` |
| `CaseSource` | case ID -> `CaseInput` | Load a schema-backed case input. | `CaseNotFound` |
| `ImageResolver` | `EvidenceImage` -> `ResolvedImage` | Resolve declared evidence to a content-addressed handle. | `ImageUnavailable`, `ImageUnreadable` |
| `ModelProvider` | `SanitizedModelInput` -> `CandidateExtraction` | Produce only an untrusted candidate extraction. | `ModelUnavailable`, `ModelOutputInvalid` |
| `ExtractionStore` | cache key and candidate | Store/retrieve candidates only, never final accountability facts. | `ExtractionStoreUnavailable` |
| `LedgerRepository` | case ID / `LedgerSnapshot` | Atomically load and save internal snapshots with expected version checks. | `LedgerConflict`, `LedgerUnavailable` |
| `MetricsSink` | endpoint plus `RuntimeMetrics` | Record safe aggregate metrics as a side channel. | `MetricsUnavailable` |
| `Clock` | no input -> aware `datetime` | Supply trusted service time. | no operational error contract |

`PORT_ERROR_RESPONSIBILITIES` is the code-level summary of the documented
adapter errors. A later service maps these errors to the locked transport
envelope; ports do not decide HTTP status or business rule outcomes.

## Clock and injection seam

`SystemClock` returns the current UTC-aware instant. `DemoClock` accepts one
explicit timezone-aware `datetime`, returns it unchanged, and rejects naive
instants with `ClockConfigurationError`. Both offer `now_rfc3339()` for a
schema field only after formatting the trusted instant. Neither clock assigns
`approved_at`, advances a ledger high-watermark, or mutates a case.

`ModulePorts` is the single construction seam for all eight adapters. It is a
frozen dataclass with no I/O in its constructor, so later importer, model,
state, storage, and API modules can compose independently without changing
these contracts.

## Change control

BATCH-04 owns `backend/src/covenia_b/domain/**`,
`backend/src/covenia_b/ports/**`, and this document. A future port or type
change requires a BATCH-04 repair, a re-run of the schema/type checks, and
re-verification of affected consumers. It must not be made opportunistically
inside a later module batch.
