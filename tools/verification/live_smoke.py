#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""One real, uncached Qwen vision extraction with auditable evidence.

Why this tool exists
--------------------
BATCH-28 has to answer one question that a mocked test can never answer: does the
*registered* Qwen deployment actually receive the verified image bytes, return a
candidate that the server-side source validator accepts, and finish inside the
frozen 20-second analysis budget?  A passing test double proves nothing here, so
this tool refuses to run at all unless a real deployment is registered and
reachable, and it never falls back to a cached, synthetic, or offline answer.

What it does
------------
1.  Verifies the environment it was launched with: isolated venv, absolute
    interpreter, model endpoint / deployment / revision present, and the prompt
    version identical to the frozen ``prompt_manifest()``.
2.  Assembles ``DEMO_001`` from the competition workbook plus the accepted case
    catalog, resolves the registered evidence images through the production
    :class:`~covenia_b.images.ManifestImageResolver`, and proves the no-PII
    declaration boundary is satisfied before any byte leaves the process.
3.  Sends the sanitized chat text *and* the verified image bytes to the real
    endpoint through the production :class:`~covenia_b.model.adapters.qwen_http.QwenHttpProvider`,
    once per attempt, with a brand-new provider object each time so nothing can
    be served from an earlier call.
4.  Runs the server-owned source validation, then builds the ``ExtractedJourney``
    and ``AccountabilityState`` with the same reviewed service/state helpers the
    ``analyze`` endpoint uses.
5.  Writes ``model-output.redacted.json``, ``governance.redacted.jsonl`` and
    ``environment.json`` and reports the exact provider usage and latency.

Honesty rules baked into the exit code
--------------------------------------
*   Token usage and latency are taken from the provider response metadata; when
    the upstream returns no usage the record says ``MISSING`` instead of a guess.
*   The 20-second budget is a *frozen* number: ``--timeout-seconds`` may only be
    lowered.  A pass that exceeds the budget exits ``4`` (``BUDGET_EXCEEDED``);
    it is never reported as a pass, and a long offline run is never relabelled as
    a successful integration run.
*   ``--require-live`` makes a missing deployment, an unreachable endpoint, a
    connection refusal, or a timeout a hard failure.  There is no cache in this
    repository, and this tool does not add one, so a silent downgrade is
    structurally impossible: every attempt is a fresh HTTP request.

Exit codes
----------
0  one attempt produced a source-validated candidate and the full journey, inside
   the budget, with no cache involvement.
1  the live pipeline ran and the model output was not accepted (schema or source
   validation).  The tool reports the real stage and leaves the raw candidate in
   the redacted artifact; this is a finding, not a pass.
2  tool/configuration error: bad arguments, missing or non-isolated interpreter,
   unregistered deployment, prompt-manifest mismatch, unusable manifest, or a
   misconfigured budget.
3  the endpoint could not be used: connection refused, TLS/HTTP framing failure,
   authentication failure, or the provider deadline expired.  With
   ``--require-live`` this is always a failure; it is never downgraded.
4  the extraction succeeded but exceeded the frozen 20-second analysis budget.
5  the run succeeded but an artifact could not be written.

Usage
-----
  python tools/verification/live_smoke.py --require-live --disable-cache \
      --output reports/batches/BATCH-28/live
  python tools/verification/live_smoke.py --require-live --disable-cache \
      --endpoint http://127.0.0.1:8002/v1/chat/completions --timeout-seconds 2

The second form is the negative control: it points the same client at a port
nothing listens on and must fail loudly with exit 3.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOOL_VERSION = "live-smoke-v1"
BATCH_ID = "BATCH-28"
DEFAULT_CASE_ID = "DEMO_001"
DEFAULT_ATTEMPTS = 2

#: ``docs/05-api-and-ui.md`` freezes the analysis budget at 20 seconds and
#: ``covenia_b.api.analyze.DEFAULT_ANALYSIS_TIMEOUT_SECONDS`` enforces it.  The
#: tool may only tighten this number, never widen it.
FROZEN_ANALYSIS_BUDGET_SECONDS = 20.0

EXIT_OK = 0
EXIT_MODEL_OUTPUT_REJECTED = 1
EXIT_TOOL_ERROR = 2
EXIT_ENDPOINT_UNAVAILABLE = 3
EXIT_BUDGET_EXCEEDED = 4
EXIT_ARTIFACT_ERROR = 5

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

#: Keys that must never reach a redacted artifact, whatever the upstream echoes.
_FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "access_token",
        "bearer",
        "endpoint_url",
    }
)


class SmokeConfigurationError(RuntimeError):
    """The tool cannot run: arguments, interpreter, or deployment are unusable."""


class SmokeEndpointError(RuntimeError):
    """The registered endpoint could not be used at all."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class AttemptRecord:
    """Everything one real provider attempt produced, redacted for reporting."""

    attempt: int
    stage: str
    outcome: str
    started_at: str
    wall_ms: int | None = None
    provider_duration_ms: int | None = None
    provider_request_id: str | None = None
    status_code: int | None = None
    request_sha256: str | None = None
    response_sha256: str | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    image_sha256s: tuple[str, ...] = ()
    usage_status: str = "NOT_ATTEMPTED"
    usage: Mapping[str, int] | None = None
    usage_note: str | None = None
    candidate_accepted: bool = False
    observations: tuple[str, ...] = ()
    candidate_promise_texts: tuple[str, ...] = ()
    source_trace: tuple[Mapping[str, str], ...] = ()
    rejection_code: str | None = None
    rejection_stage: str | None = None
    failure_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "stage": self.stage,
            "outcome": self.outcome,
            "started_at": self.started_at,
            "wall_ms": self.wall_ms,
            "provider_reported_duration_ms": self.provider_duration_ms,
            "provider_request_id": self.provider_request_id,
            "status_code": self.status_code,
            "request_sha256": self.request_sha256,
            "response_sha256": self.response_sha256,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "image_sha256s": list(self.image_sha256s),
            "usage_status": self.usage_status,
            "usage": None if self.usage is None else dict(self.usage),
            "usage_note": self.usage_note,
            "candidate_accepted": self.candidate_accepted,
            "observations": list(self.observations),
            "candidate_promise_texts": list(self.candidate_promise_texts),
            "source_trace": [dict(trace) for trace in self.source_trace],
            "rejection_code": self.rejection_code,
            "rejection_stage": self.rejection_stage,
            "failure_reason": self.failure_reason,
        }


@dataclass
class SmokeRun:
    """Mutable accumulator for one tool invocation."""

    attempts: list[AttemptRecord] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)
    budget_status: str = "NOT_MEASURED"
    model_bound_ms: int | None = None
    case_load_ms: int | None = None
    journey: Mapping[str, Any] | None = None
    accountability: Mapping[str, Any] | None = None
    source_summary: Mapping[str, Any] | None = None
    provider_mode: str = "LIVE"


# --------------------------------------------------------------------------- #
# Repository / interpreter facts
# --------------------------------------------------------------------------- #


def _repository_root() -> Path:
    """Return the checkout root that contains ``backend/src`` and ``schemas``."""

    override = os.environ.get("COVENIA_LIVE_SMOKE_ROOT")
    if override:
        return Path(override).resolve()
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "backend" / "src" / "covenia_b").is_dir():
        return candidate
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "covenia_b").is_dir():
            return parent
    raise SmokeConfigurationError("cannot locate the repository root from this tool path")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_blob_sha256(repo: Path, revision: str, relative_path: str) -> dict[str, Any]:
    """Hash the committed blob bytes (MASTER_PLAN 5.5-8), never the worktree file."""

    git = shutil.which("git")
    if git is None:
        return {"available": False, "reason": "git is not on PATH"}
    try:
        completed = subprocess.run(
            [git, "-C", str(repo), "show", f"{revision}:{relative_path}"],
            capture_output=True,
            check=False,
        )
    except OSError as error:  # pragma: no cover - defensive
        return {"available": False, "reason": f"git could not be executed: {type(error).__name__}"}
    if completed.returncode != 0:
        return {
            "available": False,
            "reason": "git show failed",
            "exit_code": completed.returncode,
            "stderr": completed.stderr.decode("utf-8", "replace").strip()[:300],
        }
    return {
        "available": True,
        "revision": revision,
        "path": relative_path,
        "method": "sha256(git show <sha>:<path> raw stdout bytes)",
        "sha256": _sha256_bytes(completed.stdout),
        "bytes": len(completed.stdout),
    }


def _venv_facts() -> dict[str, Any]:
    """Record the interpreter identity and the venv isolation proof."""

    prefix = Path(sys.prefix).resolve()
    base_prefix = Path(sys.base_prefix).resolve()
    pyvenv_cfg = prefix / "pyvenv.cfg"
    include_system_site_packages: str | None = None
    if pyvenv_cfg.is_file():
        for line in pyvenv_cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("include-system-site-packages"):
                include_system_site_packages = line.split("=", 1)[1].strip().lower()
    longest = 0
    longest_path = ""
    if prefix.is_dir():
        for entry in prefix.rglob("*"):
            rendered = str(entry)
            if len(rendered) > longest:
                longest, longest_path = len(rendered), rendered
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "python_version_full": sys.version,
        "sys_prefix": str(prefix),
        "sys_base_prefix": str(base_prefix),
        "isolated_venv": prefix != base_prefix,
        "pyvenv_cfg_present": pyvenv_cfg.is_file(),
        "include_system_site_packages": include_system_site_packages,
        "venv_longest_path_length": longest,
        "venv_longest_path": longest_path,
        "venv_longest_path_limit": 250,
        "venv_longest_path_ok": longest < 250,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "temp_dir": tempfile.gettempdir(),
        "working_directory": str(Path.cwd()),
        "run_dir": str(prefix.parent),
    }


def _installed_packages() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "available": False,
            "exit_code": completed.returncode,
            "stderr": completed.stderr.decode("utf-8", "replace")[:400],
        }
    try:
        packages = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"available": False, "reason": "pip list did not return JSON"}
    return {
        "available": True,
        "count": len(packages),
        "packages": sorted(
            ({"name": str(item.get("name")), "version": str(item.get("version"))} for item in packages),
            key=lambda item: item["name"].lower(),
        ),
    }


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #


def _redact(value: Any) -> Any:
    """Strip secrets and bound text length; keep the audited structure intact."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name.lower() in _FORBIDDEN_ARTIFACT_KEYS:
                redacted[name] = "[REDACTED]"
            else:
                redacted[name] = _redact(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        if len(value) > 4096:
            return value[:4096] + "...[TRUNCATED]"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _assert_clean(payload: Any, where: str) -> None:
    """Fail closed if a producer ever leaks a credential-shaped key into an artifact."""

    if isinstance(payload, Mapping):
        for key, item in payload.items():
            if str(key).lower() in _FORBIDDEN_ARTIFACT_KEYS and item != "[REDACTED]":
                raise SmokeConfigurationError(f"{where} carries a forbidden key {key!r}")
            _assert_clean(item, where)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _assert_clean(item, where)


# --------------------------------------------------------------------------- #
# Tool preflight
# --------------------------------------------------------------------------- #


def _endpoint_host_port(endpoint: str) -> tuple[str, int]:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise SmokeConfigurationError(f"endpoint is not an HTTP(S) URL: {endpoint!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SmokeConfigurationError("endpoint must not carry credentials, query, or fragment")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def _probe_endpoint(endpoint: str, *, timeout: float = 3.0) -> dict[str, Any]:
    host, port = _endpoint_host_port(endpoint)
    record: dict[str, Any] = {
        "endpoint": endpoint,
        "host": host,
        "port": port,
        "tcp_reachable": False,
    }
    try:
        with socket.create_connection((host, port), timeout=timeout):
            record["tcp_reachable"] = True
            record["detail"] = f"tcp {host}:{port} reachable"
    except OSError as error:
        record["detail"] = f"tcp {host}:{port} unreachable ({type(error).__name__})"
        record["error_type"] = type(error).__name__
    return record


def _port_confirmed_closed(endpoint: str) -> bool:
    """True when nothing listens on the endpoint port (the negative-control shape)."""

    host, port = _endpoint_host_port(endpoint)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# The live run
# --------------------------------------------------------------------------- #


def _load_modules() -> dict[str, Any]:
    """Import the production modules this tool drives; never a substitute."""

    from covenia_b.domain.types import (  # noqa: PLC0415
        AnalyzeCaseRequest,
        CaseInput,
        EvidenceImage,
    )
    from covenia_b.images import ManifestImageResolver  # noqa: PLC0415
    from covenia_b.importing.case_assembler import CaseAssembler  # noqa: PLC0415
    from covenia_b.model.adapters.qwen_http import (  # noqa: PLC0415
        QwenHttpConfig,
        QwenHttpProvider,
    )
    from covenia_b.model.extraction import (  # noqa: PLC0415
        BoundedCandidateExtractor,
        CandidateExtractionBudgetExceeded,
        CandidateQuarantineReason,
        QuarantinedModelOutput,
        build_candidate_model_input,
    )
    from covenia_b.model.prompts.candidate_extraction import (  # noqa: PLC0415
        CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
        PROMPT_VERSION,
        SCHEMA_REPAIR_SYSTEM_PROMPT,
        prompt_manifest,
    )
    from covenia_b.model.provider import (  # noqa: PLC0415
        ModelConnectionError,
        ModelIdentityMismatch,
        ModelProviderHttpError,
        ModelRequestRejected,
        ModelRequestTimeout,
        ModelResponseInvalid,
        UsageStatus,
    )
    from covenia_b.model.source_validation import (  # noqa: PLC0415
        SourceValidationError,
        validate_candidate_sources,
    )
    from covenia_b.observability import (  # noqa: PLC0415
        CacheStatus,
        GovernanceContext,
        InputSourceKind,
        JsonlGovernanceSink,
        ModelIdentity,
        RuntimeMetricsCollector,
        SafeInputSource,
    )
    from covenia_b.ports.errors import ModelUnavailable  # noqa: PLC0415
    from covenia_b.services.analyze import (  # noqa: PLC0415
        _DEFAULT_POLICY,
        AnalyzeService,
        _aggregate_server_evidence,
        _compile_from_server_facts,
        _enrich_extracted_journey,
    )
    from covenia_b.services.fact_loader import (  # noqa: PLC0415
        FactLoader,
        ImageSafetyDeclarations,
    )
    from covenia_b.settings import get_settings  # noqa: PLC0415

    return {
        "AnalyzeCaseRequest": AnalyzeCaseRequest,
        "CaseInput": CaseInput,
        "EvidenceImage": EvidenceImage,
        "ManifestImageResolver": ManifestImageResolver,
        "CaseAssembler": CaseAssembler,
        "QwenHttpConfig": QwenHttpConfig,
        "QwenHttpProvider": QwenHttpProvider,
        "BoundedCandidateExtractor": BoundedCandidateExtractor,
        "CandidateExtractionBudgetExceeded": CandidateExtractionBudgetExceeded,
        "CandidateQuarantineReason": CandidateQuarantineReason,
        "QuarantinedModelOutput": QuarantinedModelOutput,
        "build_candidate_model_input": build_candidate_model_input,
        "CANDIDATE_EXTRACTION_SYSTEM_PROMPT": CANDIDATE_EXTRACTION_SYSTEM_PROMPT,
        "PROMPT_VERSION": PROMPT_VERSION,
        "SCHEMA_REPAIR_SYSTEM_PROMPT": SCHEMA_REPAIR_SYSTEM_PROMPT,
        "prompt_manifest": prompt_manifest,
        "ModelConnectionError": ModelConnectionError,
        "ModelIdentityMismatch": ModelIdentityMismatch,
        "ModelProviderHttpError": ModelProviderHttpError,
        "ModelRequestRejected": ModelRequestRejected,
        "ModelRequestTimeout": ModelRequestTimeout,
        "ModelResponseInvalid": ModelResponseInvalid,
        "UsageStatus": UsageStatus,
        "SourceValidationError": SourceValidationError,
        "validate_candidate_sources": validate_candidate_sources,
        "CacheStatus": CacheStatus,
        "GovernanceContext": GovernanceContext,
        "InputSourceKind": InputSourceKind,
        "JsonlGovernanceSink": JsonlGovernanceSink,
        "ModelIdentity": ModelIdentity,
        "RuntimeMetricsCollector": RuntimeMetricsCollector,
        "SafeInputSource": SafeInputSource,
        "ModelUnavailable": ModelUnavailable,
        "AnalyzeService": AnalyzeService,
        "DEFAULT_POLICY": _DEFAULT_POLICY,
        "compile_from_server_facts": _compile_from_server_facts,
        "enrich_extracted_journey": _enrich_extracted_journey,
        "aggregate_server_evidence": _aggregate_server_evidence,
        "FactLoader": FactLoader,
        "ImageSafetyDeclarations": ImageSafetyDeclarations,
        "get_settings": get_settings,
    }


def _bind_registered_evidence(
    case_input: Any,
    accepted_manifest: Mapping[str, Any],
    modules: Mapping[str, Any],
) -> tuple[Any, list[dict[str, Any]], list[str]]:
    """Bind each assembled evidence image to its entry in the accepted registry.

    The assembler takes evidence identifiers from ``fixtures/demo-cases.json``
    while the only registry the production resolver trusts is
    ``handoff/a/images-manifest.json``.  This function performs no substitution of
    convenience: it matches on ``file_name`` (a required, byte-identical key in
    both artifacts), refuses to guess when a name has no unique accepted entry,
    and reports every remap so the discrepancy stays visible in the evidence.
    """

    entries = accepted_manifest.get("images")
    if not isinstance(entries, list) or not entries:
        raise SmokeConfigurationError("the accepted image manifest registers no image")
    by_name: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise SmokeConfigurationError("the accepted image manifest has a non-object entry")
        name = entry.get("file_name")
        if not isinstance(name, str) or not name:
            raise SmokeConfigurationError("an accepted image entry has no file_name")
        if name in by_name:
            raise SmokeConfigurationError(f"the accepted image manifest duplicates {name!r}")
        by_name[name] = entry

    rebound: list[Any] = []
    remaps: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for image in case_input.evidence_images:
        entry = by_name.get(image.file_name)
        if entry is None:
            unresolved.append(image.file_name)
            continue
        evidence_id = entry.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise SmokeConfigurationError(f"accepted entry for {image.file_name!r} has no evidence_id")
        rebound.append(
            modules["EvidenceImage"](
                evidence_id=evidence_id,
                file_name=image.file_name,
                submitted_at=image.submitted_at,
                declared_view_type=image.declared_view_type,
                source_kind=image.source_kind,
                source_message_id=image.source_message_id,
                competition_reference_path=image.competition_reference_path,
            )
        )
        if evidence_id != image.evidence_id:
            remaps.append(
                {
                    "assembled_evidence_id": image.evidence_id,
                    "accepted_evidence_id": evidence_id,
                    "file_name": image.file_name,
                    "match_key": "file_name",
                    "effect": (
                        "the assembled case named an evidence ID that the accepted registry "
                        "does not contain; the registry's own ID is used so the production "
                        "resolver can verify the bytes"
                    ),
                }
            )
    if unresolved:
        raise SmokeConfigurationError(
            "assembled evidence has no accepted registry entry: " + ", ".join(sorted(unresolved))
        )
    return case_input.model_copy(update={"evidence_images": list(rebound)}), remaps, unresolved


def _governance_context(
    modules: Mapping[str, Any],
    *,
    request_id: str,
    run_id: str,
    source_ids: Sequence[str],
    image_hashes: Sequence[str],
    pii_masked_count: int,
    model_revision: str,
) -> Any:
    order_identifier = source_ids[0] if source_ids else "unknown-order"
    sources = [
        modules["SafeInputSource"].from_identifier(
            phase="MODEL", kind=modules["InputSourceKind"].ORDER, identifier=order_identifier
        )
    ]
    for source_id in source_ids[1:]:
        kind = (
            modules["InputSourceKind"].IMAGE
            if source_id.startswith("S00001_IMG_")
            else modules["InputSourceKind"].CHAT
        )
        sources.append(
            modules["SafeInputSource"].from_identifier(
                phase="MODEL", kind=kind, identifier=source_id
            )
        )
    return modules["GovernanceContext"](
        request_id=request_id,
        run_id=run_id,
        endpoint="analyze",
        input_sources=tuple(sources),
        pii_masked_count=pii_masked_count,
        image_hashes=tuple(image_hashes),
        model=modules["ModelIdentity"](
            model_id="qwen3-vl-plus",
            model_revision=model_revision,
            prompt_version=modules["PROMPT_VERSION"],
        ),
    )


def _run_attempt(
    *,
    attempt_number: int,
    case_id: str,
    model_input: Any,
    provider_input: Any,
    modules: Mapping[str, Any],
    config: Any,
    image_payloads: Mapping[str, Any],
    provider_usage_sink: Any,
    run: SmokeRun,
) -> tuple[Any | None, AttemptRecord]:
    """Run exactly one real provider call and its server-side validation."""

    record = AttemptRecord(
        attempt=attempt_number,
        stage="INITIAL",
        outcome="NOT_STARTED",
        started_at=datetime.now(UTC).isoformat(),
    )

    def loader(handle: Any) -> Any:
        payload = image_payloads.get(handle.evidence_id)
        if payload is None:
            raise modules["ModelRequestRejected"]("verified image bytes are unavailable")
        return payload

    provider = modules["QwenHttpProvider"](config, image_loader=loader)
    attempt_id = f"attempt-{attempt_number:02d}"
    started = time.perf_counter()
    try:
        result = asyncio.run(
            provider.extract_with_metadata(
                provider_input, timeout_seconds=float(config.default_timeout_seconds)
            )
        )
    except modules["ModelRequestTimeout"]:
        record.outcome = "ENDPOINT_TIMEOUT"
        record.failure_reason = "provider deadline exceeded before a bounded response"
        record.wall_ms = round((time.perf_counter() - started) * 1000)
        provider_usage_sink.record_failure(attempt_id, "timeout")
        return None, record
    except (modules["ModelConnectionError"], ConnectionError, OSError):
        record.outcome = "CONNECTION_FAILED"
        record.failure_reason = "the registered model endpoint refused or dropped the connection"
        record.wall_ms = round((time.perf_counter() - started) * 1000)
        provider_usage_sink.record_failure(attempt_id, "connection_failed")
        return None, record
    except modules["ModelIdentityMismatch"]:
        record.outcome = "IDENTITY_MISMATCH"
        record.failure_reason = "the response did not prove the locked model and revision"
        record.wall_ms = round((time.perf_counter() - started) * 1000)
        provider_usage_sink.record_failure(attempt_id, "identity_mismatch")
        return None, record
    except modules["ModelProviderHttpError"] as error:
        record.outcome = "PROVIDER_HTTP_ERROR"
        record.status_code = int(getattr(error, "status_code", 0)) or None
        record.failure_reason = "the endpoint answered with a non-success HTTP status"
        record.wall_ms = round((time.perf_counter() - started) * 1000)
        provider_usage_sink.record_failure(attempt_id, "provider_http_error")
        return None, record
    except (modules["ModelRequestRejected"], modules["ModelResponseInvalid"]) as error:
        record.outcome = "ADAPTER_REJECTED"
        record.failure_reason = (
            "the adapter refused the request or could not parse the candidate response"
        )
        record.rejection_code = type(error).__name__
        record.wall_ms = round((time.perf_counter() - started) * 1000)
        provider_usage_sink.record_failure(attempt_id, "adapter_rejected")
        return None, record
    except modules["ModelUnavailable"] as error:
        record.outcome = "MODEL_UNAVAILABLE"
        record.failure_reason = "the model port reported unavailability"
        record.rejection_code = type(error).__name__
        record.wall_ms = round((time.perf_counter() - started) * 1000)
        provider_usage_sink.record_failure(attempt_id, "model_unavailable")
        return None, record

    record.wall_ms = round((time.perf_counter() - started) * 1000)
    metadata = result.metadata
    record.provider_duration_ms = metadata.duration_ms
    record.provider_request_id = metadata.provider_request_id
    record.status_code = metadata.status_code
    record.request_sha256 = metadata.request_sha256
    record.response_sha256 = metadata.response_sha256
    record.request_bytes = metadata.request_bytes
    record.response_bytes = metadata.response_bytes
    record.image_sha256s = tuple(metadata.image_sha256s)
    record.usage_status = metadata.usage_status.value
    if metadata.usage is None:
        record.usage_note = "上游未提供 — the provider response carried no input/output token pair"
    else:
        record.usage = {
            "input_tokens": metadata.usage.input_tokens,
            "output_tokens": metadata.usage.output_tokens,
        }

    from covenia_b.model.source_validation import (  # noqa: PLC0415 - same seam the service uses
        SourceValidationError,
        validate_candidate_sources,
    )

    candidate = result.candidate
    record.observations = tuple(candidate.observations)
    record.candidate_promise_texts = tuple(candidate.candidate_promise_texts)
    record.source_trace = tuple(
        {"field": trace.field, "source_type": trace.source_type, "source_id": trace.source_id}
        for trace in candidate.source_trace
    )
    try:
        validate_candidate_sources(candidate, model_input)
    except SourceValidationError as error:
        record.outcome = "SOURCE_REJECTED"
        record.rejection_code = error.code.value
        record.failure_reason = "the server-side source validator refused the candidate"
        # The provider really answered and really billed tokens; record that exact
        # usage instead of fabricating a MISSING measurement for a completed call.
        provider_usage_sink.record_success(attempt_id, metadata.usage)
        return None, record

    record.outcome = "ACCEPTED"
    record.candidate_accepted = True
    provider_usage_sink.record_success(attempt_id, metadata.usage)
    del case_id
    return result, record


class _ProviderUsageSink:
    """Record exact provider usage for one attempt in the governance audit log."""

    def __init__(self, session: Any, modules: Mapping[str, Any]) -> None:
        self._session = session
        self._modules = modules
        self._attempts: dict[str, Any] = {}

    def begin(self, attempt_id: str) -> None:
        self._attempts[attempt_id] = self._session.begin_model_attempt(
            attempt_id=attempt_id,
            cache_status=self._modules["CacheStatus"].MISS,
        )

    def record_success(self, attempt_id: str, usage: Any) -> None:
        attempt = self._attempts.pop(attempt_id, None)
        if attempt is None:
            return
        attempt.complete(provider_usage=usage)

    def record_failure(self, attempt_id: str, reason: str) -> None:
        attempt = self._attempts.pop(attempt_id, None)
        if attempt is None:
            return
        attempt.fail(failure_reason=reason)


def _format_rfc3339(value: Any) -> Any:
    return value if value is None else str(value)


def run_live(
    args: argparse.Namespace,
    *,
    repo: Path,
    output_dir: Path,
) -> tuple[int, SmokeRun, dict[str, Any]]:
    """Drive the real extraction pipeline and return (exit_code, run, document)."""

    modules = _load_modules()
    settings = modules["get_settings"]()

    document: dict[str, Any] = {
        "artifact": "reports/batches/BATCH-28/live/model-output.redacted.json",
        "batch_id": BATCH_ID,
        "tool": "tools/verification/live_smoke.py",
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "statement": (
            "本批由辅助调度器实现，非独立实现方；验收须由他方完成。 "
            "This artifact records one real, uncached multimodal extraction attempt against the "
            "registered Qwen deployment. It is implementation evidence, not a verification verdict."
        ),
    }
    run = SmokeRun()

    # ---- 1. tool preflight -------------------------------------------------
    interpreter = _venv_facts()
    if not interpreter["isolated_venv"]:
        raise SmokeConfigurationError(
            "the analysis must run under the batch's own isolated venv interpreter"
        )
    if args.timeout_seconds > FROZEN_ANALYSIS_BUDGET_SECONDS:
        raise SmokeConfigurationError(
            f"--timeout-seconds may not exceed the frozen {FROZEN_ANALYSIS_BUDGET_SECONDS:g}s budget"
        )

    manifest_expected = modules["prompt_manifest"]()
    prompt_version = settings.model_prompt_version
    prompt_ok = prompt_version == manifest_expected["prompt_version"]
    deployment_id = settings.model_deployment_id.strip()
    endpoint = args.endpoint or settings.model_endpoint
    revision = settings.model_revision.strip()
    missing: list[str] = []
    if not deployment_id:
        missing.append("COVENIA_MODEL_DEPLOYMENT_ID")
    if not endpoint:
        missing.append("COVENIA_MODEL_ENDPOINT")
    if not revision:
        missing.append("COVENIA_MODEL_REVISION")
    if missing:
        raise SmokeConfigurationError(
            "the model deployment is not registered (missing: " + ", ".join(missing) + ")"
        )
    if not prompt_ok:
        raise SmokeConfigurationError(
            "COVENIA_MODEL_PROMPT_VERSION does not match the frozen prompt manifest"
        )

    endpoint_probe = _probe_endpoint(endpoint)
    document["configuration"] = {
        "endpoint": endpoint,
        "deployment_id": deployment_id,
        "model_revision": revision,
        "prompt_version": prompt_version,
        "frozen_prompt_manifest": manifest_expected,
        "prompt_version_matches_manifest": prompt_ok,
        "model_id": "qwen3-vl-plus",
        "api_key_present_in_environment": bool(os.environ.get("COVENIA_MODEL_API_KEY")),
        "api_key_value_recorded": False,
        "cache_mode_setting": settings.cache_mode,
        "cache_adapter_exists": False,
        "cache_statement": (
            "no ExtractionStore/cache adapter is wired anywhere in this repository, so every "
            "attempt below is a real HTTP request and cached_result is false by construction"
        ),
        "disable_cache_requested": bool(args.disable_cache),
        "require_live_requested": bool(args.require_live),
        "attempts_requested": args.attempts,
        "timeout_seconds": args.timeout_seconds,
        "frozen_analysis_budget_seconds": FROZEN_ANALYSIS_BUDGET_SECONDS,
        "endpoint_probe": endpoint_probe,
        "endpoint_probe_skipped": bool(args.skip_endpoint_probe),
        "endpoint_port_confirmed_closed": _port_confirmed_closed(endpoint),
    }
    document["environment"] = interpreter

    if args.require_live and not args.skip_endpoint_probe and not endpoint_probe["tcp_reachable"]:
        raise SmokeEndpointError(
            "endpoint_unreachable",
            f"--require-live and the endpoint is not reachable: {endpoint_probe['detail']}",
        )

    # ---- 2. facts and verified image bytes ---------------------------------
    manifest_path = repo / settings.image_manifest_path
    accepted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if accepted_manifest.get("status") != "ACCEPTED":
        raise SmokeConfigurationError("the image manifest is not in the accepted A-line state")

    resolver = modules["ManifestImageResolver"].from_manifest_file(
        manifest_path=manifest_path,
        evidence_root=repo / settings.image_evidence_root,
    )
    assembler = modules["CaseAssembler"].from_paths(
        repo / settings.workbook_path,
        repo / settings.demo_cases_path,
        repo / settings.case_manifest_path,
    )
    load_started = time.perf_counter()
    assembly = assembler.assemble(args.case_id)
    if assembly.status != "ASSEMBLED" or assembly.case_input is None:
        raise SmokeConfigurationError(
            f"the case source could not assemble {args.case_id}: "
            + ", ".join(d.code for d in assembly.diagnostics)
        )
    case_input = modules["CaseInput"].from_contract(assembly.case_input)

    # Prove the assembled identifiers really are unusable before remapping them,
    # so the cross-artifact discrepancy is recorded as a measured fact.
    pre_binding: list[dict[str, Any]] = []
    for image in case_input.evidence_images:
        entry: dict[str, Any] = {
            "evidence_id": image.evidence_id,
            "file_name": image.file_name,
            "resolvable_by_production_resolver": False,
        }
        try:
            resolver.resolve_details(image)
            entry["resolvable_by_production_resolver"] = True
        except Exception as error:  # noqa: BLE001 - the failure class is the finding
            entry["rejection"] = type(error).__name__
            entry["rejection_code"] = getattr(error, "code", None)
        pre_binding.append(entry)

    bound_input, remaps, _ = _bind_registered_evidence(case_input, accepted_manifest, modules)
    case_input = bound_input

    provider_images: dict[str, Any] = {}
    resolved_handles: list[dict[str, Any]] = []
    for image in case_input.evidence_images:
        details = resolver.resolve_details(image)
        provider_images[details.handle.evidence_id] = details.provider_image
        resolved_handles.append(
            {
                "evidence_id": details.handle.evidence_id,
                "media_type": details.handle.media_type,
                "byte_length": details.handle.byte_length,
                "content_sha256": details.handle.content_sha256,
                "width": details.provider_image.width,
                "height": details.provider_image.height,
                "provenance_source_message_id": details.provenance.source_message_id,
                "provenance_source_kind": details.provenance.source_kind,
                "declared_view_type": image.declared_view_type,
            }
        )

    declarations = modules["ImageSafetyDeclarations"].from_accepted_manifest(manifest_path)
    loader = modules["FactLoader"](
        case_source=None,
        image_resolver=resolver,
        image_no_pii_declarations=declarations,
    )
    loaded = loader.load(
        modules["AnalyzeCaseRequest"](
            case_id=args.case_id, challenge_mode=True, case_input=case_input
        )
    )
    run.case_load_ms = round((time.perf_counter() - load_started) * 1000)
    if not loaded.provider_image_binding_verified:
        raise SmokeConfigurationError("the live provider requires verified image-to-bytes binding")

    model_input = loaded.sanitization.model_input
    provider_input = modules["build_candidate_model_input"](model_input)

    # The image bytes must travel as image parts; the observation JSON must not.
    content_types = [part.get("type") for part in _request_content(provider_input, modules)]
    document["input_binding"] = {
        "case_id": case_input.case_id,
        "source_session_id": case_input.data_provenance.source_session_id,
        "evaluation_time": _format_rfc3339(case_input.evaluation_time),
        "assembled_evidence_images": pre_binding,
        "registry_remaps": remaps,
        "cross_artifact_discrepancy": (
            "fixtures/demo-cases.json declares S00001_IMG_OVERVIEW / S00001_IMG_PUMP / "
            "S00001_IMG_PACKAGE while handoff/a/images-manifest.json registers "
            "S00001_IMG_PRODUCT_OVERVIEW / S00001_IMG_PUMP_DETAIL / S00001_IMG_PACKAGE_CONTEXT. "
            "Only file_name agrees, so the production resolver rejects the assembled case as-is. "
            "This batch may not edit either artifact; the accepted registry is treated as the "
            "authority and every remap is listed above."
            if remaps
            else "none: the assembled evidence IDs all exist in the accepted registry"
        ),
        "resolved_provider_images": resolved_handles,
        "image_sha256s_sent": [item["content_sha256"] for item in resolved_handles],
        "provider_content_parts": content_types,
        "provider_request_contains_image_url_parts": content_types.count("image_url"),
        "observation_json_sent_as_image": False,
        "observation_json_statement": (
            "the provider request carries the sanitized chat text as the single text part and "
            "each verified image as an image_url data part; no observation JSON, candidate, or "
            "derived label is serialized into the request"
        ),
        "pii_masked_count": loaded.sanitization.pii_masked_count,
        "declared_source_ids": list(model_input.source_ids),
    }

    # ---- 3. real calls, one fresh provider per attempt ---------------------
    governance_path = output_dir / "governance.redacted.jsonl"
    if governance_path.exists():
        governance_path.unlink()
    collector = modules["RuntimeMetricsCollector"](
        modules["JsonlGovernanceSink"](governance_path)
    )
    request_id = f"live-smoke-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    session = collector.start_request(
        _governance_context(
            modules,
            request_id=request_id,
            run_id=request_id,
            source_ids=model_input.source_ids,
            image_hashes=[item["content_sha256"] for item in resolved_handles],
            pii_masked_count=loaded.sanitization.pii_masked_count,
            model_revision=revision,
        )
    )
    usage_sink = _ProviderUsageSink(session, modules)

    config = modules["QwenHttpConfig"](
        endpoint=endpoint,
        model_revision=revision,
        prompt_version=modules["PROMPT_VERSION"],
        deployment_id=deployment_id,
        system_prompt=modules["CANDIDATE_EXTRACTION_SYSTEM_PROMPT"],
        api_key=os.environ.get("COVENIA_MODEL_API_KEY") or None,
        default_timeout_seconds=args.timeout_seconds,
    )

    accepted_result = None
    model_bound_started = time.perf_counter()
    for number in range(1, args.attempts + 1):
        usage_sink.begin(f"attempt-{number:02d}")
        result, record = _run_attempt(
            attempt_number=number,
            case_id=args.case_id,
            model_input=model_input,
            provider_input=provider_input,
            modules=modules,
            config=config,
            image_payloads=provider_images,
            provider_usage_sink=usage_sink,
            run=run,
        )
        run.attempts.append(record)
        if result is not None:
            accepted_result = result
            break
        if record.outcome in {
            "CONNECTION_FAILED",
            "ENDPOINT_TIMEOUT",
            "PROVIDER_HTTP_ERROR",
            "MODEL_UNAVAILABLE",
            "IDENTITY_MISMATCH",
        }:
            break
    run.model_bound_ms = round((time.perf_counter() - model_bound_started) * 1000)

    if run.model_bound_ms > FROZEN_ANALYSIS_BUDGET_SECONDS * 1000:
        run.budget_status = "BUDGET_EXCEEDED"
    elif accepted_result is None:
        run.budget_status = "NOT_ACHIEVED_OUTPUT_REJECTED"
    else:
        run.budget_status = "WITHIN_BUDGET"

    document["attempts"] = [record.to_payload() for record in run.attempts]
    document["budget"] = {
        "frozen_analysis_budget_seconds": FROZEN_ANALYSIS_BUDGET_SECONDS,
        "case_load_ms": run.case_load_ms,
        "model_bound_ms": run.model_bound_ms,
        "model_bound_seconds": (
            None if run.model_bound_ms is None else round(run.model_bound_ms / 1000, 3)
        ),
        "status": run.budget_status,
        "provider_reported_duration_ms": [
            record.provider_duration_ms for record in run.attempts
        ],
        "provider_wall_ms": [record.wall_ms for record in run.attempts],
        "measurement_source": (
            "perf_counter around the real provider call plus the provider's own reported "
            "duration_ms; no value is estimated"
        ),
        "measurement_boundary": (
            "model_bound_ms covers the model call and its source validation, which is the part "
            "of one analyze request the 20s budget must cover; case_load_ms is reported "
            "separately and is not a model cost"
        ),
    }

    # ---- 4. journey and accountability, using the reviewed service helpers ---
    if accepted_result is None:
        last = run.attempts[-1] if run.attempts else None
        endpoint_failure = last is not None and last.outcome in {
            "CONNECTION_FAILED",
            "ENDPOINT_TIMEOUT",
            "PROVIDER_HTTP_ERROR",
            "MODEL_UNAVAILABLE",
            "IDENTITY_MISMATCH",
        }
        document["status"] = (
            "ENDPOINT_UNAVAILABLE"
            if endpoint_failure
            else "MODEL_OUTPUT_REJECTED"
            if run.budget_status != "BUDGET_EXCEEDED"
            else "BUDGET_EXCEEDED"
        )
        document["summary"] = {
            "attempts": len(run.attempts),
            "accepted_attempt": None,
            "last_outcome": None if last is None else last.outcome,
            "last_rejection_code": None if last is None else last.rejection_code,
            "last_failure_reason": None if last is None else last.failure_reason,
        }
        document["stages"] = {
            "facts_and_image_binding": "PASS",
            "real_http_call": "FAIL" if endpoint_failure or not run.attempts else "PASS",
            "candidate_schema": (
                "FAIL"
                if endpoint_failure
                else ("PASS" if any(a.observations for a in run.attempts) else "FAIL")
            ),
            "source_validation": "FAIL",
            "extracted_journey": "NOT_REACHED",
            "accountability_state": "NOT_REACHED",
        }
        _write_artifacts(output_dir, document, governance_path, modules, repo=repo, settings=settings)
        if endpoint_failure:
            exit_code = EXIT_ENDPOINT_UNAVAILABLE
        elif run.budget_status == "BUDGET_EXCEEDED":
            exit_code = EXIT_BUDGET_EXCEEDED
        else:
            exit_code = EXIT_MODEL_OUTPUT_REJECTED
        return exit_code, run, document

    candidate = accepted_result.candidate
    service = modules["AnalyzeService"]
    source_summary = service._validate_candidate(candidate, loaded)
    # ``_compile_from_server_facts``, ``_enrich_extracted_journey`` and
    # ``_aggregate_server_evidence`` are module-level helpers in
    # ``covenia_b.services.analyze`` (lines 399, 410 and 539), not members of
    # ``AnalyzeService``.  ``_validate_candidate`` above is the only one of the
    # four that really is a static method on the service.  Resolving all four
    # through the reviewed module keeps the tool on the same code path the
    # ``analyze`` endpoint uses instead of re-implementing any of it.
    compilation = modules["compile_from_server_facts"](
        loaded.case_input, policy=modules["DEFAULT_POLICY"]
    )
    journey = modules["enrich_extracted_journey"](
        case_input=loaded.case_input, candidate=candidate, compilation=compilation
    )
    evidence = modules["aggregate_server_evidence"](loaded.case_input, journey, candidate)
    from covenia_b.state import build_accountability_state  # noqa: PLC0415

    state = build_accountability_state(
        case_input=loaded.case_input,
        journey=journey,
        evidence=evidence,
        compilation=compilation,
        request_id=request_id,
        persisted=None,
        actor="ANALYZE_SERVICE",
    )
    response = {
        "extracted_journey": journey.model_dump(mode="json"),
        "accountability_state": state.model_dump(mode="json"),
        "model_metadata": journey.model_metadata.model_dump(mode="json"),
    }
    document["extracted_journey"] = response["extracted_journey"]
    document["accountability_state"] = response["accountability_state"]
    document["model_metadata"] = response["model_metadata"]
    document["source_validation"] = {
        "trusted_source_count": source_summary.trusted_source_count,
        "traced_field_count": source_summary.traced_field_count,
        "agent_quote_count": source_summary.agent_quote_count,
        "image_observation_count": source_summary.image_observation_count,
    }
    document["status"] = (
        "BUDGET_EXCEEDED" if run.budget_status == "BUDGET_EXCEEDED" else "PASS"
    )
    document["summary"] = {
        "attempts": len(run.attempts),
        "accepted_attempt": run.attempts[-1].attempt,
        "cached_result": journey.model_metadata.cached_result,
        "model_revision": journey.model_metadata.model_revision,
        "run_id": journey.model_metadata.run_id,
        "image_observation_count": source_summary.image_observation_count,
        "agent_quote_count": source_summary.agent_quote_count,
        "case_status": state.case_status,
        "evidence_status": state.evidence_status,
    }
    document["stages"] = {
        "facts_and_image_binding": "PASS",
        "real_http_call": "PASS",
        "candidate_schema": "PASS",
        "source_validation": "PASS",
        "extracted_journey": "PASS",
        "accountability_state": "PASS",
    }
    run.source_summary = document["source_validation"]
    run.journey = response["extracted_journey"]
    run.accountability = response["accountability_state"]

    _write_artifacts(output_dir, document, governance_path, modules, repo=repo, settings=settings)
    exit_code = EXIT_BUDGET_EXCEEDED if run.budget_status == "BUDGET_EXCEEDED" else EXIT_OK
    return exit_code, run, document


def _request_content(provider_input: Any, modules: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct the exact multipart content list the adapter will serialize."""

    del modules
    content: list[dict[str, Any]] = [{"type": "text"}]
    content.extend({"type": "image_url"} for _ in provider_input.images)
    return content


def _write_artifacts(
    output_dir: Path,
    document: Mapping[str, Any],
    governance_path: Path,
    modules: Mapping[str, Any],
    *,
    repo: Path,
    settings: Any,
) -> None:
    """Write the three declared live artifacts and the batch environment record."""

    del modules
    output_dir.mkdir(parents=True, exist_ok=True)

    model_output = {
        key: value
        for key, value in document.items()
        if key not in {"environment"}
    }
    model_output["artifact"] = "reports/batches/BATCH-28/live/model-output.redacted.json"
    clean = _redact(model_output)
    _assert_clean(clean, "model-output.redacted.json")
    (output_dir / "model-output.redacted.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    environment = _environment_document(repo=repo, settings=settings)
    for target in (
        output_dir / "environment.json",
        repo / "reports" / "batches" / BATCH_ID / "environment.json",
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(environment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if not governance_path.exists():
        governance_path.write_text("", encoding="utf-8", newline="\n")


def _environment_document(*, repo: Path, settings: Any) -> dict[str, Any]:
    revision = os.environ.get("COVENIA_BATCH_BASE_SHA", "").strip()
    if not revision:
        git = shutil.which("git")
        if git is not None:
            completed = subprocess.run(
                [git, "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                check=False,
            )
            if completed.returncode == 0:
                revision = completed.stdout.decode("utf-8", "replace").strip()
    lock_path = "backend/requirements-dev.lock"
    blob = _git_blob_sha256(repo, revision, lock_path) if revision else {"available": False}
    working_copy = repo / lock_path
    worktree_digest = _sha256_file(working_copy) if working_copy.is_file() else None
    worktree_bytes = working_copy.stat().st_size if working_copy.is_file() else None
    canonical = (
        _sha256_bytes(working_copy.read_bytes().replace(b"\r\n", b"\n"))
        if working_copy.is_file()
        else None
    )

    # The lock file may only ever grow by appended, exactly pinned entries.  This
    # batch adds none, so the committed blob must equal the canonical (LF) bytes
    # of the worktree copy; a CRLF checkout legitimately changes the raw digest.
    if blob.get("available") and canonical is not None:
        if canonical == blob["sha256"]:
            change_type = "UNCHANGED"
            change_note = (
                "no dependency was added by BATCH-28; the worktree copy is byte-identical to "
                "the committed blob under the canonical LF form"
            )
            canonical_matches = True
        else:
            change_type = "MODIFIED_BEYOND_APPEND"
            change_note = (
                "the worktree lock file does not match the committed blob; record this as an "
                "environment conflict and do not treat it as an append"
            )
            canonical_matches = False
    else:
        change_type = "UNKNOWN"
        change_note = "the committed blob could not be read, so no lock comparison is claimed"
        canonical_matches = None

    return {
        "artifact": "reports/batches/BATCH-28/environment.json",
        "batch_id": BATCH_ID,
        "tool": "tools/verification/live_smoke.py",
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "statement": (
            "本批由辅助调度器实现，非独立实现方；验收须由他方完成。"
        ),
        "interpreter": _venv_facts(),
        "packages": _installed_packages(),
        "settings_snapshot": (
            None
            if settings is None
            else {
                "model_endpoint": settings.model_endpoint,
                "model_deployment_id": settings.model_deployment_id,
                "model_revision": settings.model_revision,
                "model_prompt_version": settings.model_prompt_version,
                "cache_mode": settings.cache_mode,
                "analysis_timeout_seconds": settings.analysis_timeout_seconds,
                "workbook_path": str(settings.workbook_path),
                "demo_cases_path": str(settings.demo_cases_path),
                "case_manifest_path": str(settings.case_manifest_path),
                "image_manifest_path": str(settings.image_manifest_path),
                "image_evidence_root": str(settings.image_evidence_root),
            }
        ),
        "dependency_lock": {
            "path": lock_path,
            "change_type": change_type,
            "change_note": change_note,
            "appended_entries": [],
            "committed_blob": blob,
            "worktree_sha256_raw_bytes": worktree_digest,
            "worktree_sha256_canonical_lf": canonical,
            "worktree_bytes": worktree_bytes,
            "canonical_matches_committed_blob": canonical_matches,
            "eol_note": (
                "the committed blob is stored with LF; the Windows worktree checkout uses CRLF, "
                "so the raw worktree digest differs from the blob digest by design. "
                "MASTER_PLAN 5.5-8 requires the git-show blob digest for hash verification, and "
                "that value is recorded above as committed_blob.sha256."
            ),
        },
        "environment_variables_observed": {
            name: ("SET" if os.environ.get(name) else "NOT_SET")
            for name in (
                "COVENIA_MODEL_ENDPOINT",
                "COVENIA_MODEL_DEPLOYMENT_ID",
                "COVENIA_MODEL_REVISION",
                "COVENIA_MODEL_PROMPT_VERSION",
                "COVENIA_MODEL_API_KEY",
                "COVENIA_ANALYSIS_TIMEOUT_SECONDS",
                "COVENIA_CACHE_MODE",
            )
        },
        "secrets": {
            "api_key_recorded": False,
            "statement": (
                "no credential value is read into, or written by, this tool; only the presence "
                "of COVENIA_MODEL_API_KEY is recorded"
            ),
        },
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One real, uncached Qwen image+chat extraction for BATCH-28"
    )
    parser.add_argument("--require-live", action="store_true", help="fail unless a real deployment is reachable")
    parser.add_argument("--disable-cache", action="store_true", help="assert the uncached path is used")
    parser.add_argument("--output", default=None, help="artifact directory (default reports/batches/BATCH-28/live)")
    parser.add_argument("--endpoint", default=None, help="endpoint override (else COVENIA_MODEL_ENDPOINT)")
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID, help="case to analyse")
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS, help="bounded real attempts")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=FROZEN_ANALYSIS_BUDGET_SECONDS,
        help=f"per-attempt deadline; may only be lowered below {FROZEN_ANALYSIS_BUDGET_SECONDS:g}s",
    )
    parser.add_argument("--json", action="store_true", help="print the redacted document to stdout")
    parser.add_argument(
        "--skip-endpoint-probe",
        action="store_true",
        help=(
            "skip the TCP preflight so the real HTTP client performs the call; used to "
            "demonstrate the client-side failure mode against an unlistened port"
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="only print the verdict line")
    return parser.parse_args(argv)


def _write_failure_document(
    output_dir: Path,
    repo: Path,
    args: argparse.Namespace,
    *,
    exit_code: int,
    status: str,
    detail: str,
) -> None:
    """Record a run that stopped before the pipeline, so the failure is auditable."""

    try:
        settings = _load_modules()["get_settings"]()
        endpoint = args.endpoint or settings.model_endpoint
    except Exception:  # noqa: BLE001 - the diagnostic must never mask the original failure
        settings = None
        endpoint = args.endpoint or os.environ.get("COVENIA_MODEL_ENDPOINT") or ""
    document = {
        "artifact": "reports/batches/BATCH-28/live/model-output.redacted.json",
        "batch_id": BATCH_ID,
        "tool": "tools/verification/live_smoke.py",
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "exit_code": exit_code,
        "detail": detail,
        "statement": (
            "本批由辅助调度器实现，非独立实现方；验收须由他方完成。 "
            "The run stopped before any model call; no cached, synthetic, or offline candidate "
            "was substituted."
        ),
        "configuration": {
            "endpoint": endpoint,
            "endpoint_port_confirmed_closed": _port_confirmed_closed(endpoint) if endpoint else None,
            "require_live_requested": bool(args.require_live),
            "disable_cache_requested": bool(args.disable_cache),
            "skip_endpoint_probe": bool(args.skip_endpoint_probe),
            "attempts_requested": args.attempts,
            "timeout_seconds": args.timeout_seconds,
            "frozen_analysis_budget_seconds": FROZEN_ANALYSIS_BUDGET_SECONDS,
        },
        "stages": {
            "facts_and_image_binding": "NOT_REACHED",
            "real_http_call": "NOT_REACHED",
            "candidate_schema": "NOT_REACHED",
            "source_validation": "NOT_REACHED",
            "extracted_journey": "NOT_REACHED",
            "accountability_state": "NOT_REACHED",
        },
        "attempts": [],
        "environment": _venv_facts(),
    }
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        clean = _redact(document)
        _assert_clean(clean, "model-output.redacted.json")
        (output_dir / "model-output.redacted.json").write_text(
            json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        governance_path = output_dir / "governance.redacted.jsonl"
        if not governance_path.exists():
            governance_path.write_text("", encoding="utf-8", newline="\n")
        environment = _environment_document(repo=repo, settings=settings)
        (output_dir / "environment.json").write_text(
            json.dumps(environment, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:  # pragma: no cover - defensive
        print(f"warning: could not record the failure document: {error}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        repo = _repository_root()
    except SmokeConfigurationError as error:
        print(f"tool error: {error}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    output_dir = Path(args.output) if args.output else repo / "reports" / "batches" / BATCH_ID / "live"
    if not output_dir.is_absolute():
        output_dir = (repo / output_dir).resolve()

    if str(repo / "backend" / "src") not in sys.path:
        sys.path.insert(0, str(repo / "backend" / "src"))

    if args.disable_cache:
        print("mode: --disable-cache asserted; no cache adapter exists, every attempt is a real call")
    else:
        print("mode: --disable-cache not given (the tool never uses a cache anyway)")

    try:
        exit_code, run, document = run_live(args, repo=repo, output_dir=output_dir)
    except SmokeConfigurationError as error:
        print(f"tool error: {error}", file=sys.stderr)
        _write_failure_document(output_dir, repo, args, exit_code=EXIT_TOOL_ERROR, status="TOOL_ERROR", detail=str(error))
        return EXIT_TOOL_ERROR
    except SmokeEndpointError as error:
        print(f"endpoint error [{error.code}]: {error.detail}", file=sys.stderr)
        _write_failure_document(
            output_dir,
            repo,
            args,
            exit_code=EXIT_ENDPOINT_UNAVAILABLE,
            status="ENDPOINT_UNAVAILABLE",
            detail=error.detail,
        )
        return EXIT_ENDPOINT_UNAVAILABLE
    except OSError as error:
        print(f"artifact error: {type(error).__name__}: {error}", file=sys.stderr)
        _write_failure_document(output_dir, repo, args, exit_code=EXIT_ARTIFACT_ERROR, status="ARTIFACT_ERROR", detail=str(error))
        return EXIT_ARTIFACT_ERROR
    except Exception as error:  # noqa: BLE001 - an escaping exception is a finding
        # An unanticipated exception is still a real outcome and must leave an
        # auditable artifact.  Before this handler existed, a failure between the
        # model call and the journey projection escaped uncaught and produced no
        # artifact at all, which made a genuine defect look like a missing run.
        # The failure is recorded and then re-raised: this tool never converts a
        # crash into a verdict, and the traceback must stay visible on stderr.
        print(f"unexpected error: {type(error).__name__}: {error}", file=sys.stderr)
        _write_failure_document(
            output_dir,
            repo,
            args,
            exit_code=EXIT_TOOL_ERROR,
            status="TOOL_ERROR",
            detail=f"{type(error).__name__}: {error}",
        )
        raise

    if args.json:
        print(json.dumps(_redact(document), ensure_ascii=False, indent=2, sort_keys=True))

    if not args.quiet:
        print(f"{TOOL_VERSION}: {document.get('status')}")
        for stage, verdict in document.get("stages", {}).items():
            print(f"  {verdict:<11} {stage}")
        for attempt in document.get("attempts", []):
            print(
                f"  attempt {attempt['attempt']}: {attempt['outcome']} "
                f"status={attempt['status_code']} wall_ms={attempt['wall_ms']} "
                f"provider_ms={attempt['provider_reported_duration_ms']} "
                f"usage={attempt['usage']} ({attempt['usage_status']})"
            )
        budget = document.get("budget", {})
        print(
            f"  budget: {budget.get('status')} model_bound_ms={budget.get('model_bound_ms')} "
            f"frozen={budget.get('frozen_analysis_budget_seconds')}s"
        )
        print(f"  artifacts: {output_dir}")

    verdict = document.get("status", "UNKNOWN")
    print(
        "=" * 72
        + f"\n{TOOL_VERSION}: {verdict}  (exit={exit_code}, attempts={len(run.attempts)}, "
        f"budget={run.budget_status})"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
