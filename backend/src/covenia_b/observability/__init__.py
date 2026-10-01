"""Safe runtime measurements and governance audit logging.

This module is deliberately separate from the frozen domain and port packages.
It implements the existing ``MetricsSink`` shape through a request-scoped
session while retaining the provenance that the small public metric contract
cannot carry.
"""

from covenia_b.observability.runtime import (
    LOCKED_MODEL_ID,
    CacheStatus,
    ExactTokenCounter,
    GovernanceContext,
    GovernanceLogWriteError,
    GovernanceSession,
    InMemoryGovernanceSink,
    InputSourceKind,
    JsonlGovernanceSink,
    MeasurementConfigurationError,
    ModelAttempt,
    ModelIdentity,
    ProviderUsage,
    RuntimeMetricsCollector,
    SafeInputSource,
)

__all__ = [
    "CacheStatus",
    "ExactTokenCounter",
    "GovernanceContext",
    "GovernanceLogWriteError",
    "GovernanceSession",
    "InMemoryGovernanceSink",
    "InputSourceKind",
    "JsonlGovernanceSink",
    "LOCKED_MODEL_ID",
    "MeasurementConfigurationError",
    "ModelAttempt",
    "ModelIdentity",
    "ProviderUsage",
    "RuntimeMetricsCollector",
    "SafeInputSource",
]
