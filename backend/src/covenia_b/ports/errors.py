"""Provider-neutral errors for the BATCH-04 module ports."""

from __future__ import annotations


class PortError(Exception):
    """Base error for an adapter boundary; later services map it to transport."""


class CaseNotFound(PortError):
    """The requested case is absent from the configured case source."""


class WorkbookUnavailable(PortError):
    """A workbook cannot be opened or enumerated by its adapter."""


class ImageUnavailable(PortError):
    """A declared evidence image cannot be resolved by its adapter."""


class ImageUnreadable(PortError):
    """An image bytes source exists but cannot be safely read."""


class ModelUnavailable(PortError):
    """The configured model provider is unavailable before producing a candidate."""


class ModelOutputInvalid(PortError):
    """A provider returned data that cannot become a candidate extraction."""


class ExtractionStoreUnavailable(PortError):
    """The candidate extraction cache or persistence adapter is unavailable."""


class LedgerConflict(PortError):
    """An optimistic ledger version or event high-watermark check failed."""


class LedgerUnavailable(PortError):
    """The ledger adapter cannot load or persist a snapshot."""


class MetricsUnavailable(PortError):
    """The optional metrics adapter cannot accept a safe metric record."""


class ClockConfigurationError(PortError, ValueError):
    """A clock was configured with a naive or otherwise untrusted instant."""
