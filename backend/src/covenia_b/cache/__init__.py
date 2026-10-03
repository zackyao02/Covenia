"""Explicit, provenance-safe extraction-cache fallback primitives.

The cache package deliberately decorates only the model extraction port.  It
does not cache a response, a decision, a ledger snapshot, or any live state.
"""

from .extraction_fallback import (
    CacheFallbackEvent,
    CacheFallbackReason,
    CacheFallbackUnavailable,
    CacheGovernanceSink,
    CacheRequestContext,
    CacheVersionSet,
    CachingExtractionProvider,
    InMemoryCacheGovernanceSink,
    build_extraction_cache_key,
)

__all__ = [
    "CacheFallbackEvent",
    "CacheFallbackReason",
    "CacheFallbackUnavailable",
    "CacheGovernanceSink",
    "CacheRequestContext",
    "CacheVersionSet",
    "CachingExtractionProvider",
    "InMemoryCacheGovernanceSink",
    "build_extraction_cache_key",
]
