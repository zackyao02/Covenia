# BATCH-10 required model environment

This is a deployment handoff, not evidence of a live model run. BATCH-10 used
only a protocol double; BATCH-28 owns real Qwen inference and real-image
acceptance.

## Required configuration

The service owner supplies these values through the process environment or an
equivalent secret manager. No API key belongs in source, reports, or command
arguments.

| Variable | Requirement |
| --- | --- |
| `COVENIA_QWEN_ENDPOINT` | `http://` or `https://` endpoint for the team-controlled OpenAI-compatible chat service; no credentials, query, or fragment. |
| `COVENIA_QWEN_API_KEY` | Optional for an unauthenticated local service; otherwise a single-line ASCII secret used only as `Authorization: Bearer`. |
| `COVENIA_QWEN_MODEL_ID` | Must be exactly `qwen3-vl-plus`; the adapter rejects another value. |
| `COVENIA_QWEN_MODEL_REVISION` | Required non-empty deployment revision/commit identifier. It is sent in the request and must be echoed by the response body or `x-model-revision` header. |
| `COVENIA_QWEN_PROMPT_VERSION` | Safe version label recorded in request metadata and provider run metadata. |
| `COVENIA_QWEN_DEPLOYMENT_ID` | Safe non-secret deployment label for governance metadata. |

The response must contain `model=qwen3-vl-plus` and the exact
configured revision. A service that omits or changes the revision is rejected;
the adapter does not infer a revision from a friendly model name or a random
route. The provider protocol is OpenAI-compatible JSON with one non-streaming
assistant message containing candidate-only JSON.

## Operational requirements

- Use an already verified `ProviderImageInput` from BATCH-08. The caller passes
  its exact bytes through the injected image loader; the adapter checks the
  handle SHA-256, media type, byte length, dimensions, and configured limits.
- Pass the use-case total timeout through `QwenHttpProvider.extract(...,
  timeout_seconds=...)` or configure `default_timeout_seconds`. The budget
  includes concurrency-slot wait and is not a per-read timeout.
- Send sanitized input through BATCH-07's
  `extract_with_privacy_boundary`; this adapter is not a privacy bypass.
- Wrap a real call with BATCH-09's `begin_model_attempt().complete(...)` or
  `.fail(...)`. Use `ProviderRunMetadata.usage` only when `usage_status` is
  `EXACT`; missing usage remains zero/unknown and is never estimated.
- The HTTP adapter uses a bounded, cancellation-aware standard-library
  HTTP/1.1 transport. It does not add a third-party dependency or GPU stack.

## Reproduction commands

All Python commands for this implementation used the absolute interpreter:

```powershell
C:\cov-run\b10oct2\venv\Scripts\python.exe -m pytest backend/tests/model/test_qwen_provider.py -q
C:\cov-run\b10oct2\venv\Scripts\python.exe -m pip check
```

These commands exercise the protocol double only. They must not be described
as real Qwen inference, and the real endpoint/API key/model revision must be
provided separately for BATCH-28.
