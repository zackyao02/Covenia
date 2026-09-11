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


def test_application_factory_has_no_business_or_documentation_routes() -> None:
    settings = Settings()
    application = create_app(settings)

    assert application.state.settings is settings
    assert application.routes == []
    assert settings.pii_safety_checks_enabled is True


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
