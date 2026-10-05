"""Safe, side-effect-free runtime configuration for the Covenia backend.

The object is an inventory only: constructing it performs no I/O, opens no
client, and holds no secret.  The one value an operator may keep outside the
object is the model API key, which :mod:`covenia_b.runtime` reads directly from
``COVENIA_MODEL_API_KEY`` at provider-construction time.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://localhost:5173",
)


class Settings(BaseSettings):
    """Configuration inventory without I/O, secret fields, or service clients."""

    model_config = SettingsConfigDict(
        env_prefix="COVENIA_",
        extra="ignore",
        frozen=True,
    )

    # Local transport.  The listener is loopback-only by contract; ``main``
    # refuses a non-loopback host even when one is supplied on the CLI.
    listen_host: str = "127.0.0.1"
    listen_port: int = 8000
    allowed_origin: str = "http://localhost:5173"
    allowed_origins: str = ",".join(DEFAULT_ALLOWED_ORIGINS)

    # Local A-owned and competition inputs.  Relative paths resolve against the
    # process working directory (the repository root for every planned command).
    workbook_path: Path = Path("data/tianchi-track1-mock-data.xlsx")
    demo_cases_path: Path = Path("fixtures/demo-cases.json")
    case_manifest_path: Path = Path("handoff/a/cases-manifest.json")
    image_manifest_path: Path = Path("handoff/a/images-manifest.json")
    image_evidence_root: Path = Path("frontend/public/evidence")
    image_root: Path = Path("data/images")
    sqlite_path: Path = Path("runtime/covenia.sqlite3")
    request_log_path: Path = Path("runtime/logs/requests.jsonl")

    # Model deployment.  Registration is an external gate; an empty
    # ``model_deployment_id`` means "not registered yet" and is reported as a
    # blocker by ``covenia_b.preflight`` instead of being silently replaced.
    model_endpoint: str = "http://127.0.0.1:8001"
    model_revision: str = "local-unregistered-revision"
    model_prompt_version: str = "candidate-extraction-v1"
    model_deployment_id: str = ""

    # Service budgets.
    analysis_timeout_seconds: float = 20.0
    evaluate_budget_seconds: float = 10.0

    demo_clock: str = "system"
    cache_mode: Literal["disabled", "memory", "file"] = "disabled"
    pii_safety_checks_enabled: bool = True

    @property
    def cors_origins(self) -> tuple[str, ...]:
        """Return the approved browser origins as an ordered, duplicate-free tuple."""

        entries = [*self.allowed_origins.split(","), self.allowed_origin]
        ordered: list[str] = []
        for entry in entries:
            origin = entry.strip()
            if origin and origin not in ordered:
                ordered.append(origin)
        return tuple(ordered)


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings snapshot without opening external resources."""

    return Settings()
