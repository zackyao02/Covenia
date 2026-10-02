from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from covenia_b.receipts import (
    NotificationDraft,
    ProgressLedger,
    ProgressStatus,
    project_progress,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO_ROOT / "schemas" / "accountability-state.schema.json"
BASE_TIME = datetime(2034, 7, 11, 3, 17, 29, tzinfo=timezone.utc)
NEXT_TIME = BASE_TIME + timedelta(minutes=43)


def receipt_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(
        schema["properties"]["service_progress_receipt"],
        format_checker=FormatChecker(),
    )


def ledger(status: ProgressStatus) -> ProgressLedger:
    return ProgressLedger(
        receipt_id=f"AUDIT-V17-{status.value}-9471",
        status=status,
        received_evidence=("AUDIT_EVIDENCE_9471",),
        brand_action="The brand owns the next service update.",
        latest_update_at=BASE_TIME,
        next_check_at=None if status is ProgressStatus.COMPLETED else NEXT_TIME,
        recovery_if_missed="The brand must provide a revised update.",
        internal_note="AUDIT_INTERNAL_ONLY_9471",
    )


def expect_value_error(name: str, action, expected_text: str) -> dict[str, str]:
    try:
        action()
    except ValueError as exc:
        message = str(exc)
        if expected_text not in message:
            raise AssertionError(
                f"{name}: wrong ValueError: expected {expected_text!r}, got {message!r}"
            ) from exc
        return {"case": name, "result": "EXPECTED_REJECTION", "error": message}
    raise AssertionError(f"{name}: invalid projection was accepted")


def main() -> None:
    validator = receipt_validator()
    positives: list[dict[str, object]] = []

    for status in (
        ProgressStatus.ACTIVE,
        ProgressStatus.AT_RISK,
        ProgressStatus.COMPLETED,
    ):
        projection = project_progress(ledger(status))
        consumer = projection.receipt.consumer_view()
        validator.validate(consumer)
        assert "next_update_state" not in consumer
        assert "internal_note" not in consumer
        assert "proactive_notification_draft" not in consumer

        if status is ProgressStatus.COMPLETED:
            assert projection.next_check_at is None
            assert projection.receipt.next_update_by is None
            assert projection.proactive_notification_draft is None
            timing = {
                "next_check_at": None,
                "next_update_by": None,
                "draft": None,
            }
        else:
            draft = projection.proactive_notification_draft
            assert draft is not None
            assert (
                projection.next_check_at
                == projection.receipt.next_update_by
                == draft.commits_next_update_at
            )
            assert draft.commits_next_update_at.isoformat(timespec="seconds") in draft.text
            assert draft.requires_human_approval is True
            assert draft.is_sent is False
            timing = {
                "next_check_at": projection.next_check_at.isoformat(),
                "next_update_by": projection.receipt.next_update_by.isoformat(),
                "commits_next_update_at": draft.commits_next_update_at.isoformat(),
            }

        positives.append(
            {
                "status": status.value,
                "schema": "PASS",
                "consumer_keys": sorted(consumer),
                "next_update_state_public": False,
                "timing": timing,
            }
        )

    terminal = project_progress(ledger(ProgressStatus.COMPLETED))
    active = project_progress(ledger(ProgressStatus.ACTIVE))
    mismatch = NEXT_TIME + timedelta(minutes=19)
    future_draft = NotificationDraft(
        text=f"The next update will follow by {NEXT_TIME.isoformat(timespec='seconds')}.",
        commits_next_update_at=NEXT_TIME,
    )
    mismatched_draft = NotificationDraft(
        text=f"The next update will follow by {mismatch.isoformat(timespec='seconds')}.",
        commits_next_update_at=mismatch,
    )

    negatives = [
        expect_value_error(
            "terminal_future_next_check_at",
            lambda: replace(terminal, next_check_at=NEXT_TIME).validate(),
            "terminal receipt",
        ),
        expect_value_error(
            "terminal_future_next_update_by",
            lambda: replace(
                terminal,
                receipt=replace(terminal.receipt, next_update_by=NEXT_TIME),
            ).validate(),
            "terminal receipt",
        ),
        expect_value_error(
            "terminal_notification_draft",
            lambda: replace(terminal, proactive_notification_draft=future_draft).validate(),
            "terminal receipt",
        ),
        expect_value_error(
            "scheduled_next_check_at_mismatch",
            lambda: replace(active, next_check_at=mismatch).validate(),
            "must equal next_check_at",
        ),
        expect_value_error(
            "scheduled_next_update_by_mismatch",
            lambda: replace(
                active,
                receipt=replace(active.receipt, next_update_by=mismatch),
            ).validate(),
            "must equal next_check_at",
        ),
        expect_value_error(
            "scheduled_commits_next_update_at_mismatch",
            lambda: replace(active, proactive_notification_draft=mismatched_draft).validate(),
            "must equal next_check_at",
        ),
        expect_value_error(
            "notification_text_time_mismatch",
            lambda: NotificationDraft(
                text=f"The next update will follow by {mismatch.isoformat(timespec='seconds')}.",
                commits_next_update_at=NEXT_TIME,
            ),
            "notification text must contain commits_next_update_at",
        ),
    ]

    tampered_consumer = active.receipt.consumer_view()
    tampered_consumer["next_update_state"] = active.receipt.next_update_state
    try:
        validator.validate(tampered_consumer)
    except ValidationError as exc:
        negatives.append(
            {
                "case": "public_next_update_state_extra_field",
                "result": "EXPECTED_SCHEMA_REJECTION",
                "error": exc.message,
            }
        )
    else:
        raise AssertionError("schema accepted public next_update_state")

    print(
        json.dumps(
            {
                "result": "PASS",
                "probe": "independent BATCH-17 projection and schema probe",
                "schema_path": str(SCHEMA_PATH),
                "positive_cases": positives,
                "negative_cases": negatives,
                "summary": {
                    "positive_states": 3,
                    "expected_runtime_rejections": 7,
                    "expected_schema_rejections": 1,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
