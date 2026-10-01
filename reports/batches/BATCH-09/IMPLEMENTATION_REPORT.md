# BATCH-09 implementation report

Status: `COMPLETED` implementation; independent verification and integration remain separate gates.

Implemented a request-scoped runtime-metrics collector and a durable redacted JSONL governance sink. A real provider attempt starts its monotonic timer before invocation and records exact provider usage where present. If usage is absent, only an exact tokenizer with the same model ID and revision may count tokens; otherwise both token values remain zero with `MISSING` provenance.

Pure-rule `evaluate` emits zero model tokens and zero inference latency with a frozen `rule_substitution_count` of one. Cache hits do not copy old usage; cache fallback has an explicit safe reason code. Audit sink failures raise `GovernanceLogWriteError` before request totals change.

The required observability suite passed 10/10 in the normal execution context. Focused provider/retry/cache, audit-failure, and PII/secret/prompt/original-image leakage probes also passed. `ruff` and `pip check` passed. One elevated evidence-run retry could not access that process's inherited pytest temporary directory; it is disclosed in `commands.json` and was not used as passing evidence. The exact normal-context test command subsequently passed.

No dependency, domain, port, schema, fixture, frontend, plan, or other-Batch file changed. The code-and-test commit is `cac51bd9ecc38b318eae6eed22561be829c885c2`; this report does not self-reference its own later report commit.

Downstream callers must use the provenance-aware session API around real provider calls and must send only safe source hashes, image hashes, counts, versions, and reason codes to governance logging. Do not treat this report as an independent PASS.
