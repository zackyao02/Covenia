from __future__ import annotations

import pytest

from covenia_b.domain.types import ImageObservation, Scope
from covenia_b.evidence import CandidateEvidence, CurrentEvidenceContext, aggregate_evidence


def make_scope(
    *,
    order_id: str = "order-a",
    sku_id: str = "sku-primary",
    fulfillment_item_id: str = "item-primary",
    issue_type: str = "PACKAGE_DAMAGE",
) -> Scope:
    return Scope(
        order_id=order_id,
        sku_id=sku_id,
        fulfillment_item_id=fulfillment_item_id,
        issue_type=issue_type,
    )


def make_context(**scope_overrides: str) -> CurrentEvidenceContext:
    return CurrentEvidenceContext(
        scope=make_scope(**scope_overrides),
        item_role="PRIMARY",
        affected_component="PUMP",
    )


def make_observation(
    evidence_id: str,
    *,
    readability: str = "HIGH",
    product_identifiable: bool = True,
    sku_match: str = "MATCH",
    product_role: str = "PRIMARY",
    issue_visible: bool = True,
    affected_component: str = "PUMP",
    coverage: list[str] | None = None,
    integrity_concern: bool = False,
    hygiene_risk_signal: str = "LOW",
    confidence: float = 0.01,
) -> ImageObservation:
    return ImageObservation(
        evidence_id=evidence_id,
        readability=readability,
        product_identifiable=product_identifiable,
        sku_match=sku_match,
        product_role=product_role,
        issue_visible=issue_visible,
        affected_component=affected_component,
        view_type="ISSUE_DETAIL",
        coverage=coverage
        if coverage is not None
        else ["PRODUCT_IDENTITY", "AFFECTED_COMPONENT", "DAMAGE_DETAIL"],
        integrity_concern=integrity_concern,
        hygiene_risk_signal=hygiene_risk_signal,
        confidence=confidence,
    )


def make_candidate(
    *observations: ImageObservation,
    scope: Scope | None = None,
    candidate_id: str = "candidate-a",
    declared_evidence_valid: bool = False,
) -> CandidateEvidence:
    return CandidateEvidence(
        candidate_id=candidate_id,
        extracted_scope=scope or make_scope(),
        image_observations=observations,
        declared_evidence_valid=declared_evidence_valid,
    )


def test_aggregate_evidence_combines_reliable_multi_image_coverage() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(
            make_observation(
                "identity-and-component",
                coverage=["PRODUCT_IDENTITY", "AFFECTED_COMPONENT"],
            ),
            make_observation("damage-detail", coverage=["DAMAGE_DETAIL"]),
        ),
    )

    assert result.evidence_status == "VALID"
    assert result.matching_source_ids == ("damage-detail", "identity-and-component")
    assert result.missing_coverage == ()
    assert result.conflicting_source_ids == ()


def test_unreadable_extra_image_does_not_override_complete_reliable_coverage() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(
            make_observation("complete"),
            make_observation("unreadable", readability="LOW"),
        ),
    )

    assert result.evidence_status == "VALID"
    assert result.matching_source_ids == ("complete",)
    assert result.missing_source_ids == ("unreadable",)


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("order_id", "order-b"),
        ("sku_id", "sku-gift"),
        ("fulfillment_item_id", "item-gift"),
        ("issue_type", "LOGISTICS_STALLED"),
    ],
)
def test_scope_changes_are_mismatched_in_frozen_comparison_order(
    changed_field: str, changed_value: str
) -> None:
    context = make_context()
    candidate_scope = make_scope(**{changed_field: changed_value})

    result = aggregate_evidence(
        context,
        make_candidate(make_observation("complete"), scope=candidate_scope),
    )

    assert result.evidence_status == "MISMATCHED"
    first_difference = next(trace for trace in result.scope_trace if not trace.matches)
    assert first_difference.level == changed_field
    assert first_difference.current_value != first_difference.candidate_value


def test_gift_instead_of_primary_is_an_observed_mismatch() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(make_observation("gift", product_role="GIFT")),
    )

    assert result.evidence_status == "MISMATCHED"
    assert result.mismatched_source_ids == ("gift",)
    assert {reason.code for reason in result.reasons} >= {"PRODUCT_ROLE_MISMATCH"}


def test_conflicting_good_sources_go_to_human_review() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(
            make_observation("primary"),
            make_observation("gift", product_role="GIFT"),
        ),
    )

    assert result.evidence_status == "NEED_HUMAN_REVIEW"
    assert result.conflicting_source_ids == ("gift", "primary")
    assert {reason.code for reason in result.reasons} >= {"CONFLICTING_SOURCE_FACTS"}


def test_missing_coverage_and_unknown_source_facts_go_to_human_review() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(
            make_observation(
                "unknown-sku",
                sku_match="UNKNOWN",
                coverage=["PRODUCT_IDENTITY"],
            )
        ),
    )

    assert result.evidence_status == "NEED_HUMAN_REVIEW"
    assert result.missing_source_ids == ("unknown-sku",)
    assert result.missing_coverage == (
        "PRODUCT_IDENTITY",
        "AFFECTED_COMPONENT",
        "DAMAGE_DETAIL",
    )


def test_inconsistent_claimed_coverage_goes_to_human_review() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(
            make_observation(
                "inconsistent",
                issue_visible=False,
                coverage=["PRODUCT_IDENTITY", "DAMAGE_DETAIL"],
            )
        ),
    )

    assert result.evidence_status == "NEED_HUMAN_REVIEW"
    assert result.conflicting_source_ids == ("inconsistent",)
    assert {reason.code for reason in result.reasons} >= {"SOURCE_SELF_CONFLICT"}


def test_changed_component_is_an_observed_mismatch() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(make_observation("cap", affected_component="CAP")),
    )

    assert result.evidence_status == "MISMATCHED"
    assert result.mismatched_source_ids == ("cap",)


def test_source_integrity_concern_requires_human_review() -> None:
    result = aggregate_evidence(
        make_context(),
        make_candidate(make_observation("concern", integrity_concern=True)),
    )

    assert result.evidence_status == "NEED_HUMAN_REVIEW"
    assert result.conflicting_source_ids == ("concern",)


def test_candidate_id_and_evidence_valid_declaration_do_not_change_result() -> None:
    observation = make_observation("complete")
    first = aggregate_evidence(
        make_context(),
        make_candidate(observation, candidate_id="candidate-a", declared_evidence_valid=False),
    )
    renamed = aggregate_evidence(
        make_context(),
        make_candidate(observation, candidate_id="candidate-b", declared_evidence_valid=True),
    )

    assert renamed == first


def test_confidence_and_image_text_assertion_do_not_change_result() -> None:
    baseline = aggregate_evidence(
        make_context(),
        make_candidate(make_observation("complete", confidence=0.0)),
    )
    asserted = aggregate_evidence(
        make_context(),
        make_candidate(
            make_observation("complete", confidence=1.0),
            declared_evidence_valid=True,
        ),
    )

    assert baseline == asserted


def test_repeated_calls_and_observation_order_are_deterministic() -> None:
    first = make_observation("first", coverage=["PRODUCT_IDENTITY", "AFFECTED_COMPONENT"])
    second = make_observation("second", coverage=["DAMAGE_DETAIL"])
    context = make_context()

    initial = aggregate_evidence(context, make_candidate(first, second))
    repeated = aggregate_evidence(context, make_candidate(first, second))
    reordered = aggregate_evidence(context, make_candidate(second, first))

    assert repeated == initial
    assert reordered == initial


def test_adverse_reaction_remains_a_scope_fact_not_a_medical_conclusion() -> None:
    context = make_context(issue_type="ADVERSE_REACTION")
    result = aggregate_evidence(
        context,
        make_candidate(
            make_observation("complete", hygiene_risk_signal="HIGH"),
            scope=make_scope(issue_type="ADVERSE_REACTION"),
        ),
    )

    assert result.evidence_status == "VALID"
    assert all(reason.code != "INTEGRITY_CONCERN" for reason in result.reasons)
