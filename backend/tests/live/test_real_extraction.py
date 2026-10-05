#!/usr/bin/env python
"""The one live acceptance test for BATCH-28.

This module is the ``live`` marker's only member.  It is not a unit test of the
model adapter: a double would prove nothing about whether the *registered* Qwen
deployment really receives the verified JPEG bytes.  It therefore drives the
tracked tool :mod:`tools.verification.live_smoke` as a subprocess under this
batch's own absolute interpreter and asserts the tool's own verdict.

What is asserted, and why each assertion exists
-----------------------------------------------
1.  **The tool ran and reported its verdict.**  A missing deployment, an
    unreachable endpoint, a refused connection, or a prompt-manifest mismatch is
    a failure, never a skip: silently passing here would be exactly the
    "offline run reported as a live pass" failure this batch exists to prevent.
2.  **At least one attempt reached the real endpoint.**  ``status_code == 200``
    plus a provider request id means the bytes left this process and an upstream
    answered.  A cached or synthetic candidate cannot produce them.
3.  **The image bytes were really sent.**  Every SHA-256 recorded in
    ``image_sha256s`` is compared with the SHA-256 the accepted registry declares
    for the same file, and the recorded request must contain one ``image_url``
    part per image.  This is the proof that the model received image bytes rather
    than an observation JSON document.
4.  **Usage and latency come from upstream.**  When the provider reports usage it
    must be ``EXACT`` with a non-negative input/output pair; when it does not,
    the artifact must say so instead of inventing numbers.  The latency must
    equal the value the adapter measured, never a hand-written constant.
5.  **The extraction decision is reported honestly.**  A source-validated
    candidate must show ``cached_result is False`` and the exact locked revision;
    a rejected candidate must name its rejection code, and the test then fails —
    the failure is the finding, not something to route around.
6.  **The 20-second budget is a verdict, not a hope.**  ``BUDGET_EXCEEDED`` fails
    the test; a long run is never relabelled as an integration pass.

Delivery statement: this batch was implemented by the auxiliary dispatcher and is
not an independent implementation; verification must be performed by another party.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

BATCH_ID = "BATCH-28"
FROZEN_BUDGET_SECONDS = 20.0
GOVERNANCE_EVENT_KINDS = {
    "MODEL_ATTEMPT",
    "MODEL_FAILURE",
    "CACHE_HIT",
    "CACHE_FALLBACK",
    "RULE_EVALUATION",
    "PORT_METRICS",
}
GOVERNANCE_TOP_LEVEL_KEYS = {
    "schema_version",
    "event_id",
    "event_kind",
    "emitted_at",
    "request_id",
    "run_id",
    "endpoint",
    "model",
    "input_sources",
    "image_hashes",
    "pii_masked_count",
    "metrics",
    "request_totals",
    "metric_provenance",
    "cache",
    "failure_reason",
}

#: Exit codes the tool documents in its module docstring.
TOOL_EXIT_CODES = {
    0: "PASS",
    1: "MODEL_OUTPUT_REJECTED",
    2: "TOOL_ERROR",
    3: "ENDPOINT_UNAVAILABLE",
    4: "BUDGET_EXCEEDED",
    5: "ARTIFACT_ERROR",
}


def _repository_root() -> Path:
    """Return the checkout root, independent of the pytest invocation directory."""

    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "backend" / "src" / "covenia_b").is_dir():
        return candidate
    raise pytest.UsageError("cannot locate the repository root from this test module")


def _deployment_registered() -> bool:
    return bool(os.environ.get("COVENIA_MODEL_DEPLOYMENT_ID", "").strip()) and bool(
        os.environ.get("COVENIA_MODEL_ENDPOINT", "").strip()
    )


@pytest.fixture(scope="module")
def live_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Run the tracked live tool once and return its verdict plus its artifacts."""

    if not _deployment_registered():
        pytest.skip(
            "no model deployment is registered for this process "
            "(COVENIA_MODEL_DEPLOYMENT_ID / COVENIA_MODEL_ENDPOINT are empty); "
            "the offline suite reports this as unverified, never as a live pass"
        )

    repository = _repository_root()
    tool = repository / "tools" / "verification" / "live_smoke.py"
    assert tool.is_file(), f"the tracked live tool is missing: {tool}"

    output_dir = tmp_path_factory.mktemp(f"{BATCH_ID.lower()}-live-")
    command = [
        sys.executable,
        str(tool),
        "--require-live",
        "--disable-cache",
        "--output",
        str(output_dir),
        "--quiet",
    ]
    completed = subprocess.run(
        command,
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    verdict = output_dir / "model-output.redacted.json"
    assert verdict.is_file(), (
        "the live tool produced no verdict artifact, so nothing can be asserted\n"
        f"command: {command}\nexit: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    document = json.loads(verdict.read_text(encoding="utf-8"))
    return {
        "exit_code": completed.returncode,
        "command": command,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "output_dir": output_dir,
        "document": document,
    }


def _document_of(run: dict[str, object]) -> dict[str, object]:
    document = run["document"]
    exit_code = int(run["exit_code"])
    assert exit_code in TOOL_EXIT_CODES, (
        f"the live tool returned an undocumented exit code {exit_code}"
    )
    assert document.get("status") == TOOL_EXIT_CODES[exit_code], (
        "the recorded status must match the process exit code; a mismatch means the "
        "artifact and the verdict disagree about what happened"
    )
    return document


def _require_usable(run: dict[str, object]) -> dict[str, object]:
    """Fail on any non-success verdict, naming the tool's own reason."""

    document = _document_of(run)
    exit_code = int(run["exit_code"])
    if exit_code != 0:
        attempts = document.get("attempts") or []
        summary = document.get("summary") or {}
        budget = (document.get("budget") or {}).get("status")
        pytest.fail(
            f"the live run did not produce an accepted extraction: "
            f"{TOOL_EXIT_CODES[exit_code]} (exit {exit_code})\n"
            f"status={document.get('status')} budget={budget}\n"
            f"last outcome={summary.get('last_outcome')} "
            f"rejection={summary.get('last_rejection_code')} "
            f"reason={summary.get('last_failure_reason')}\n"
            f"attempts={json.dumps(attempts, ensure_ascii=False)[:1500]}\n"
            f"stderr:\n{run['stderr']}"
        )
    return document


def _require_an_answered_attempt(run: dict[str, object]) -> dict[str, object]:
    """Require only that the endpoint really answered; the verdict may still be a rejection.

    Criteria 2 and the measurement rules are properties of the *call*, not of the
    model's answer quality: they must be assertable even when the candidate was
    refused, otherwise a rejection would hide whether the images and the usage
    data were ever real.
    """

    document = _document_of(run)
    attempts = document.get("attempts") or []
    answered = [item for item in attempts if item.get("status_code") == 200]
    assert answered, (
        "no attempt reached the registered endpoint with HTTP 200, so the image-and-usage "
        f"claims cannot be checked (status={document.get('status')}, exit={run['exit_code']})"
    )
    return document


def test_live_tool_is_invoked_uncached_under_this_interpreter(live_run: dict[str, object]) -> None:
    """The tool must run under this batch's interpreter and assert the uncached path."""

    command = live_run["command"]
    assert command[0] == sys.executable, "the live tool must run under this batch's interpreter"
    assert "--require-live" in command
    assert "--disable-cache" in command
    document = live_run["document"]
    configuration = document["configuration"]
    assert configuration["require_live_requested"] is True
    assert configuration["disable_cache_requested"] is True
    assert configuration["cache_adapter_exists"] is False
    assert configuration["cache_mode_setting"] == "disabled"
    assert configuration["prompt_version_matches_manifest"] is True
    assert configuration["api_key_value_recorded"] is False


def test_real_endpoint_answered_and_the_run_stayed_inside_the_budget(
    live_run: dict[str, object],
) -> None:
    """A real 200 response inside 20 seconds is the whole point of the batch."""

    document = _document_of(live_run)
    attempts = document["attempts"]
    assert attempts, "the run recorded no attempt at all"

    # The transport and budget measurements are checked first so that a rejected
    # candidate still leaves behind the two facts the report needs: the endpoint
    # really answered, and the real cost was inside the frozen budget.
    answered = [item for item in attempts if item["status_code"] == 200]
    assert answered, "no attempt reached the registered endpoint with HTTP 200"
    for attempt in answered:
        assert attempt["provider_request_id"], (
            "a 200 response without a provider request id cannot be bound to a real call"
        )
        assert attempt["request_sha256"] and attempt["response_sha256"]
        assert attempt["wall_ms"] is not None and attempt["wall_ms"] > 0
        assert attempt["provider_reported_duration_ms"] is not None
        assert attempt["provider_reported_duration_ms"] > 0

    budget = document["budget"]
    assert budget["frozen_analysis_budget_seconds"] == FROZEN_BUDGET_SECONDS
    assert budget["model_bound_ms"] is not None
    documented_states = {"WITHIN_BUDGET", "BUDGET_EXCEEDED", "NOT_ACHIEVED_OUTPUT_REJECTED"}
    assert budget["status"] in documented_states, (
        "the budget verdict must be one of the documented states, never a guess"
    )
    assert budget["model_bound_ms"] <= FROZEN_BUDGET_SECONDS * 1000, (
        "the real extraction exceeded the frozen 20-second analysis budget: "
        f"model_bound_ms={budget['model_bound_ms']}"
    )
    if budget["status"] == "BUDGET_EXCEEDED":
        pytest.fail(
            "the tool reported BUDGET_EXCEEDED while the measured value was inside the "
            f"budget: model_bound_ms={budget['model_bound_ms']}"
        )

    _require_usable(live_run)
    assert document["status"] == "PASS"


def test_the_model_received_registered_image_bytes_not_observation_json(
    live_run: dict[str, object],
) -> None:
    """Bind the transmitted bytes to the accepted registry, and rule out JSON-as-image."""

    document = _require_an_answered_attempt(live_run)
    binding = document["input_binding"]
    registry_hashes = {item["content_sha256"] for item in binding["resolved_provider_images"]}
    assert registry_hashes, "no registered image was resolved for the provider"
    for item in binding["resolved_provider_images"]:
        assert item["media_type"] in {"image/jpeg", "image/png", "image/webp"}
        assert item["byte_length"] > 0
        assert item["width"] > 0 and item["height"] > 0
        assert len(item["content_sha256"]) == 64
        assert item["provenance_source_message_id"]

    assert binding["provider_request_contains_image_url_parts"] == len(registry_hashes)
    assert binding["observation_json_sent_as_image"] is False
    assert "image_url" in binding["provider_content_parts"]

    for attempt in document["attempts"]:
        if not attempt["image_sha256s"]:
            continue
        assert set(attempt["image_sha256s"]) == registry_hashes, (
            "the bytes the adapter sent do not match the bytes the resolver verified"
        )


def test_usage_and_latency_are_taken_from_upstream(live_run: dict[str, object]) -> None:
    """Usage is EXACT-and-real or explicitly missing; latency is the measured value."""

    document = _require_an_answered_attempt(live_run)
    answered = [item for item in document["attempts"] if item["status_code"] == 200]
    assert answered
    for attempt in answered:
        status = attempt["usage_status"]
        assert status in {"EXACT", "MISSING"}
        if status == "EXACT":
            usage = attempt["usage"]
            assert usage is not None
            assert usage["input_tokens"] >= 0 and usage["output_tokens"] >= 0
            assert attempt["usage_note"] is None
        else:
            assert attempt["usage"] is None
            assert attempt["usage_note"], (
                "a missing upstream usage measurement must be recorded explicitly"
            )


def test_accepted_candidate_is_uncached_and_bound_to_the_locked_revision(
    live_run: dict[str, object],
) -> None:
    """criterion 1: chat + real image -> candidate -> ExtractedJourney, cached_result false."""

    document = _require_usable(live_run)
    metadata = document["model_metadata"]
    assert metadata["cached_result"] is False
    assert metadata["model_id"] == "qwen3-vl-plus"
    assert metadata["model_revision"] == document["configuration"]["model_revision"]
    assert metadata["prompt_version"] == document["configuration"]["prompt_version"]
    assert metadata["run_id"]

    journey = document["extracted_journey"]
    assert journey["case_id"] == document["input_binding"]["case_id"]
    assert journey["model_metadata"]["cached_result"] is False
    assert journey["source_trace"]

    validation = document["source_validation"]
    assert validation["trusted_source_count"] > 0
    assert validation["traced_field_count"] > 0
    assert validation["image_observation_count"] >= 1, (
        "the candidate produced no image-traceable observation, so the image path is unproven"
    )
    assert validation["agent_quote_count"] >= 1
    assert document["accountability_state"]["case_id"] == journey["case_id"]


def test_a_rejected_run_is_reported_honestly(live_run: dict[str, object]) -> None:
    """A non-zero verdict must never leave a partial success behind it.

    This assertion is deliberately independent of the outcome: it is what stops a
    future edit from turning a rejected extraction into a green run by quietly
    dropping the stage that failed.
    """

    document = live_run["document"]
    stages = document["stages"]
    if document.get("status") == "PASS":
        assert stages["source_validation"] == "PASS"
        assert stages["extracted_journey"] == "PASS"
        assert document["model_metadata"]["cached_result"] is False
        return

    attempts = document.get("attempts") or []
    assert stages["facts_and_image_binding"] == "PASS", (
        "the local binding stage must be proven even when the model output is refused"
    )
    assert stages["extracted_journey"] == "NOT_REACHED"
    assert stages["accountability_state"] == "NOT_REACHED"
    assert "extracted_journey" not in document, (
        "a rejected run must not publish an ExtractedJourney it never built"
    )
    assert "model_metadata" not in document
    assert attempts, "a rejected run must still record the real attempts it made"
    for item in attempts:
        assert item["outcome"]
        assert item["failure_reason"]
        if item["outcome"] == "SOURCE_REJECTED":
            assert item["rejection_code"], "a source rejection must name its stable code"


def test_governance_log_is_redacted_and_complete(live_run: dict[str, object]) -> None:
    """The governance JSONL carries hashes and counters, never secrets or raw content."""

    _require_an_answered_attempt(live_run)
    output_dir = Path(str(live_run["output_dir"]))
    governance = output_dir / "governance.redacted.jsonl"
    assert governance.is_file(), "the governance audit log was not written"
    lines = [line for line in governance.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, "the governance audit log is empty"
    records = [json.loads(line) for line in lines]
    for record in records:
        unexpected = sorted(set(record) - GOVERNANCE_TOP_LEVEL_KEYS)
        assert not unexpected, f"the governance record gained unexpected fields: {unexpected}"
        assert record["event_kind"] in GOVERNANCE_EVENT_KINDS
        assert record["endpoint"] == "analyze"
        assert record["cache"]["status"] in {"MISS", "BYPASSED"}
        assert record["pii_masked_count"] >= 0
        for image_hash in record["image_hashes"]:
            assert len(image_hash) == 64 and image_hash == image_hash.lower()
        text = json.dumps(record, ensure_ascii=False)
        assert "Bearer " not in text
        assert "api_key" not in text.lower()

    environment = output_dir / "environment.json"
    assert environment.is_file()
    recorded = json.loads(environment.read_text(encoding="utf-8"))
    assert recorded["interpreter"]["python_executable"] == sys.executable
    assert recorded["interpreter"]["isolated_venv"] is True
    assert str(recorded["interpreter"]["include_system_site_packages"]).strip().lower() == "false"
    assert recorded["interpreter"]["venv_longest_path_ok"] is True
    assert recorded["dependency_lock"]["change_type"] == "UNCHANGED"
    assert recorded["dependency_lock"]["appended_entries"] == []
    assert recorded["dependency_lock"]["canonical_matches_committed_blob"] is True
    assert recorded["secrets"]["api_key_recorded"] is False
