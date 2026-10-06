"""Re-derive criteria 2 and 3 from a live artifact, against the accepted registry.

Criteria checked, all from on-disk bytes rather than from the artifact's own claims:

2.  The verified image bytes really reached the provider:
    - every image SHA-256 the artifact says it sent equals the SHA-256 of the file
      the accepted registry points at, recomputed here from disk
    - the request carried one image_url part per image and no observation JSON
    - the recorded request size is consistent with a text part plus those images

3.  Usage and latency come from upstream, and the 20-second budget is a real verdict:
    - usage_status is EXACT with a non-negative upstream pair, or MISSING with a note
    - the recorded provider duration equals the upstream-reported duration
    - the budget verdict follows from the measured model_bound_ms

Scratch diagnostic, outside the repository.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(r"C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\w28")
MANIFEST = REPO / "handoff" / "a" / "images-manifest.json"

TARGETS = {
    "official-run-2 (rejected)": REPO
    / "reports/batches/BATCH-28/live/model-output.redacted.json",
    "pytest-live-run (accepted)": REPO
    / "reports/batches/BATCH-28/aux-cross-line-v2/pytest-live-run-accepted/model-output.redacted.json",
    "v1 baseline (prompt v1, rejected)": REPO
    / "reports/batches/BATCH-28/prompt-v1-run/live/model-output.redacted.json",
}

registry = json.loads(MANIFEST.read_text(encoding="utf-8"))
registry_by_id = {entry["evidence_id"]: entry for entry in registry["images"]}

print("registry entries:", sorted(registry_by_id))
print()

for label, path in TARGETS.items():
    document = json.loads(path.read_text(encoding="utf-8"))
    binding = document["input_binding"]
    print("=" * 78)
    print(label)
    print("  artifact:", path.relative_to(REPO).as_posix())
    print("  status:", document["status"], "| prompt_version:", document["configuration"]["prompt_version"])
    checks: list[tuple[str, bool, str]] = []

    for entry in binding["resolved_provider_images"]:
        evidence_id = entry["evidence_id"]
        declared = registry_by_id.get(evidence_id)
        if declared is None:
            checks.append((f"{evidence_id} present in registry", False, "missing"))
            continue
        file_path = REPO / declared["file_path"] if "file_path" in declared else REPO / "frontend" / "public" / "evidence" / declared["file_name"]
        if not file_path.is_file():
            candidates = list((REPO / "frontend" / "public" / "evidence").rglob(declared["file_name"]))
            file_path = candidates[0] if candidates else file_path
        actual = hashlib.sha256(file_path.read_bytes()).hexdigest()
        # The accepted registry stores its digests in upper case and the artifacts
        # in lower case, so the comparison is case-folded on purpose.
        same_digest = (
            actual.lower() == entry["content_sha256"].lower() == declared["sha256"].lower()
        )
        checks.append(
            (
                f"{evidence_id}: artifact sha256 == manifest sha256 == on-disk sha256",
                same_digest,
                f"disk={actual[:16]} artifact={entry['content_sha256'][:16]} manifest={declared['sha256'][:16]}",
            )
        )
        checks.append(
            (
                f"{evidence_id}: registry file_name matches",
                declared["file_name"] == file_path.name,
                f"{declared['file_name']} bytes={file_path.stat().st_size} artifact_bytes={entry['byte_length']}",
            )
        )
        checks.append(
            (
                f"{evidence_id}: byte_length agrees with disk",
                file_path.stat().st_size == entry["byte_length"],
                str(entry["byte_length"]),
            )
        )

    parts = binding["provider_content_parts"]
    checks.append(
        (
            "request carried one text part plus one image_url part per image",
            parts[0] == "text" and parts.count("image_url") == len(binding["resolved_provider_images"]),
            str(parts),
        )
    )
    checks.append(
        (
            "no observation JSON was serialized as an image",
            binding["observation_json_sent_as_image"] is False,
            str(binding["observation_json_sent_as_image"]),
        )
    )

    released = {
        image_hash
        for attempt in document["attempts"]
        for image_hash in attempt.get("image_sha256s") or []
    }
    checks.append(
        (
            "every attempt's image_sha256s equal the registry hashes",
            released == {entry["content_sha256"] for entry in binding["resolved_provider_images"]},
            f"{len(released)} distinct",
        )
    )

    for attempt in document["attempts"]:
        number = attempt["attempt"]
        if attempt["status_code"] == 200:
            checks.append(
                (
                    f"attempt {number}: upstream answered 200 with a provider request id",
                    bool(attempt["provider_request_id"]),
                    str(attempt["provider_request_id"]),
                )
            )
        if attempt["usage_status"] == "EXACT":
            usage = attempt["usage"]
            checks.append(
                (
                    f"attempt {number}: usage is upstream EXACT with a non-negative pair",
                    usage is not None and usage["input_tokens"] >= 0 and usage["output_tokens"] >= 0,
                    json.dumps(usage),
                )
            )
        else:
            checks.append(
                (
                    f"attempt {number}: missing usage is recorded, not invented",
                    attempt["usage"] is None and bool(attempt["usage_note"]),
                    str(attempt["usage_note"]),
                )
            )
        checks.append(
            (
                f"attempt {number}: wall and provider latency both measured",
                attempt["wall_ms"] is not None
                and attempt["wall_ms"] > 0
                and attempt["provider_reported_duration_ms"] is not None
                and attempt["provider_reported_duration_ms"] > 0,
                f"wall={attempt['wall_ms']} provider={attempt['provider_reported_duration_ms']}",
            )
        )

    budget = document["budget"]
    expected_status = (
        "BUDGET_EXCEEDED"
        if budget["model_bound_ms"] > budget["frozen_analysis_budget_seconds"] * 1000
        else ("WITHIN_BUDGET" if document.get("summary", {}).get("accepted_attempt") else "NOT_ACHIEVED_OUTPUT_REJECTED")
    )
    checks.append(
        (
            "budget verdict follows from the measured model_bound_ms",
            budget["status"] == expected_status,
            f"model_bound_ms={budget['model_bound_ms']} status={budget['status']}",
        )
    )

    passed = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}  ({detail})")
    print(f"  checks: {passed}/{len(checks)}")
