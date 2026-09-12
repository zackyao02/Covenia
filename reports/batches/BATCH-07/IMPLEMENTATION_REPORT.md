# BATCH-07 repair implementation report

## Result

COMPLETED / IMPLEMENTED

This repair addresses only V-B07-001 and V-B07-002 from verifier commit
0749b1f, against baseline f8fad9c1f6b8f128d3215971b33780cb3080378b.
It does not replace independent verification.

## Delivered

- The model boundary now requires the sanitizer-generated projection plus its
  safe source-ID provenance before a provider can receive it.
- A copied, direct-constructed, text-replaced, or source-ID-replaced result
  fails closed before the capturing provider is called.
- Five opaque structured-field bypass mutations pass as expected failures.
- All five PII categories have both hit and non-overreach tests. The
  hospital-location and anti-allergy-product commitments remain verbatim.

## Evidence

- Code commit: ddf9a32fe1e765e7a3a4a47aebabcb77ddcbf8c3
- Full privacy suite: 24 passed in 0.30s
- Mutation suite: 7 passed, 17 deselected in 0.25s
- Ruff: All checks passed!
- Pip check: No broken requirements found.
- Environment and command records: environment.json, commands.json, and
  pip-check.txt in this directory.

## Scope and handoff

Only backend/src/covenia_b/privacy/**, backend/tests/privacy/**, and
implementation-owned BATCH-07 reports changed. No verifier artifact was
written, and no push, merge, or next batch was started.

Consumers must pass the original SanitizationResult directly to
extract_with_privacy_boundary; reconstructing or replacing its projection
is intentionally rejected.
