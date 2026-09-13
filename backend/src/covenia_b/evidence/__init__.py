"""Deterministic aggregation of candidate image observations."""

from .aggregation import (
    CandidateEvidence,
    CurrentEvidenceContext,
    EvidenceAggregation,
    EvidenceReason,
    ScopeTrace,
    aggregate_evidence,
)

__all__ = [
    "CandidateEvidence",
    "CurrentEvidenceContext",
    "EvidenceAggregation",
    "EvidenceReason",
    "ScopeTrace",
    "aggregate_evidence",
]
