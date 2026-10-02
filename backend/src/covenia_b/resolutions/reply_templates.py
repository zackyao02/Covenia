"""Bounded consumer-facing reply templates for resolution candidates.

The planner may pass only a candidate kind and server-derived coverage facts.
There is deliberately no interpolation point for ticket assignees, risk scores,
model text, deadlines, or any other unbounded value.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType
from typing import Literal

CandidateType = Literal[
    "CHECK_REPLACEMENT_FULFILLMENT",
    "ASK_CURRENT_SCOPE_EVIDENCE",
    "HUMAN_EVIDENCE_REVIEW",
]
MissingCoverage = Literal["PRODUCT_IDENTITY", "AFFECTED_COMPONENT", "DAMAGE_DETAIL"]


class ReplyTemplateError(ValueError):
    """Raised when a caller attempts to use fields outside the reply contract."""


_MISSING_COVERAGE_ORDER: tuple[MissingCoverage, ...] = (
    "PRODUCT_IDENTITY",
    "AFFECTED_COMPONENT",
    "DAMAGE_DETAIL",
)
_MISSING_MATERIAL_LABELS = MappingProxyType(
    {
        "PRODUCT_IDENTITY": "商品整体与标识照片",
        "AFFECTED_COMPONENT": "受影响部位照片",
        "DAMAGE_DETAIL": "问题细节照片",
    }
)
_CANDIDATE_TYPES = frozenset(
    {
        "CHECK_REPLACEMENT_FULFILLMENT",
        "ASK_CURRENT_SCOPE_EVIDENCE",
        "HUMAN_EVIDENCE_REVIEW",
    }
)


def missing_material_labels(missing_coverage: Sequence[str]) -> tuple[str, ...]:
    """Return canonical labels for only the three allowed coverage gaps.

    The returned values are fixed template fragments.  A caller cannot introduce
    a free-form material request, even if an upstream model or UI sends one.
    """

    if isinstance(missing_coverage, str):
        raise ReplyTemplateError("missing coverage must be a sequence of coverage identifiers")
    supplied = frozenset(missing_coverage)
    unknown = supplied.difference(_MISSING_MATERIAL_LABELS)
    if unknown:
        raise ReplyTemplateError("missing coverage contains an unsupported value")
    return tuple(
        _MISSING_MATERIAL_LABELS[coverage]
        for coverage in _MISSING_COVERAGE_ORDER
        if coverage in supplied
    )


def render_consumer_reply(
    candidate_type: CandidateType,
    *,
    missing_coverage: Sequence[str] = (),
) -> str:
    """Render a consumer reply exclusively from bounded template fields."""

    if candidate_type not in _CANDIDATE_TYPES:
        raise ReplyTemplateError("candidate type is outside the reply-template contract")
    materials = missing_material_labels(missing_coverage)
    if candidate_type == "CHECK_REPLACEMENT_FULFILLMENT":
        if materials:
            raise ReplyTemplateError("fulfillment checks do not request additional materials")
        return "我们正在核对已有换货进度，确认后会向您更新。"
    if candidate_type == "HUMAN_EVIDENCE_REVIEW":
        if materials:
            raise ReplyTemplateError("human review does not request additional materials")
        return "为确保处理准确，我们已提交人工复核，确认后会向您更新。"
    if not materials:
        raise ReplyTemplateError("current-scope evidence requests require a known missing material")
    return f"为核对当前问题范围，请补充：{'、'.join(materials)}。收到后我们将继续核对。"
