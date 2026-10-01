"""Versioned JSON encoding, request fingerprints and exact timestamp ordering."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any

from covenia_b.domain.time import Rfc3339Timestamp, require_rfc3339_timestamp
from covenia_b.domain.types import (
    AccountabilityState,
    ApiEnvelope,
    CompiledCommitment,
    CompiledCommitments,
    LedgerSnapshot,
    ServiceProgressReceipt,
)
from covenia_b.storage.models import EventRecord, StoredResponse


class StoredReceipt(ServiceProgressReceipt):
    """f507e37 schema compatibility, localized until the owner updates its DTO."""

    next_update_by: Rfc3339Timestamp | None


class StoredAccountabilityState(AccountabilityState):
    """The current schema's receipt type; no invented terminal update instant."""

    service_progress_receipt: StoredReceipt | None


def canonical_json(value: Any) -> str:
    """Sorted object keys, compact UTF-8 JSON; array order and scalar types retained."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def request_digest(operation: str, body: Mapping[str, Any]) -> str:
    # Only top-level transport metadata is excluded. Nested business fields remain.
    cleaned = {
        key: value
        for key, value in body.items()
        if key.casefold() not in {"request_id", "x-request-id"}
    }
    return hashlib.sha256(
        canonical_json({"operation": operation, "body": cleaned}).encode("utf-8")
    ).hexdigest()


def time_order(value: str) -> Decimal:
    """Exact UTC ordering including fractions beyond datetime's microsecond precision."""

    require_rfc3339_timestamp(value)
    match = re.fullmatch(r"(.{10})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})", value)
    if match is None:
        raise ValueError("invalid timestamp")
    date, hour, minute, second, fraction, offset = match.groups()
    parsed = datetime.fromisoformat(date)
    offset_seconds = 0
    if offset not in {"Z", "z"}:
        sign = 1 if offset[0] == "+" else -1
        offset_seconds = sign * (int(offset[1:3]) * 3600 + int(offset[4:6]) * 60)
    # A lexical leap second is ordered at the following second, consistently on replay.
    utc = parsed + timedelta(hours=int(hour), minutes=int(minute), seconds=int(second))
    seconds = utc.toordinal() * 86400 + utc.hour * 3600 + utc.minute * 60 + utc.second
    with localcontext() as context:
        context.prec = max(28, len(fraction or "") + 20)
        return Decimal(seconds - offset_seconds) + Decimal(fraction or "0")


def event_digest(event: EventRecord) -> str:
    instant = format(time_order(event.event_time), "f")
    if "." in instant:
        instant = instant.rstrip("0").rstrip(".")
    payload = {"event_type": event.event_type, "utc_time": instant}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def encode_snapshot(snapshot: LedgerSnapshot) -> str:
    state = snapshot.accountability_state
    return canonical_json(
        {
            "format_version": 1,
            "case_id": snapshot.case_id,
            "version": snapshot.version,
            "event_high_watermark": snapshot.event_high_watermark,
            "accountability_state": state.to_contract() if state is not None else None,
            "compiled_commitments": asdict(snapshot.compiled_commitments),
        }
    )


def decode_snapshot(encoded: str) -> LedgerSnapshot:
    value = json.loads(encoded)
    if value["format_version"] != 1:
        raise ValueError("unsupported snapshot format")
    payload = value["accountability_state"]
    state = None
    if payload is not None:
        receipt = payload.get("service_progress_receipt")
        model = (
            StoredAccountabilityState
            if receipt and receipt["next_update_by"] is None
            else AccountabilityState
        )
        state = model.from_contract(payload)
    compiled = value["compiled_commitments"]
    return LedgerSnapshot(
        case_id=value["case_id"],
        version=value["version"],
        event_high_watermark=value["event_high_watermark"],
        accountability_state=state,
        compiled_commitments=CompiledCommitments(
            commitments=tuple(CompiledCommitment(**entry) for entry in compiled["commitments"]),
            compiled_from_evidence=compiled["compiled_from_evidence"],
        ),
    )


def encode_response(response: StoredResponse) -> str:
    ApiEnvelope.from_contract(response.body)
    if type(response.status_code) is not int or not 100 <= response.status_code <= 599:
        raise ValueError("invalid response status")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in response.headers.items()):
        raise ValueError("invalid response headers")
    return canonical_json(
        {"body": response.body, "status_code": response.status_code, "headers": response.headers}
    )


def decode_response(encoded: str) -> StoredResponse:
    value = json.loads(encoded)
    response = StoredResponse(**value)
    encode_response(response)
    return response
