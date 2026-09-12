"""Create model input without retaining raw identity or health text.

The returned value contains only redacted text, safe identifiers, and aggregate
masking metadata.  This module deliberately has no logging or cache dependency:
callers must send ``pii_masked_count`` to the later governance sink, never raw
input values.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from typing import Final

from covenia_b.domain.types import CaseInput, ResolvedImage, SanitizedModelInput


class PrivacyCategory(StrEnum):
    """Sensitive values that must not cross the model boundary in raw form."""

    PHONE = "phone"
    SHIPPING_ADDRESS = "shipping_address"
    ALIPAY_ACCOUNT = "alipay_account"
    MEDICAL_CONTEXT = "medical_context"
    ADVERSE_REACTION = "adverse_reaction"


_PLACEHOLDERS: Final[dict[PrivacyCategory, str]] = {
    PrivacyCategory.PHONE: "[PHONE_REDACTED]",
    PrivacyCategory.SHIPPING_ADDRESS: "[SHIPPING_ADDRESS_REDACTED]",
    PrivacyCategory.ALIPAY_ACCOUNT: "[ALIPAY_ACCOUNT_REDACTED]",
    PrivacyCategory.MEDICAL_CONTEXT: "[MEDICAL_CONTEXT_REDACTED]",
    PrivacyCategory.ADVERSE_REACTION: "[ADVERSE_REACTION_RISK]",
}

_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?<!\d)(?:\+?86[-\s]?)?1[3-9](?:[-\s]?\d){9}(?!\d)"
)
_ALIPAY_ACCOUNT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:支付宝(?:账号|账户)?|alipay(?:\s+account)?)\s*[:：=]\s*[^\s,，。；;]+",
    re.IGNORECASE,
)
_SHIPPING_ADDRESS_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:收货(?:地址|地)?|shipping\s+address)\s*[:：=]\s*[^。；;\n]+",
    re.IGNORECASE,
)
_PERSONAL_HEALTH_SUBJECT: Final[str] = (
    r"(?:消费者|顾客|用户|客户|买家|本人|我|她|他|患者|consumer|customer|user|patient|i|she|he|they)"
)
_HEALTH_EXPERIENCE_CUE: Final[str] = (
    r"(?:出现|发生|感到|感觉|反馈|表示|自述|诉称|经历|伴有|导致|引发|产生|有|使用后|使用时|服用后|涂抹后|"
    r"reported|experienced|developed|suffered|has|with|after\s+use|on\s+use)"
)
_ADVERSE_SYMPTOM: Final[str] = (
    r"(?<!抗)(?:过敏(?:反应)?|红(?:肿|疹)|瘙痒|刺痛|灼(?:痛|烧)|呼吸困难|allergic\s+reaction|rash)"
)
_ADVERSE_REACTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?:不良反应|adverse\s+reaction|"
    rf"(?:{_PERSONAL_HEALTH_SUBJECT}.{{0,24}}?(?:{_HEALTH_EXPERIENCE_CUE}).{{0,8}}?"
    rf"|{_PERSONAL_HEALTH_SUBJECT}.{{0,24}}?"
    rf"|(?:{_HEALTH_EXPERIENCE_CUE}).{{0,8}}?){_ADVERSE_SYMPTOM})",
    re.IGNORECASE,
)
_MEDICAL_CONTEXT_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?:就医|就诊|诊断|治疗|处方|病历|medical\s+(?:treatment|record)|diagnosis|prescription|"
    rf"{_PERSONAL_HEALTH_SUBJECT}.{{0,24}}?(?:前往|去|到|看|咨询|接受|went\s+to|visited|saw).{{0,8}}?"
    rf"(?:医院|医生|hospital|doctor))",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[。！？!?；;\n])")


class ImagePrivacyDeclarationRequired(ValueError):
    """Raised before model input is created when an image lacks a safe declaration."""


@dataclass(frozen=True, slots=True)
class SensitiveField:
    """A typed raw field that is replaced wholesale rather than pattern-guessed."""

    category: PrivacyCategory
    source_id: str
    value: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.value:
            raise ValueError("sensitive fields require non-empty safe source IDs and values")


@dataclass(frozen=True, slots=True)
class RedactedText:
    """Internal redaction result; it never stores the raw source string."""

    text: str
    masked_categories: tuple[PrivacyCategory, ...]

    @property
    def pii_masked_count(self) -> int:
        return len(self.masked_categories)


@dataclass(frozen=True, slots=True)
class _GeneratedSanitizedProjection:
    """Private record tying a result to its safe, generated model projection."""

    model_input: SanitizedModelInput
    case_id: str
    redacted_text: str
    images: tuple[ResolvedImage, ...]
    source_ids: tuple[str, ...]
    pii_masked_count: int
    masked_categories: tuple[PrivacyCategory, ...]
    adverse_risk_candidate: bool

    @classmethod
    def from_result(
        cls, result: SanitizationResult
    ) -> _GeneratedSanitizedProjection:
        model_input = result.model_input
        return cls(
            model_input=model_input,
            case_id=model_input.case_id,
            redacted_text=model_input.redacted_text,
            images=model_input.images,
            source_ids=model_input.source_ids,
            pii_masked_count=result.pii_masked_count,
            masked_categories=result.masked_categories,
            adverse_risk_candidate=result.adverse_risk_candidate,
        )

    def matches(self, result: SanitizationResult) -> bool:
        """Reject copied or altered inputs, including opaque field-value bypasses."""

        model_input = result.model_input
        return (
            self.model_input is model_input
            and self.case_id == model_input.case_id
            and self.redacted_text == model_input.redacted_text
            and self.images == model_input.images
            and self.source_ids == model_input.source_ids
            and self.pii_masked_count == result.pii_masked_count
            and self.masked_categories == result.masked_categories
            and self.adverse_risk_candidate == result.adverse_risk_candidate
        )


@dataclass(frozen=True, slots=True)
class SanitizationResult:
    """The only privacy result handed to a model boundary and governance caller."""

    model_input: SanitizedModelInput
    pii_masked_count: int
    masked_categories: tuple[PrivacyCategory, ...]
    adverse_risk_candidate: bool
    _generated_projection: _GeneratedSanitizedProjection | None = dataclass_field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.pii_masked_count != len(self.masked_categories):
            raise ValueError("pii_masked_count must equal the number of redaction hits")
        if self.adverse_risk_candidate != (
            PrivacyCategory.ADVERSE_REACTION in self.masked_categories
        ):
            raise ValueError("adverse risk must be derived from redaction categories")

    def _has_generated_projection(self) -> bool:
        """Return whether this exact safe projection came from this sanitizer."""

        return (
            self._generated_projection is not None
            and self._generated_projection.matches(self)
        )


def redact_text(value: str) -> RedactedText:
    """Redact detectable chat PII and health descriptions while retaining safe context.

    Explicit ``SensitiveField`` values are handled by ``sanitize_case_input`` so
    callers do not rely solely on text-pattern detection for structured fields.
    """

    if not isinstance(value, str):
        raise ValueError("model-bound text must be a string")

    redacted = value
    categories: list[PrivacyCategory] = []
    for pattern, category in (
        (_PHONE_PATTERN, PrivacyCategory.PHONE),
        (_SHIPPING_ADDRESS_PATTERN, PrivacyCategory.SHIPPING_ADDRESS),
        (_ALIPAY_ACCOUNT_PATTERN, PrivacyCategory.ALIPAY_ACCOUNT),
    ):
        redacted, hit_count = pattern.subn(_PLACEHOLDERS[category], redacted)
        categories.extend([category] * hit_count)

    redacted, adverse_hits = _redact_sensitive_sentences(
        redacted,
        _ADVERSE_REACTION_PATTERN,
        PrivacyCategory.ADVERSE_REACTION,
    )
    categories.extend([PrivacyCategory.ADVERSE_REACTION] * adverse_hits)

    redacted, medical_hits = _redact_sensitive_sentences(
        redacted,
        _MEDICAL_CONTEXT_PATTERN,
        PrivacyCategory.MEDICAL_CONTEXT,
    )
    categories.extend([PrivacyCategory.MEDICAL_CONTEXT] * medical_hits)
    return RedactedText(text=redacted, masked_categories=tuple(categories))


def sanitize_case_input(
    case_input: CaseInput,
    *,
    resolved_images: Sequence[ResolvedImage] = (),
    image_no_pii_declarations: Mapping[str, bool] | None = None,
    sensitive_fields: Sequence[SensitiveField] = (),
) -> SanitizationResult:
    """Render a safe, traceable prompt and reject undeclared image ingress.

    ``case_id``, order IDs, message IDs, timestamps, and safe commitment text
    remain traceable.  Structured sensitive fields are represented only by a
    category-specific placeholder.  Image bytes may enter only after their
    evidence ID has an explicit no-PII declaration supplied by the A-owned
    manifest path.
    """

    images = tuple(resolved_images)
    _require_declared_safe_images(images, image_no_pii_declarations)

    lines = [
        f"case_id={case_input.case_id}",
        f"order_id={case_input.order.order_id}",
        f"current_issue_sku_id={case_input.current_issue.sku_id}",
    ]
    source_ids = [case_input.order.order_id]
    masked_categories: list[PrivacyCategory] = []

    for message in case_input.conversation:
        redacted_message = redact_text(message.text)
        lines.append(
            f"[message_id={message.message_id} timestamp={message.timestamp} "
            f"speaker={message.speaker}] {redacted_message.text}"
        )
        source_ids.append(message.message_id)
        masked_categories.extend(redacted_message.masked_categories)

    for field in sensitive_fields:
        lines.append(
            f"[field={field.category.value} source_id={field.source_id}] "
            f"{_PLACEHOLDERS[field.category]}"
        )
        source_ids.append(field.source_id)
        masked_categories.append(field.category)

    source_ids.extend(ticket.ticket_id for ticket in case_input.service_tickets)
    source_ids.extend(image.evidence_id for image in images)
    unique_source_ids = tuple(dict.fromkeys(source_ids))
    category_tuple = tuple(masked_categories)
    model_input = SanitizedModelInput(
        case_id=case_input.case_id,
        redacted_text="\n".join(lines),
        images=images,
        source_ids=unique_source_ids,
    )
    result = SanitizationResult(
        model_input=model_input,
        pii_masked_count=len(category_tuple),
        masked_categories=category_tuple,
        adverse_risk_candidate=PrivacyCategory.ADVERSE_REACTION in category_tuple,
    )
    object.__setattr__(
        result,
        "_generated_projection",
        _GeneratedSanitizedProjection.from_result(result),
    )
    return result


def _redact_sensitive_sentences(
    value: str,
    pattern: re.Pattern[str],
    category: PrivacyCategory,
) -> tuple[str, int]:
    """Replace each sensitive sentence with a minimum anonymous semantic token."""

    sentences = _SENTENCE_BOUNDARY.split(value)
    hit_count = 0
    redacted_sentences: list[str] = []
    for sentence in sentences:
        if pattern.search(sentence):
            redacted_sentences.append(_PLACEHOLDERS[category])
            hit_count += 1
        else:
            redacted_sentences.append(sentence)
    return "".join(redacted_sentences), hit_count


def _require_declared_safe_images(
    images: tuple[ResolvedImage, ...],
    declarations: Mapping[str, bool] | None,
) -> None:
    """Fail closed: image handles never imply their bytes are free of PII."""

    if not images:
        return
    if declarations is None:
        raise ImagePrivacyDeclarationRequired("image no-PII declarations are required")
    if any(declarations.get(image.evidence_id) is not True for image in images):
        raise ImagePrivacyDeclarationRequired("every model-bound image needs a no-PII declaration")
