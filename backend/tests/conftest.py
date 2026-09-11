"""Shared test fixtures for backend modules."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def temporary_runtime_dir(tmp_path: Path) -> Path:
    """Provide an isolated empty runtime directory with no case data or conclusions."""

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    return runtime_dir
