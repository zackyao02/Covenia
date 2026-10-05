"""Startup preflight for the assembled backend: ``python -m covenia_b.preflight``.

The check is deliberately read-only apart from two bounded probes: it opens the
configured SQLite ledger (which is the real writability test) and, unless
``--offline`` is given, opens one TCP connection to the registered model
endpoint.  It never calls the model, never fabricates a case result, and never
serves a request.  A missing workbook, image manifest, ledger, or model
deployment is reported as a blocker instead of being silently replaced by a
substitute.

Exit codes: ``0`` the report was written (blockers are data, listed in the
report and on stdout); ``2`` with ``--fail-on-blocker`` when a blocker exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from covenia_b.ports.errors import PortError
from covenia_b.runtime import (
    build_runtime,
    compose_application,
    missing_model_settings,
    route_inventory_document,
)
from covenia_b.settings import Settings, get_settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_REPORT_DIR = Path("reports/batches/BATCH-27")
SHORT_PATH_LIMIT = 250
VENV_PATH_LIMIT = 250


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def check_workbook(path: Path) -> dict[str, Any]:
    """Open, parse and normalize the competition workbook without writing."""

    resolved = path if path.is_absolute() else (Path.cwd() / path)
    record: dict[str, Any] = {
        "id": "workbook",
        "path": str(resolved),
        "required": True,
    }
    if not resolved.is_file():
        return {**record, "status": "BLOCKED", "reason": "the configured workbook is missing"}
    try:
        from covenia_b.importing.normalization import build_counts, normalize_workbook
        from covenia_b.importing.workbook import CompetitionWorkbook

        workbook = CompetitionWorkbook(resolved)
        dataset = normalize_workbook(workbook)
        sheet_names = list(workbook.sheet_names())
        counts = build_counts(dataset)
    except (PortError, ValueError, OSError) as error:
        return {
            **record,
            "status": "BLOCKED",
            "reason": "the configured workbook cannot be normalized",
            "error_type": type(error).__name__,
        }
    if not counts:
        return {**record, "status": "BLOCKED", "reason": "the workbook normalized to no records"}
    return {
        **record,
        "status": "READY",
        "sheets": sheet_names,
        "record_counts": counts,
        "sha256": _sha256(resolved),
    }


def check_case_source(settings: Settings) -> dict[str, Any]:
    """Prove the accepted case catalog can be joined with the workbook rows."""

    record: dict[str, Any] = {
        "id": "case_source",
        "workbook": str(settings.workbook_path),
        "demo_cases": str(settings.demo_cases_path),
        "manifest": str(settings.case_manifest_path),
        "required": True,
    }
    try:
        from covenia_b.importing.case_assembler import CaseAssembler

        assembler = CaseAssembler.from_paths(
            settings.workbook_path,
            settings.demo_cases_path,
            settings.case_manifest_path,
        )
        case_ids = sorted(assembler.catalog.case_ids)
    except (PortError, ValueError, OSError, KeyError) as error:
        return {
            **record,
            "status": "BLOCKED",
            "reason": "the accepted demo catalog cannot be loaded against the workbook",
            "error_type": type(error).__name__,
            "error": str(error)[:300],
        }
    if not case_ids:
        return {**record, "status": "BLOCKED", "reason": "the case catalog declares no case"}
    return {**record, "status": "READY", "case_ids": case_ids}


def check_image_manifest(settings: Settings) -> dict[str, Any]:
    """Verify the accepted image manifest and every registered evidence file."""

    manifest_path = (
        settings.image_manifest_path
        if settings.image_manifest_path.is_absolute()
        else Path.cwd() / settings.image_manifest_path
    )
    evidence_root = (
        settings.image_evidence_root
        if settings.image_evidence_root.is_absolute()
        else Path.cwd() / settings.image_evidence_root
    )
    record: dict[str, Any] = {
        "id": "image_manifest",
        "manifest": str(manifest_path),
        "evidence_root": str(evidence_root),
        "required": True,
        "images": [],
    }
    if not manifest_path.is_file():
        return {**record, "status": "BLOCKED", "reason": "the image manifest is missing"}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {**record, "status": "BLOCKED", "reason": "the image manifest is not readable JSON"}
    if not isinstance(raw, dict) or not isinstance(raw.get("images"), list):
        return {**record, "status": "BLOCKED", "reason": "the image manifest has no images list"}
    if raw.get("status") != "ACCEPTED":
        return {
            **record,
            "status": "BLOCKED",
            "reason": "the image manifest is not in the accepted A-line state",
            "manifest_status": raw.get("status"),
        }

    try:
        from covenia_b.images import ManifestImageResolver
        from covenia_b.services.fact_loader import ImageSafetyDeclarations

        ManifestImageResolver.from_manifest_file(
            manifest_path=manifest_path, evidence_root=evidence_root
        )
        ImageSafetyDeclarations.from_accepted_manifest(manifest_path)
    except (PortError, ValueError, OSError, KeyError) as error:
        return {
            **record,
            "status": "BLOCKED",
            "reason": "the image manifest is rejected by the production resolver",
            "error_type": type(error).__name__,
        }

    images: list[dict[str, Any]] = []
    blocked: list[str] = []
    for entry in raw["images"]:
        if not isinstance(entry, dict):
            blocked.append("an image entry is not an object")
            continue
        file_name = str(entry.get("file_name"))
        target = evidence_root / file_name
        detail: dict[str, Any] = {
            "evidence_id": entry.get("evidence_id"),
            "file_name": file_name,
            "no_pii_declaration": entry.get("no_pii_declaration") is True,
        }
        if entry.get("no_pii_declaration") is not True:
            detail["status"] = "BLOCKED"
            blocked.append(f"{file_name} has no accepted no-PII declaration")
        elif not target.is_file():
            detail["status"] = "BLOCKED"
            blocked.append(f"{file_name} is missing under the evidence root")
        else:
            payload = target.read_bytes()
            digest = hashlib.sha256(payload).hexdigest().upper()
            declared = str(entry.get("sha256", "")).upper()
            detail["sha256"] = digest
            detail["bytes"] = len(payload)
            if digest != declared or len(payload) != entry.get("bytes"):
                detail["status"] = "BLOCKED"
                blocked.append(f"{file_name} does not match its declared sha256/byte length")
            else:
                detail["status"] = "READY"
        images.append(detail)

    record["images"] = images
    record["manifest_sha256"] = _sha256(manifest_path)
    record["image_count"] = len(images)
    if blocked or not images:
        record["status"] = "BLOCKED"
        record["reason"] = blocked or ["the manifest registers no image"]
    else:
        record["status"] = "READY"
    return record


def check_sqlite(settings: Settings) -> dict[str, Any]:
    """Prove the configured ledger path is writable and is a Covenia database."""

    path = (
        settings.sqlite_path
        if settings.sqlite_path.is_absolute()
        else Path.cwd() / settings.sqlite_path
    )
    record: dict[str, Any] = {"id": "sqlite", "path": str(path), "required": True}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {**record, "status": "BLOCKED", "reason": "the ledger directory is not creatable"}
    try:
        connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ROLLBACK")
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error:
        return {**record, "status": "BLOCKED", "reason": "the ledger path is not writable"}
    record.update({"status": "READY", "journal_mode": str(mode), "writable": True})
    try:
        from covenia_b.storage import SQLiteLedgerRepository

        SQLiteLedgerRepository(path)
        record["schema"] = "VALIDATED"
    except (PortError, ValueError, sqlite3.Error) as error:
        return {
            **record,
            "status": "BLOCKED",
            "reason": "the ledger cannot be initialized or validated",
            "error_type": type(error).__name__,
        }
    return record


def _probe_model_endpoint(endpoint: str, *, timeout: float = 2.0) -> tuple[bool, str]:
    parsed = urlsplit(endpoint)
    host = parsed.hostname
    if host is None:
        return False, "the endpoint has no host"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"tcp {host}:{port} reachable"
    except OSError as error:
        return False, f"tcp {host}:{port} unreachable ({type(error).__name__})"


def check_model(settings: Settings, *, offline: bool) -> dict[str, Any]:
    """Report the model deployment configuration and the warmup obligation."""

    missing = missing_model_settings(settings)
    record: dict[str, Any] = {
        "id": "model",
        "endpoint": settings.model_endpoint,
        "model_revision": settings.model_revision,
        "prompt_version": settings.model_prompt_version,
        "deployment_id_configured": bool(settings.model_deployment_id.strip()),
        "api_key_present": bool(os.environ.get("COVENIA_MODEL_API_KEY")),
        "offline": offline,
        "required": True,
        "warmup": {
            "required": True,
            "performed": False,
            "reason": "offline mode never contacts the model endpoint",
        },
    }
    if missing:
        return {
            **record,
            "status": "BLOCKED",
            "reason": (
                "the model deployment is not registered; analyze will answer "
                "MODEL_UNAVAILABLE and no candidate is substituted"
            ),
            "missing_settings": [f"COVENIA_{name.upper()}" for name in missing],
        }
    if offline:
        record["status"] = "READY"
        record["warmup"] = {
            "required": True,
            "performed": False,
            "reason": "offline mode never contacts the model endpoint",
        }
        return record
    reachable, detail = _probe_model_endpoint(settings.model_endpoint)
    record["warmup"] = {"required": True, "performed": reachable, "reason": detail}
    if not reachable:
        return {
            **record,
            "status": "BLOCKED",
            "reason": "the registered model endpoint is not reachable",
        }
    record["status"] = "READY"
    return record


def check_composition(settings: Settings) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the real application and return its preflight record plus inventory."""

    record: dict[str, Any] = {"id": "composition", "required": True}
    runtime = build_runtime(settings)
    app = compose_application(settings, runtime=runtime)
    inventory = route_inventory_document(app, settings=settings, runtime=runtime)
    record.update(
        {
            "status": "READY",
            "business_post_route_count": inventory["business_post_route_count"],
            "business_post_routes": [
                f"{entry['method']} {entry['path']}"
                for entry in inventory["business_post_routes"]
            ],
            "documentation_routes_disabled": (
                app.docs_url is None and app.redoc_url is None and app.openapi_url is None
            ),
            "allowed_origins": inventory["cors"]["allowed_origins"],
            "model_provider_configured": inventory["model_provider"]["configured"],
        }
    )
    if inventory["business_post_route_count"] != 4 or not record["documentation_routes_disabled"]:
        record["status"] = "BLOCKED"
        record["reason"] = "the application does not expose exactly the frozen four POST routes"
    return record, inventory


def _longest_path(root: Path) -> dict[str, Any]:
    longest = ("", 0)
    for entry in root.rglob("*"):
        rendered = str(entry)
        if len(rendered) > longest[1]:
            longest = (rendered, len(rendered))
    return {"length": longest[1], "path": longest[0], "limit": VENV_PATH_LIMIT}


def check_short_paths() -> dict[str, Any]:
    """Inherit the repaired short-path convention (real disk paths, not git escapes)."""

    repository = _repository_root()
    tool = repository / "tools" / "preflight" / "shortpath_check.py"
    run_dir = Path(sys.prefix).resolve().parent
    record: dict[str, Any] = {
        "id": "short_paths",
        "repository_root": str(repository),
        "run_dir": str(run_dir),
        "tool": str(tool),
        "measured": "real filesystem paths (os.walk + git -c core.quotepath=false)",
        "required": True,
        "venv": _longest_path(Path(sys.prefix)) if Path(sys.prefix).is_dir() else None,
    }
    if not tool.is_file():
        record["status"] = "BLOCKED"
        record["reason"] = "the repaired short-path preflight tool is missing"
        return record
    completed = subprocess.run(
        [sys.executable, str(tool), "--repo", str(repository), "--run-dir", str(run_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    record["tool_exit_code"] = completed.returncode
    record["tool_stdout"] = completed.stdout
    if completed.returncode != 0:
        record["status"] = "BLOCKED"
        record["reason"] = "a real path reaches the short-path limit"
        return record
    venv = record["venv"]
    if venv is not None and venv["length"] >= VENV_PATH_LIMIT:
        record["status"] = "BLOCKED"
        record["reason"] = "the venv contains a path at or above the limit"
        return record
    record["status"] = "READY"
    return record


def run_preflight(settings: Settings, *, offline: bool) -> dict[str, Any]:
    """Run every check and return the machine-readable preflight document."""

    checks = [
        check_workbook(settings.workbook_path),
        check_case_source(settings),
        check_image_manifest(settings),
        check_sqlite(settings),
        check_model(settings, offline=offline),
        check_short_paths(),
    ]
    composition, inventory = check_composition(settings)
    checks.append(composition)
    short_paths = next(check for check in checks if check["id"] == "short_paths")
    blockers = [
        f"{check['id']}: {_reason(check)}"
        for check in checks
        if check.get("status") == "BLOCKED"
    ]
    venv_prefix = Path(sys.prefix).resolve()
    document: dict[str, Any] = {
        "artifact": "reports/batches/BATCH-27/preflight.json",
        "batch_id": "BATCH-27",
        "generated_at": _now(),
        "offline": offline,
        "status": "BLOCKED" if blockers else "READY",
        "blockers": blockers,
        "checks": checks,
        "environment": {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "sys_prefix": str(venv_prefix),
            "isolated_venv": sys.prefix != sys.base_prefix,
            "temp_dir": tempfile.gettempdir(),
            "run_dir": str(venv_prefix.parent),
            "venv_longest_path": short_paths.get("venv"),
            "working_directory": str(Path.cwd()),
        },
        "route_inventory_artifact": "reports/batches/BATCH-27/route-inventory.json",
        "honesty_statement": (
            "Missing inputs are reported as blockers. The preflight never returns a "
            "synthetic candidate, a cached extraction, or a substitute case result."
        ),
    }
    document["route_inventory"] = inventory
    return document


def _reason(check: dict[str, Any]) -> str:
    reason = check.get("reason")
    if isinstance(reason, list):
        return "; ".join(str(item) for item in reason)
    if reason is None:
        return "blocked"
    return str(reason)


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Covenia startup preflight (local, read-only)")
    parser.add_argument("--offline", action="store_true", help="never contact the model endpoint")
    parser.add_argument("--workbook", default=None, help="competition workbook path override")
    parser.add_argument("--report-dir", default=None, help="artifact directory override")
    parser.add_argument(
        "--fail-on-blocker",
        action="store_true",
        help="exit 2 when a blocker is reported (default: exit 0 after writing the report)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.workbook is not None:
        settings = settings.model_copy(update={"workbook_path": Path(args.workbook)})

    document = run_preflight(settings, offline=args.offline)
    report_dir = Path(args.report_dir) if args.report_dir else DEFAULT_REPORT_DIR
    _write(report_dir / "preflight.json", document)
    _write(report_dir / "route-inventory.json", document["route_inventory"])

    print(f"preflight: {document['status']}")
    for check in document["checks"]:
        print(f"  {check['status']:<7} {check['id']}")
    for blocker in document["blockers"]:
        print(f"  BLOCKER {blocker}")
    environment = document["environment"]
    venv = environment["venv_longest_path"] or {}
    print(
        "  venv longest path: {length} (< {limit})".format(
            length=venv.get("length"), limit=VENV_PATH_LIMIT
        )
    )
    print(f"  interpreter: {environment['python_executable']}")
    print(f"  report: {report_dir / 'preflight.json'}")
    print(f"  routes: {report_dir / 'route-inventory.json'}")
    if document["status"] == "BLOCKED" and args.fail_on_blocker:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
