"""Time primitives shared by schema-backed domain objects and clock ports."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated

from jsonschema import FormatChecker
from pydantic import AfterValidator, Strict

_FORMAT_CHECKER = FormatChecker()
_RFC3339_DATETIME_RE = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12][0-9]|3[01])"
    r"[Tt](?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9]):(?P<second>[0-5][0-9]|60)"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)


@_FORMAT_CHECKER.checks("date-time")
def is_rfc3339_datetime(value: object) -> bool:
    """Validate the exact RFC 3339 lexical form used by the locked checker."""

    if not isinstance(value, str):
        return True
    match = _RFC3339_DATETIME_RE.fullmatch(value)
    if match is None:
        return False
    year = int(match["year"])
    month = int(match["month"])
    day = int(match["day"])
    days_in_month = (
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    )
    return day <= days_in_month[month - 1]


def contract_format_checker() -> FormatChecker:
    """Return the shared strict checker used by models and schema validation."""

    return _FORMAT_CHECKER


def require_rfc3339_timestamp(value: str) -> str:
    """Return a strict RFC 3339 date-time string or raise ``ValueError``.

    ``jsonschema`` is also the contract-validation authority, so using its
    registered checker here keeps public model parsing aligned with the locked
    JSON Schema definition (including offsets, lowercase ``t``/``z``, and
    leap-second lexical forms).
    """

    if not contract_format_checker().conforms(value, "date-time"):
        raise ValueError("must be an RFC 3339 date-time with an offset")
    return value


type Rfc3339Timestamp = Annotated[
    str,
    Strict(),
    AfterValidator(require_rfc3339_timestamp),
]


def require_aware_datetime(value: datetime) -> datetime:
    """Reject naive datetimes before they can become trusted clock values."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("trusted clock values must be timezone-aware")
    return value


def format_rfc3339_timestamp(value: datetime) -> str:
    """Format an aware server instant for a public schema field."""

    instant = require_aware_datetime(value)
    rendered = instant.isoformat()
    if instant.utcoffset() == UTC.utcoffset(instant):
        rendered = rendered.replace("+00:00", "Z")
    return require_rfc3339_timestamp(rendered)
