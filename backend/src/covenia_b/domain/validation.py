"""JSON Schema validation entry points for the locked public contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from covenia_b.domain.time import contract_format_checker


class ContractValidationError(ValueError):
    """Raised when a payload does not satisfy one of the locked schemas."""


def _repository_root() -> Path:
    """Locate the checkout without relying on a caller's working directory."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "schemas").is_dir() and (parent / "docs" / "contracts").is_dir():
            return parent
    raise RuntimeError("unable to locate the Covenia checkout schema directory")


@lru_cache
def contract_schema_directory() -> Path:
    """Return the immutable schema directory used by the BATCH-03 lock."""

    return _repository_root() / "schemas"


@lru_cache
def load_contract_schemas() -> dict[str, dict[str, Any]]:
    """Load every locked schema once, keyed by its file name."""

    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(contract_schema_directory().glob("*.schema.json")):
        with path.open(encoding="utf-8") as handle:
            schemas[path.name] = json.load(handle)
    return schemas


@lru_cache
def contract_registry() -> Registry:
    """Build a local registry so cross-schema ``$ref`` values remain locked."""

    resources = (
        (schema["$id"], Resource.from_contents(schema))
        for schema in load_contract_schemas().values()
    )
    return Registry().with_resources(resources)


@lru_cache
def validator_for(schema_name: str) -> Draft202012Validator:
    """Return a strict Draft 2020-12 validator for one named public schema."""

    try:
        schema = load_contract_schemas()[schema_name]
    except KeyError as error:
        raise KeyError(f"unknown locked contract schema: {schema_name}") from error
    return Draft202012Validator(
        schema,
        registry=contract_registry(),
        format_checker=contract_format_checker(),
    )


def validation_messages(schema_name: str, payload: Any) -> tuple[str, ...]:
    """Return stable, human-readable validation messages without mutating data."""

    errors = sorted(
        validator_for(schema_name).iter_errors(payload),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    return tuple(
        f"{schema_name} at "
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors
    )


def validate_contract_payload(schema_name: str, payload: Any) -> None:
    """Raise ``ContractValidationError`` when the locked schema rejects payload."""

    messages = validation_messages(schema_name, payload)
    if messages:
        raise ContractValidationError("; ".join(messages))
