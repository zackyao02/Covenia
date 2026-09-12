from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from covenia_b.domain.types import CaseInput, SanitizedModelInput
from covenia_b.privacy import (
    PrivacyCategory,
    SanitizationResult,
    SensitiveField,
    UnsafeModelInputError,
    extract_with_privacy_boundary,
    sanitize_case_input,
)


class CapturingProvider:
    def __init__(self) -> None:
        self.captured_inputs = []

    async def extract(self, model_input):  # type: ignore[no-untyped-def]
        self.captured_inputs.append(model_input)
        return None


def test_model_provider_receives_only_the_sanitized_projection() -> None:
    phone = "".join(str(digit) for digit in (1, 3, 8, 0, 0, 1, 3, 8, 0, 0, 0))
    prepared_input = sanitize_case_input(_case_input(f"联系手机：{phone}。"))
    provider = CapturingProvider()

    asyncio.run(extract_with_privacy_boundary(provider, prepared_input))

    assert len(provider.captured_inputs) == 1
    assert phone not in provider.captured_inputs[0].redacted_text
    assert "[PHONE_REDACTED]" in provider.captured_inputs[0].redacted_text


@pytest.mark.mutation
@pytest.mark.parametrize(
    ("category", "opaque_value"),
    [
        (PrivacyCategory.PHONE, "opaque-structured-phone-value"),
        (PrivacyCategory.SHIPPING_ADDRESS, "opaque-structured-shipping-value"),
        (PrivacyCategory.ALIPAY_ACCOUNT, "opaque-structured-alipay-value"),
        (PrivacyCategory.MEDICAL_CONTEXT, "opaque-structured-medical-value"),
        (PrivacyCategory.ADVERSE_REACTION, "opaque-structured-adverse-value"),
    ],
    ids=("phone", "shipping-address", "alipay-account", "medical-context", "adverse-reaction"),
)
def test_mutation_replacing_a_generated_projection_is_rejected_before_provider_capture(
    category: PrivacyCategory,
    opaque_value: str,
) -> None:
    prepared_input = sanitize_case_input(
        _case_input("客服承诺尽快更新处理进度。"),
        sensitive_fields=(
            SensitiveField(
                category=category,
                source_id=f"message-opaque-{category.value}",
                value=opaque_value,
            ),
        ),
    )
    bypassed = replace(
        prepared_input,
        model_input=replace(
            prepared_input.model_input,
            redacted_text=f"field={category.value}; opaque_value={opaque_value}",
        ),
    )
    provider = CapturingProvider()

    with pytest.raises(UnsafeModelInputError, match="unsafe unredacted model input was blocked"):
        asyncio.run(extract_with_privacy_boundary(provider, bypassed))

    assert provider.captured_inputs == []


@pytest.mark.mutation
def test_mutation_replacing_generated_projection_provenance_is_rejected_before_capture() -> None:
    prepared_input = sanitize_case_input(_case_input("客服承诺尽快更新处理进度。"))
    bypassed = replace(
        prepared_input,
        model_input=replace(
            prepared_input.model_input,
            source_ids=("order-safe-001", "message-untrusted-001"),
        ),
    )
    provider = CapturingProvider()

    with pytest.raises(UnsafeModelInputError, match="unsafe unredacted model input was blocked"):
        asyncio.run(extract_with_privacy_boundary(provider, bypassed))

    assert provider.captured_inputs == []


@pytest.mark.mutation
def test_directly_constructed_result_is_rejected_before_provider_capture() -> None:
    forged = SanitizationResult(
        model_input=SanitizedModelInput(
            case_id="case-safe-001",
            redacted_text="客服承诺在 48 小时内更新进度。",
            images=(),
            source_ids=("order-safe-001", "message-safe-001"),
        ),
        pii_masked_count=0,
        masked_categories=(),
        adverse_risk_candidate=False,
    )
    provider = CapturingProvider()

    with pytest.raises(UnsafeModelInputError, match="unsafe unredacted model input was blocked"):
        asyncio.run(extract_with_privacy_boundary(provider, forged))

    assert provider.captured_inputs == []


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
