"""Storage-only DTOs and errors; services own transport error mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from covenia_b.domain.types import LedgerSnapshot
from covenia_b.ports.errors import LedgerConflict


class IdempotencyConflict(LedgerConflict):
    """A case-scoped request key or event identity was reused with different content."""

    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True, slots=True)
class StoredResponse:
    """The first complete envelope, HTTP status, and service-supplied headers."""

    body: dict[str, Any]
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EventRecord:
    event_id: str
    event_type: str
    event_time: str


@dataclass(frozen=True, slots=True)
class Mutation:
    """A pure service callback's proposed snapshot and response."""

    snapshot: LedgerSnapshot
    response: StoredResponse


@dataclass(frozen=True, slots=True)
class TransactionResult:
    snapshot: LedgerSnapshot
    response: StoredResponse
    replayed: bool
    replay_source: str | None = None
