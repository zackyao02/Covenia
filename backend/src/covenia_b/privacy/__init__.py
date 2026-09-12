"""Fail-closed privacy preparation for model-bound Covenia input."""

from covenia_b.privacy.boundary import UnsafeModelInputError, extract_with_privacy_boundary
from covenia_b.privacy.sanitizer import (
    ImagePrivacyDeclarationRequired,
    PrivacyCategory,
    SanitizationResult,
    SensitiveField,
    redact_text,
    sanitize_case_input,
)

__all__ = [
    "ImagePrivacyDeclarationRequired",
    "PrivacyCategory",
    "SanitizationResult",
    "SensitiveField",
    "UnsafeModelInputError",
    "extract_with_privacy_boundary",
    "redact_text",
    "sanitize_case_input",
]
