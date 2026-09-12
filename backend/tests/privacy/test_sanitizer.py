from __future__ import annotations

import pytest

from covenia_b.domain.types import CaseInput, ResolvedImage
from covenia_b.privacy import (
    ImagePrivacyDeclarationRequired,
    PrivacyCategory,
    SensitiveField,
    redact_text,
    sanitize_case_input,
)

_TEST_PHONE = "".join(
    str(digit) for digit in (1, 3, 8, 0, 0, 1, 3, 8, 0, 0, 0)
)


def test_masks_chat_pii_and_preserves_safe_association_and_promise_semantics() -> None:
    phone = "".join(str(digit) for digit in (1, 3, 8, 0, 0, 1, 3, 8, 0, 0, 0))
    case_input = _case_input(
        f"联系手机：{phone}；收货地址：unit-test-address；支付宝账号：unit-test-account。",
        "客服承诺在 48 小时内发出换货商品。",
        "消费者表示出现不良反应。",
        "消费者已经就医处理。",
    )

    result = sanitize_case_input(case_input)
    model_text = result.model_input.redacted_text

    assert result.pii_masked_count == 5
    assert set(result.masked_categories) == {
        PrivacyCategory.PHONE,
        PrivacyCategory.SHIPPING_ADDRESS,
        PrivacyCategory.ALIPAY_ACCOUNT,
        PrivacyCategory.ADVERSE_REACTION,
        PrivacyCategory.MEDICAL_CONTEXT,
    }
    assert result.adverse_risk_candidate is True
    assert "[ADVERSE_REACTION_RISK]" in model_text
    assert "[MEDICAL_CONTEXT_REDACTED]" in model_text
    assert "客服承诺在 48 小时内发出换货商品。" in model_text
    assert "order-safe-001" in model_text
    assert "message-safe-001" in model_text
    assert "2026-09-13T09:32:00+00:00" in model_text
    for raw_value in (phone, "unit-test-address", "unit-test-account"):
        assert raw_value not in model_text
    assert "message-safe-001" in result.model_input.source_ids
    assert "order-safe-001" in result.model_input.source_ids


def test_masks_explicit_fields_without_pattern_matching_their_values() -> None:
    opaque_field_value = "field-value-without-a-recognizable-pattern"
    result = sanitize_case_input(
        _case_input("客服承诺尽快更新处理进度。"),
        sensitive_fields=(
            SensitiveField(
                category=PrivacyCategory.SHIPPING_ADDRESS,
                source_id="message-safe-field",
                value=opaque_field_value,
            ),
        ),
    )

    assert result.pii_masked_count == 1
    assert "[SHIPPING_ADDRESS_REDACTED]" in result.model_input.redacted_text
    assert opaque_field_value not in result.model_input.redacted_text
    assert "message-safe-field" in result.model_input.source_ids


@pytest.mark.parametrize(
    ("category", "text", "raw_fragment", "placeholder"),
    [
        (
            PrivacyCategory.PHONE,
            "联系手机：" + _TEST_PHONE + "。",
            _TEST_PHONE,
            "[PHONE_REDACTED]",
        ),
        (
            PrivacyCategory.SHIPPING_ADDRESS,
            "收货地址：synthetic-delivery-location。",
            "synthetic-delivery-location",
            "[SHIPPING_ADDRESS_REDACTED]",
        ),
        (
            PrivacyCategory.ALIPAY_ACCOUNT,
            "支付宝账号：synthetic-account-token。",
            "synthetic-account-token",
            "[ALIPAY_ACCOUNT_REDACTED]",
        ),
        (
            PrivacyCategory.MEDICAL_CONTEXT,
            "消费者已经就医处理。",
            "消费者已经就医处理。",
            "[MEDICAL_CONTEXT_REDACTED]",
        ),
        (
            PrivacyCategory.ADVERSE_REACTION,
            "消费者表示出现不良反应。",
            "消费者表示出现不良反应。",
            "[ADVERSE_REACTION_RISK]",
        ),
    ],
    ids=("phone", "shipping-address", "alipay-account", "medical-context", "adverse-reaction"),
)
def test_masks_each_required_chat_pii_category(
    category: PrivacyCategory,
    text: str,
    raw_fragment: str,
    placeholder: str,
) -> None:
    redacted = redact_text(text)

    assert redacted.pii_masked_count == 1
    assert redacted.masked_categories == (category,)
    assert raw_fragment not in redacted.text
    assert placeholder in redacted.text


def test_masks_a_personal_adverse_symptom_without_erasing_the_risk_signal() -> None:
    redacted = redact_text("消费者皮肤红肿并瘙痒。")

    assert redacted.pii_masked_count == 1
    assert redacted.masked_categories == (PrivacyCategory.ADVERSE_REACTION,)
    assert redacted.text == "[ADVERSE_REACTION_RISK]"


@pytest.mark.parametrize(
    ("category", "text"),
    [
        (PrivacyCategory.PHONE, "客服承诺通过电话在 48 小时内回电。"),
        (PrivacyCategory.SHIPPING_ADDRESS, "客服承诺说明收货地址修改流程。"),
        (PrivacyCategory.ALIPAY_ACCOUNT, "客服承诺说明支付宝账号认证流程。"),
        (PrivacyCategory.MEDICAL_CONTEXT, "客服承诺在医院附近的自提点安排换货。"),
        (PrivacyCategory.ADVERSE_REACTION, "客服承诺寄送抗过敏产品。"),
    ],
    ids=("phone", "shipping-address", "alipay-account", "medical-context", "adverse-reaction"),
)
def test_preserves_non_pii_commitments_for_each_category(
    category: PrivacyCategory,
    text: str,
) -> None:
    redacted = redact_text(text)

    assert redacted.pii_masked_count == 0
    assert category not in redacted.masked_categories
    assert redacted.text == text


def test_preserves_safe_metadata_and_the_acceptance_promise_counterexamples() -> None:
    hospital_location_promise = "客服承诺在医院附近的自提点安排换货。"
    anti_allergy_product_promise = "客服承诺寄送抗过敏产品。"
    result = sanitize_case_input(
        _case_input(hospital_location_promise, anti_allergy_product_promise)
    )

    model_text = result.model_input.redacted_text

    assert result.pii_masked_count == 0
    assert hospital_location_promise in model_text
    assert anti_allergy_product_promise in model_text
    assert "order-safe-001" in model_text
    assert "message-safe-001" in model_text
    assert "2026-09-13T09:32:00+00:00" in model_text
    assert result.model_input.source_ids == (
        "order-safe-001",
        "message-safe-001",
        "message-safe-002",
    )


def test_unrelated_text_is_not_over_redacted() -> None:
    text = "客服承诺在 48 小时内更新进度；支付宝支持政策可在帮助页查阅。"

    redacted = redact_text(text)

    assert redacted.text == text
    assert redacted.pii_masked_count == 0


def test_model_bound_images_require_explicit_no_pii_declarations() -> None:
    image = ResolvedImage(
        evidence_id="image-safe-001",
        media_type="image/png",
        content_sha256="a" * 64,
        byte_length=12,
    )
    case_input = _case_input("客服承诺在 48 小时内更新进度。")

    with pytest.raises(ImagePrivacyDeclarationRequired):
        sanitize_case_input(case_input, resolved_images=(image,))
    with pytest.raises(ImagePrivacyDeclarationRequired):
        sanitize_case_input(
            case_input,
            resolved_images=(image,),
            image_no_pii_declarations={"image-safe-001": False},
        )

    result = sanitize_case_input(
        case_input,
        resolved_images=(image,),
        image_no_pii_declarations={"image-safe-001": True},
    )
    assert result.model_input.images == (image,)


def _case_input(*messages: str) -> CaseInput:
    conversation = [
        {
            "message_id": f"message-safe-{index:03d}",
            "timestamp": f"2026-09-13T09:{31 + index:02d}:00+00:00",
            "speaker": "CONSUMER" if index % 2 else "AGENT",
            "text": message,
            "source_kind": "COMPETITION_MOCK",
        }
        for index, message in enumerate(messages, start=1)
    ]
    return CaseInput.model_validate(
        {
            "case_id": "case-safe-001",
            "data_provenance": {
                "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
                "source_session_id": "session-safe-001",
                "augmentation_notes": [],
            },
            "evaluation_time": "2026-09-13T09:32:00+00:00",
            "conversation": conversation,
            "order": {
                "order_id": "order-safe-001",
                "channel": "TIANCHI_MOCK_QIANNIU",
                "items": [
                    {
                        "fulfillment_item_id": "item-safe-001",
                        "sku_id": "sku-safe-001",
                        "product_name": "Test Product",
                        "batch_code": None,
                        "item_role": "PRIMARY",
                    }
                ],
                "original_logistics_number": "logistics-safe-001",
            },
            "service_tickets": [],
            "evidence_images": [
                {
                    "evidence_id": "image-safe-001",
                    "file_name": "safe.png",
                    "submitted_at": "2026-09-13T09:30:00+00:00",
                    "declared_view_type": "ISSUE_DETAIL",
                    "source_kind": "TEAM_SYNTHETIC_RECREATION",
                    "source_message_id": "message-safe-001",
                    "competition_reference_path": None,
                }
            ],
            "current_issue": {
                "fulfillment_item_id": "item-safe-001",
                "sku_id": "sku-safe-001",
                "issue_type": "PACKAGE_DAMAGE",
                "affected_component": "PUMP",
            },
            "policy_requirement_id": "DEMO_POLICY_PACKAGE_DAMAGE_V1",
        }
    )
