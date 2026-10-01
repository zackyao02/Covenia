from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from covenia_b.receipts import (
    NotificationDraft,
    ProgressLedger,
    ProgressStatus,
    project_progress,
)

LATEST_UPDATE = datetime.fromisoformat("2030-01-01T10:30:00+00:00")
NEXT_CHECK = datetime.fromisoformat("2030-01-01T11:00:00+00:00")
RECEIPT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "accountability-state.schema.json"
)


def _receipt_validator() -> Draft202012Validator:
    accountability_schema = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    receipt_schema = accountability_schema["properties"]["service_progress_receipt"]
    return Draft202012Validator(receipt_schema, format_checker=FormatChecker())


def _ledger(status: ProgressStatus = ProgressStatus.AT_RISK) -> ProgressLedger:
    return ProgressLedger(
        receipt_id="RECEIPT-17-001",
        status=status,
        received_evidence=("Package image received",),
        brand_action="The brand is following up on the replacement.",
        latest_update_at=LATEST_UPDATE,
        next_check_at=None if status is ProgressStatus.COMPLETED else NEXT_CHECK,
        recovery_if_missed="The brand will provide another update.",
        internal_note="warehouse escalation owner: internal-only",
    )


def test_at_risk_uses_one_instant_for_check_receipt_draft_and_text() -> None:
    projection = project_progress(_ledger())
    draft = projection.proactive_notification_draft

    assert projection.next_check_at == NEXT_CHECK
    assert projection.receipt.next_update_by == NEXT_CHECK
    assert draft is not None
    assert draft.commits_next_update_at == NEXT_CHECK
    assert NEXT_CHECK.isoformat(timespec="seconds") in draft.text
    assert draft.requires_human_approval is True
    assert draft.is_sent is False


def test_manual_next_update_edit_reprojects_every_open_projection() -> None:
    edited_next_check = NEXT_CHECK + timedelta(minutes=30)
    projection = project_progress(replace(_ledger(), next_check_at=edited_next_check))
    draft = projection.proactive_notification_draft

    assert projection.next_check_at == edited_next_check
    assert projection.receipt.next_update_by == edited_next_check
    assert draft is not None
    assert draft.commits_next_update_at == edited_next_check
    assert edited_next_check.isoformat(timespec="seconds") in draft.text
    assert NEXT_CHECK.isoformat(timespec="seconds") not in draft.text


@pytest.mark.parametrize("status", [ProgressStatus.ACTIVE, ProgressStatus.AT_RISK])
def test_open_states_remain_brand_accountable_without_consumer_action(
    status: ProgressStatus,
) -> None:
    projection = project_progress(_ledger(status))

    assert projection.receipt.next_update_state == "SCHEDULED"
    assert projection.receipt.consumer_action_required is False
    assert projection.receipt.latest_update_at < projection.receipt.next_update_by


def test_completed_is_terminal_not_a_future_update_or_notification() -> None:
    projection = project_progress(_ledger(ProgressStatus.COMPLETED))

    assert projection.next_check_at is None
    assert projection.receipt.next_update_state == "TERMINAL"
    assert projection.receipt.next_update_by is None
    assert projection.receipt.latest_update_at == LATEST_UPDATE
    assert projection.receipt.consumer_action_required is False
    assert projection.proactive_notification_draft is None


def test_consumer_view_excludes_internal_draft_and_internal_ledger_context() -> None:
    consumer_view = project_progress(_ledger()).receipt.consumer_view()

    rendered = repr(consumer_view)
    assert "proactive_notification_draft" not in consumer_view
    assert "next_update_state" not in consumer_view
    assert "internal_note" not in consumer_view
    assert "warehouse escalation owner" not in rendered


@pytest.mark.parametrize(
    "status",
    [ProgressStatus.ACTIVE, ProgressStatus.AT_RISK, ProgressStatus.COMPLETED],
)
def test_consumer_view_conforms_to_current_service_progress_receipt_schema(
    status: ProgressStatus,
) -> None:
    consumer_view = project_progress(_ledger(status)).receipt.consumer_view()

    _receipt_validator().validate(consumer_view)


def test_current_schema_rejects_internal_state_as_an_extra_consumer_field() -> None:
    projection = project_progress(_ledger())
    consumer_view = projection.receipt.consumer_view()
    consumer_view["next_update_state"] = projection.receipt.next_update_state

    with pytest.raises(ValidationError, match="Additional properties"):
        _receipt_validator().validate(consumer_view)


def test_terminal_validation_rejects_future_updates_and_notification_drafts() -> None:
    projection = project_progress(_ledger(ProgressStatus.COMPLETED))
    future_draft = NotificationDraft(
        text=f"The next update will follow by {NEXT_CHECK.isoformat(timespec='seconds')}.",
        commits_next_update_at=NEXT_CHECK,
    )
    invalid_projections = (
        replace(projection, next_check_at=NEXT_CHECK),
        replace(
            projection,
            receipt=replace(projection.receipt, next_update_by=NEXT_CHECK),
        ),
        replace(projection, proactive_notification_draft=future_draft),
    )

    for invalid_projection in invalid_projections:
        with pytest.raises(ValueError, match="terminal receipt"):
            invalid_projection.validate()


def test_scheduled_validation_rejects_each_mismatched_time_projection() -> None:
    projection = project_progress(_ledger(ProgressStatus.ACTIVE))
    mismatched_time = NEXT_CHECK + timedelta(minutes=15)
    mismatched_draft = NotificationDraft(
        text=(
            "The next update will follow by "
            f"{mismatched_time.isoformat(timespec='seconds')}."
        ),
        commits_next_update_at=mismatched_time,
    )
    invalid_projections = (
        replace(projection, next_check_at=mismatched_time),
        replace(
            projection,
            receipt=replace(projection.receipt, next_update_by=mismatched_time),
        ),
        replace(projection, proactive_notification_draft=mismatched_draft),
    )

    for invalid_projection in invalid_projections:
        with pytest.raises(ValueError, match="must equal next_check_at"):
            invalid_projection.validate()


def test_internal_schedule_marker_must_match_receipt_progress_status() -> None:
    scheduled = project_progress(_ledger(ProgressStatus.ACTIVE))
    terminal = project_progress(_ledger(ProgressStatus.COMPLETED))

    with pytest.raises(ValueError, match="internal next_update_state"):
        replace(
            scheduled,
            receipt=replace(scheduled.receipt, next_update_state="TERMINAL"),
        ).validate()
    with pytest.raises(ValueError, match="internal next_update_state"):
        replace(
            terminal,
            receipt=replace(terminal.receipt, next_update_state="SCHEDULED"),
        ).validate()


def test_open_progress_rejects_latest_update_as_a_future_update() -> None:
    with pytest.raises(ValueError, match="later than latest_update_at"):
        replace(_ledger(), next_check_at=LATEST_UPDATE)


def test_tampered_draft_text_fails_the_one_instant_invariant() -> None:
    wrong_time = NEXT_CHECK + timedelta(minutes=30)

    with pytest.raises(ValueError, match="commits_next_update_at"):
        NotificationDraft(
            text=f"The next update will follow by {wrong_time.isoformat(timespec='seconds')}.",
            commits_next_update_at=NEXT_CHECK,
        )
