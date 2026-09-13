"""Pure, server-owned evidence aggregation.

Candidate labels, candidate declarations, image file names, confidence values, and
hygiene signals are deliberately excluded from the decision. The function uses
only the bounded observation facts that BATCH-03 permits a server to aggregate.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from covenia_b.domain.types import AffectedComponent, EvidenceStatus, ImageObservation, Scope

CoverageFact = Literal[
    "PRODUCT_IDENTITY",
    "AFFECTED_COMPONENT",
    "DAMAGE_DETAIL",
    "PACKAGE_CONTEXT",
    "BATCH_LABEL",
]
ItemRole = Literal["PRIMARY", "GIFT", "BUNDLE_COMPONENT"]
ScopeLevel = Literal["order_id", "sku_id", "fulfillment_item_id", "issue_type"]
ReasonCode = Literal[
    "SCOPE_MISMATCH",
    "OBSERVATIONS_MISSING",
    "READABILITY_NOT_HIGH",
    "PRODUCT_NOT_IDENTIFIABLE",
    "SKU_UNKNOWN",
    "PRODUCT_ROLE_UNKNOWN",
    "ISSUE_NOT_VISIBLE",
    "CURRENT_COMPONENT_UNKNOWN",
    "AFFECTED_COMPONENT_UNKNOWN",
    "REQUIRED_COVERAGE_MISSING",
    "SKU_MISMATCH",
    "PRODUCT_ROLE_MISMATCH",
    "AFFECTED_COMPONENT_MISMATCH",
    "CONFLICTING_SOURCE_FACTS",
    "SOURCE_SELF_CONFLICT",
    "INTEGRITY_CONCERN",
    "DUPLICATE_EVIDENCE_ID",
]

REQUIRED_COVERAGE: tuple[CoverageFact, ...] = (
    "PRODUCT_IDENTITY",
    "AFFECTED_COMPONENT",
    "DAMAGE_DETAIL",
)
SCOPE_ORDER: tuple[ScopeLevel, ...] = (
    "order_id",
    "sku_id",
    "fulfillment_item_id",
    "issue_type",
)


@dataclass(frozen=True, slots=True)
class CurrentEvidenceContext:
    """Server-known facts against which a candidate is checked."""

    scope: Scope
    item_role: ItemRole
    affected_component: AffectedComponent | None


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Untrusted candidate observations and labels.

    ``candidate_id`` and ``declared_evidence_valid`` are carried only so callers
    can retain source provenance. ``aggregate_evidence`` intentionally does not
    read either field when deriving its result.
    """

    candidate_id: str
    extracted_scope: Scope
    image_observations: tuple[ImageObservation, ...]
    declared_evidence_valid: bool = False


@dataclass(frozen=True, slots=True)
class ScopeTrace:
    """One ordered comparison in the frozen scope sequence."""

    level: ScopeLevel
    current_value: str
    candidate_value: str
    matches: bool


@dataclass(frozen=True, slots=True)
class EvidenceReason:
    """A fact-based explanation with no model conclusion or diagnosis."""

    code: ReasonCode
    detail: str
    source_ids: tuple[str, ...] = ()
    scope_level: ScopeLevel | None = None


@dataclass(frozen=True, slots=True)
class EvidenceAggregation:
    """Deterministic evidence status and its supporting source trace."""

    evidence_status: EvidenceStatus
    scope_trace: tuple[ScopeTrace, ...]
    matching_source_ids: tuple[str, ...]
    mismatched_source_ids: tuple[str, ...]
    missing_source_ids: tuple[str, ...]
    conflicting_source_ids: tuple[str, ...]
    missing_coverage: tuple[CoverageFact, ...]
    reasons: tuple[EvidenceReason, ...]


def aggregate_evidence(
    current: CurrentEvidenceContext,
    candidate: CandidateEvidence,
) -> EvidenceAggregation:
    """Aggregate candidate image facts without consulting model conclusions.

    Status precedence is fixed: a changed scope is ``MISMATCHED``; otherwise a
    source conflict is ``NEED_HUMAN_REVIEW``; otherwise an explicit observed
    mismatch is ``MISMATCHED``; otherwise missing required facts are reviewed;
    only complete, compatible coverage is ``VALID``.
    """

    scope_trace = _scope_trace(current.scope, candidate.extracted_scope)
    reasons: list[EvidenceReason] = [
        EvidenceReason(
            code="SCOPE_MISMATCH",
            detail=f"scope changed at {trace.level}",
            scope_level=trace.level,
        )
        for trace in scope_trace
        if not trace.matches
    ]

    observations = tuple(
        sorted(candidate.image_observations, key=lambda item: item.evidence_id)
    )
    matching_sources: set[str] = set()
    mismatched_sources: set[str] = set()
    missing_sources: set[str] = set()
    conflicting_sources: set[str] = set()
    coverage_sources: dict[CoverageFact, set[str]] = {
        coverage: set() for coverage in REQUIRED_COVERAGE
    }
    field_matches: dict[str, set[str]] = {
        "sku": set(),
        "role": set(),
        "component": set(),
    }
    field_mismatches: dict[str, set[str]] = {
        "sku": set(),
        "role": set(),
        "component": set(),
    }

    duplicate_ids = tuple(
        evidence_id
        for evidence_id, count in sorted(
            Counter(item.evidence_id for item in observations).items()
        )
        if count > 1
    )
    if duplicate_ids:
        conflicting_sources.update(duplicate_ids)
        reasons.append(
            EvidenceReason(
                code="DUPLICATE_EVIDENCE_ID",
                detail="a candidate contains duplicate evidence identifiers",
                source_ids=duplicate_ids,
            )
        )

    component_is_known = current.affected_component not in (None, "UNKNOWN")
    if not component_is_known:
        reasons.append(
            EvidenceReason(
                code="CURRENT_COMPONENT_UNKNOWN",
                detail="the current affected component cannot be verified",
            )
        )

    if not observations:
        reasons.append(
            EvidenceReason(
                code="OBSERVATIONS_MISSING",
                detail="the candidate contains no image observations",
            )
        )

    for observation in observations:
        evidence_id = observation.evidence_id

        if observation.readability != "HIGH":
            missing_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="READABILITY_NOT_HIGH",
                    detail="source readability is not HIGH",
                    source_ids=(evidence_id,),
                )
            )
            continue

        self_conflict = _source_self_conflict(observation)
        if self_conflict:
            conflicting_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="SOURCE_SELF_CONFLICT",
                    detail=self_conflict,
                    source_ids=(evidence_id,),
                )
            )
            continue

        if observation.integrity_concern:
            conflicting_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="INTEGRITY_CONCERN",
                    detail="source integrity requires human review",
                    source_ids=(evidence_id,),
                )
            )
            continue

        if not observation.product_identifiable:
            missing_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="PRODUCT_NOT_IDENTIFIABLE",
                    detail="source does not identify a product",
                    source_ids=(evidence_id,),
                )
            )
            continue

        if observation.sku_match == "UNKNOWN":
            missing_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="SKU_UNKNOWN",
                    detail="source SKU relation is unknown",
                    source_ids=(evidence_id,),
                )
            )
            continue
        if observation.sku_match == "MISMATCH":
            mismatched_sources.add(evidence_id)
            field_mismatches["sku"].add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="SKU_MISMATCH",
                    detail="source SKU differs from the current item",
                    source_ids=(evidence_id,),
                )
            )
            continue
        field_matches["sku"].add(evidence_id)

        if observation.product_role == "UNKNOWN":
            missing_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="PRODUCT_ROLE_UNKNOWN",
                    detail="source product role is unknown",
                    source_ids=(evidence_id,),
                )
            )
            continue
        if observation.product_role != current.item_role:
            mismatched_sources.add(evidence_id)
            field_mismatches["role"].add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="PRODUCT_ROLE_MISMATCH",
                    detail="source product role differs from the current item",
                    source_ids=(evidence_id,),
                )
            )
            continue
        field_matches["role"].add(evidence_id)
        matching_sources.add(evidence_id)

        if "PRODUCT_IDENTITY" in observation.coverage:
            coverage_sources["PRODUCT_IDENTITY"].add(evidence_id)

        if not observation.issue_visible:
            missing_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="ISSUE_NOT_VISIBLE",
                    detail="source does not show the current issue",
                    source_ids=(evidence_id,),
                )
            )
            continue

        if not component_is_known:
            missing_sources.add(evidence_id)
            continue
        if observation.affected_component == "UNKNOWN":
            missing_sources.add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="AFFECTED_COMPONENT_UNKNOWN",
                    detail="source affected component is unknown",
                    source_ids=(evidence_id,),
                )
            )
            continue
        if observation.affected_component != current.affected_component:
            mismatched_sources.add(evidence_id)
            matching_sources.discard(evidence_id)
            field_mismatches["component"].add(evidence_id)
            reasons.append(
                EvidenceReason(
                    code="AFFECTED_COMPONENT_MISMATCH",
                    detail="source component differs from the current issue",
                    source_ids=(evidence_id,),
                )
            )
            continue
        field_matches["component"].add(evidence_id)

        if "AFFECTED_COMPONENT" in observation.coverage:
            coverage_sources["AFFECTED_COMPONENT"].add(evidence_id)
        if "DAMAGE_DETAIL" in observation.coverage:
            coverage_sources["DAMAGE_DETAIL"].add(evidence_id)

    for field in ("sku", "role", "component"):
        if field_matches[field] and field_mismatches[field]:
            source_ids = _ordered_unique(field_matches[field] | field_mismatches[field])
            conflicting_sources.update(source_ids)
            reasons.append(
                EvidenceReason(
                    code="CONFLICTING_SOURCE_FACTS",
                    detail=f"sources disagree about {field}",
                    source_ids=source_ids,
                )
            )

    missing_coverage = tuple(
        coverage for coverage in REQUIRED_COVERAGE if not coverage_sources[coverage]
    )
    if missing_coverage:
        reasons.append(
            EvidenceReason(
                code="REQUIRED_COVERAGE_MISSING",
                detail=f"missing coverage: {', '.join(missing_coverage)}",
            )
        )

    scope_changed = any(not trace.matches for trace in scope_trace)
    if scope_changed:
        evidence_status: EvidenceStatus = "MISMATCHED"
    elif conflicting_sources:
        evidence_status = "NEED_HUMAN_REVIEW"
    elif mismatched_sources:
        evidence_status = "MISMATCHED"
    elif missing_coverage or not component_is_known or not observations:
        evidence_status = "NEED_HUMAN_REVIEW"
    else:
        evidence_status = "VALID"

    return EvidenceAggregation(
        evidence_status=evidence_status,
        scope_trace=scope_trace,
        matching_source_ids=_ordered_unique(matching_sources),
        mismatched_source_ids=_ordered_unique(mismatched_sources),
        missing_source_ids=_ordered_unique(missing_sources),
        conflicting_source_ids=_ordered_unique(conflicting_sources),
        missing_coverage=missing_coverage,
        reasons=tuple(reasons),
    )


def _scope_trace(current_scope: Scope, candidate_scope: Scope) -> tuple[ScopeTrace, ...]:
    return tuple(
        ScopeTrace(
            level=level,
            current_value=getattr(current_scope, level),
            candidate_value=getattr(candidate_scope, level),
            matches=getattr(current_scope, level) == getattr(candidate_scope, level),
        )
        for level in SCOPE_ORDER
    )


def _source_self_conflict(observation: ImageObservation) -> str | None:
    coverage = set(observation.coverage)
    if "PRODUCT_IDENTITY" in coverage and not observation.product_identifiable:
        return "PRODUCT_IDENTITY coverage conflicts with product_identifiable=false"
    if "AFFECTED_COMPONENT" in coverage and observation.affected_component == "UNKNOWN":
        return "AFFECTED_COMPONENT coverage conflicts with affected_component=UNKNOWN"
    if "DAMAGE_DETAIL" in coverage and not observation.issue_visible:
        return "DAMAGE_DETAIL coverage conflicts with issue_visible=false"
    return None


def _ordered_unique(source_ids: set[str]) -> tuple[str, ...]:
    return tuple(sorted(source_ids))
