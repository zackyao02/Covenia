"""The mandatory call seam between sanitized input and a model provider."""

from __future__ import annotations

from covenia_b.domain.types import CandidateExtraction
from covenia_b.ports.contracts import ModelProvider
from covenia_b.privacy.sanitizer import SanitizationResult, redact_text


class UnsafeModelInputError(ValueError):
    """Raised before a provider can capture a detectable raw sensitive value."""


async def extract_with_privacy_boundary(
    provider: ModelProvider,
    prepared_input: SanitizationResult,
) -> CandidateExtraction:
    """Dispatch only the safe model-input projection through the provider port.

    The second scan is intentionally defensive.  It turns a regression or
    mutation that bypasses normal redaction into a failure before the provider
    receives a request, rather than relying on downstream logging or caching.
    """

    _reject_detectable_raw_pii(prepared_input)
    return await provider.extract(prepared_input.model_input)


def _reject_detectable_raw_pii(prepared_input: SanitizationResult) -> None:
    probe = redact_text(prepared_input.model_input.redacted_text)
    if probe.pii_masked_count:
        raise UnsafeModelInputError("unsafe unredacted model input was blocked")
