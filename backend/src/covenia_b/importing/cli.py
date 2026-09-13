"""Command-line entry point for deterministic, read-only workbook importing."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from covenia_b.importing.normalization import build_counts, build_provenance, normalize_workbook
from covenia_b.importing.workbook import CompetitionWorkbook


def run_import(workbook_path: str | Path, output_dir: str | Path) -> dict[str, object]:
    """Import one workbook and write only deterministic artifacts below ``output_dir``."""

    workbook = Path(workbook_path).resolve()
    output = Path(output_dir).resolve()
    before = _file_digest(workbook)
    dataset = normalize_workbook(CompetitionWorkbook(workbook))
    after = _file_digest(workbook)
    if before != after:
        raise RuntimeError("Input workbook bytes changed during a read-only import")

    counts = {
        "schema_version": "covenia-b-import-counts-v1",
        "counts": build_counts(dataset),
    }
    provenance = build_provenance(dataset)
    input_hashes = {
        "schema_version": "covenia-b-import-input-hashes-v1",
        "workbook": {
            "file_name": workbook.name,
            "size_bytes": before["size_bytes"],
            "sha256": before["sha256"],
            "hash_method": "sha256 over raw input bytes",
            "unchanged_after_import": True,
        },
    }

    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "counts": output / "counts.json",
        "provenance": output / "provenance.json",
        "input_hashes": output / "input-hashes.json",
    }
    _write_json(paths["counts"], counts)
    _write_json(paths["provenance"], provenance)
    _write_json(paths["input_hashes"], input_hashes)
    return {
        "output_dir": str(output),
        "counts": counts["counts"],
        "artifacts": {name: str(path) for name, path in paths.items()},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    result = run_import(arguments.workbook, arguments.output)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _file_digest(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
    return {"size_bytes": size_bytes, "sha256": digest.hexdigest().upper()}


def _write_json(path: Path, payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
