"""ASGI application factory for the non-business service scaffold."""

from __future__ import annotations

from fastapi import FastAPI

from covenia_b.api.base import install_api_seams
from covenia_b.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an empty application without connecting to external resources."""

    application = FastAPI(
        title="Covenia backend scaffold",
        version="0.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = settings or get_settings()
    install_api_seams(application)
    return application


app = create_app()
