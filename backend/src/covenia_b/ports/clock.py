"""Trusted, timezone-aware clock implementations for later service composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from covenia_b.domain.time import format_rfc3339_timestamp, require_aware_datetime
from covenia_b.ports.errors import ClockConfigurationError


class SystemClock:
    """A real UTC server clock; it performs no persistence or business logic."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def now_rfc3339(self) -> str:
        return format_rfc3339_timestamp(self.now())


@dataclass(frozen=True, slots=True)
class DemoClock:
    """A deliberately injected, fixed aware instant for controlled demonstrations."""

    instant: datetime

    def __post_init__(self) -> None:
        try:
            require_aware_datetime(self.instant)
        except ValueError as error:
            raise ClockConfigurationError(str(error)) from error

    def now(self) -> datetime:
        return self.instant

    def now_rfc3339(self) -> str:
        return format_rfc3339_timestamp(self.instant)
