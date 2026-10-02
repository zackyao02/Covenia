"""Versioned, candidate-only model prompts."""

from covenia_b.model.prompts.candidate_extraction import (
    CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
    CANDIDATE_OUTPUT_FIELDS,
    PROMPT_VERSION,
    SCHEMA_REPAIR_SYSTEM_PROMPT,
    prompt_manifest,
)

__all__ = [
    "CANDIDATE_EXTRACTION_SYSTEM_PROMPT",
    "CANDIDATE_OUTPUT_FIELDS",
    "PROMPT_VERSION",
    "SCHEMA_REPAIR_SYSTEM_PROMPT",
    "prompt_manifest",
]
