"""Bootstrap tests for the installable, non-business backend scaffold."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from covenia_b import __version__
from covenia_b.api.base import ApiError, normalize_request_id
from covenia_b.main import create_app
from covenia_b.settings import Settings


def test_package_imports_with_scaffold_version() -> None:
    assert __version__ == "0.0.0"


# Cross-line maintenance task, basis CROSS-LINE-BOOTSTRAP-TEST-BASELINE-20261005.
# Supersedes test_application_factory_has_no_business_or_documentation_routes,
# whose "empty application" invariant (application.routes == []) directly
# contradicted BATCH-27 acceptance_criteria #1 ("exactly four business POST
# endpoints"). The invariant is STRENGTHENED, not weakened: the composition root
# must expose exactly the four approved operations, with no documentation route
# and no fifth business route. The two retained assertions are unchanged.
#
# Route paths follow BATCH-27's route-inventory.json (the delivered fact).
# Note: approve is mounted at /api/resolutions/approve -- the real constant in
# api/approve.py -- not /api/actions/approve as the dispatch brief guessed.

_EXPECTED_BUSINESS_OPERATIONS = (
    ("/api/actions/evaluate", ("POST",)),
    ("/api/cases/analyze", ("POST",)),
    ("/api/events/shipment", ("POST",)),
    ("/api/resolutions/approve", ("POST",)),
)

_FORBIDDEN_ROUTE_PATHS = frozenset(
    {
        "/health",
        "/healthz",
        "/ready",
        "/live",
        "/reset",
        "/query",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)


def test_application_factory_exposes_exactly_the_four_business_routes() -> None:
    settings = Settings()
    application = create_app(settings)

    # Retained from the superseded test, unchanged.
    assert application.state.settings is settings
    assert settings.pii_safety_checks_enabled is True

    # The competition build keeps every interactive documentation endpoint closed.
    assert application.docs_url is None
    assert application.redoc_url is None
    assert application.openapi_url is None

    mounted = tuple(
        (route.path, tuple(sorted(route.methods or ()))) for route in application.routes
    )

    # No extra route of any kind: the mounted table is exactly the four operations.
    assert len(application.routes) == len(_EXPECTED_BUSINESS_OPERATIONS)
    assert sorted(mounted) == sorted(_EXPECTED_BUSINESS_OPERATIONS)

    # Every operation is a POST, and no prohibited path is reachable.
    assert all(methods == ("POST",) for _, methods in mounted)
    assert {path for path, _ in mounted}.isdisjoint(_FORBIDDEN_ROUTE_PATHS)


def test_settings_only_describe_resources_without_opening_them() -> None:
    settings = Settings()

    assert settings.image_root == Path("data/images")
    assert settings.sqlite_path == Path("runtime/covenia.sqlite3")
    assert settings.cache_mode == "disabled"


def test_request_id_normalization_and_error_envelope_are_transport_only() -> None:
    request_id = normalize_request_id("7e650df5-a8dd-40e3-aad1-348acf770649")
    payload = ApiError(
        code="INTERNAL_ERROR",
        message="The scaffold has no business handler.",
    ).as_payload(request_id)

    assert request_id == "7e650df5-a8dd-40e3-aad1-348acf770649"
    assert UUID(normalize_request_id("not-a-uuid")).version == 4
    assert payload == {
        "data": None,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "The scaffold has no business handler.",
            "retryable": False,
        },
        "request_id": request_id,
    }
