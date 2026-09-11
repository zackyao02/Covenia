"""Safe, side-effect-free runtime configuration for the service scaffold."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration inventory without I/O, secret fields, or service clients."""

    model_config = SettingsConfigDict(
        env_prefix="COVENIA_",
        extra="ignore",
        frozen=True,
    )

    model_endpoint: str = "http://127.0.0.1:8001"
    image_root: Path = Path("data/images")
    sqlite_path: Path = Path("runtime/covenia.sqlite3")
    allowed_origin: str = "http://localhost:5173"
    demo_clock: str = "system"
    cache_mode: Literal["disabled", "memory", "file"] = "disabled"
    pii_safety_checks_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings snapshot without opening external resources."""

    return Settings()
