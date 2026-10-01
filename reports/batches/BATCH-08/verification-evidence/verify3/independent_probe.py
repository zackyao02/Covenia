from __future__ import annotations

import argparse
import hashlib
import json
import struct
import tempfile
from pathlib import Path
from typing import Any

import covenia_b.images.resolver as resolver_module
from covenia_b.domain.types import EvidenceImage
from covenia_b.images.resolver import ImageContentRejected, ManifestImageResolver


def _segment(marker: int, body: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def _jpeg(
    *,
    include_dqt: bool = True,
    include_dht: bool = True,
    frame_quantization_table: int = 0,
    scan_dc_table: int = 0,
    scan_ac_table: int = 0,
) -> bytes:
    parts = [b"\xff\xd8"]
    if include_dqt:
        parts.append(_segment(0xDB, b"\x00" + b"\x10" * 64))
    if include_dht:
        dc_table = b"\x00" + bytes((1,)) + bytes(15) + b"\x00"
        ac_table = b"\x10" + bytes((1,)) + bytes(15) + b"\x00"
        parts.append(_segment(0xC4, dc_table + ac_table))
    sof = bytes((8,)) + struct.pack(">HH", 8, 8) + bytes(
        (1, 1, 0x11, frame_quantization_table)
    )
    parts.append(_segment(0xC0, sof))
    sos = bytes((1, 1, (scan_dc_table << 4) | scan_ac_table, 0, 63, 0))
    parts.append(_segment(0xDA, sos))
    parts.append(b"\x00\xff\xd9")
    return b"".join(parts)


def _entry(evidence_id: str, file_name: str, body: bytes) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "file_name": file_name,
        "repo_target_path": f"frontend/public/evidence/{file_name}",
        "source_message_id": f"verify3-{evidence_id}",
        "source_kind": "TEAM_SYNTHETIC_RECREATION",
        "competition_reference_path": "mock_images/verify3-reference.jpg",
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "mime": "image/jpeg",
        "dimensions": {"width": 8, "height": 8},
        "declared_view_type": "NEED_HUMAN_REVIEW",
        "sku_label": "UNTRUSTED-LABEL",
    }


def _evidence(evidence_id: str, file_name: str, source_message_id: str) -> EvidenceImage:
    return EvidenceImage(
        evidence_id=evidence_id,
        file_name=file_name,
        submitted_at="2026-10-01T00:00:00+08:00",
        declared_view_type="OTHER",
        source_kind="TEAM_SYNTHETIC_RECREATION",
        source_message_id=source_message_id,
        competition_reference_path="mock_images/verify3-reference.jpg",
    )


def _resolver(root: Path, entries: list[dict[str, Any]]) -> ManifestImageResolver:
    evidence_root = root / "evidence"
    evidence_root.mkdir(parents=True)
    for entry in entries:
        (evidence_root / str(entry["file_name"])).write_bytes(entry.pop("_body"))
    manifest_path = root / "images-manifest.json"
    manifest_path.write_text(
        json.dumps({"images": entries}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ManifestImageResolver.from_manifest_file(
        manifest_path=manifest_path,
        evidence_root=evidence_root,
    )


def _negative_case(
    temp_root: Path,
    *,
    case_id: str,
    payload: bytes,
    expected_code: str,
    two_filenames: bool,
) -> dict[str, Any]:
    file_names = (
        (f"{case_id}.jpg", f"renamed-{case_id}.jpg")
        if two_filenames
        else (f"{case_id}.jpg",)
    )
    entries: list[dict[str, Any]] = []
    for index, file_name in enumerate(file_names, start=1):
        entry = _entry(f"{case_id}-{index}", file_name, payload)
        entry["_body"] = payload
        entries.append(entry)
    resolver = _resolver(temp_root / case_id, entries)

    provider_inputs_constructed: list[dict[str, object]] = []
    provider_dispatches: list[object] = []
    observed_codes: list[str] = []
    original_provider_input = resolver_module.ProviderImageInput

    def forbidden_provider_input(**kwargs: object) -> object:
        provider_inputs_constructed.append(dict(kwargs))
        raise AssertionError("ProviderImageInput construction must be unreachable")

    resolver_module.ProviderImageInput = forbidden_provider_input  # type: ignore[misc]
    try:
        for index, file_name in enumerate(file_names, start=1):
            evidence_id = f"{case_id}-{index}"
            try:
                provider_dispatches.append(
                    resolver.resolve_for_provider(
                        _evidence(evidence_id, file_name, f"verify3-{evidence_id}")
                    )
                )
            except ImageContentRejected as error:
                observed_codes.append(error.code)
    finally:
        resolver_module.ProviderImageInput = original_provider_input

    passed = (
        observed_codes == [expected_code] * len(file_names)
        and not provider_inputs_constructed
        and not provider_dispatches
    )
    return {
        "case": case_id,
        "expected_code": expected_code,
        "file_names": list(file_names),
        "same_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "observed_codes": observed_codes,
        "provider_inputs_constructed": len(provider_inputs_constructed),
        "provider_dispatches": len(provider_dispatches),
        "passed": passed,
    }


def _positive_filename_independence(temp_root: Path) -> dict[str, Any]:
    payload = _jpeg()
    entries: list[dict[str, Any]] = []
    file_names = ("neutral-a.jpg", "renamed-neutral-b.jpg")
    for index, file_name in enumerate(file_names, start=1):
        entry = _entry(f"positive-{index}", file_name, payload)
        entry["_body"] = payload
        entries.append(entry)
    resolver = _resolver(temp_root / "positive", entries)
    provider_inputs = [
        resolver.resolve_for_provider(
            _evidence(f"positive-{index}", file_name, f"verify3-positive-{index}")
        )
        for index, file_name in enumerate(file_names, start=1)
    ]
    descriptions = [provider_input.safe_media_description() for provider_input in provider_inputs]
    forbidden_keys = {
        "file_name",
        "declared_view_type",
        "sku_label",
        "source_message_id",
        "source_kind",
        "competition_reference_path",
    }
    passed = (
        provider_inputs[0] == provider_inputs[1]
        and descriptions[0] == descriptions[1]
        and not (forbidden_keys & set(descriptions[0]))
    )
    return {
        "case": "positive_filename_independence",
        "file_names": list(file_names),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "provider_inputs_equal": provider_inputs[0] == provider_inputs[1],
        "safe_media_description": descriptions[0],
        "forbidden_keys_present": sorted(forbidden_keys & set(descriptions[0])),
        "passed": passed,
    }


def _real_images(repo: Path) -> dict[str, Any]:
    manifest_path = repo / "handoff" / "a" / "images-manifest.json"
    evidence_root = repo / "frontend" / "public" / "evidence"
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resolver = ManifestImageResolver.from_manifest_file(
        manifest_path=manifest_path,
        evidence_root=evidence_root,
    )
    results: list[dict[str, Any]] = []
    all_match = True
    for raw_entry in raw_manifest["images"]:
        evidence = EvidenceImage(
            evidence_id=raw_entry["evidence_id"],
            file_name=raw_entry["file_name"],
            submitted_at="2026-10-01T00:00:00+08:00",
            declared_view_type=raw_entry.get("declared_view_type", "OTHER"),
            source_kind=raw_entry["source_kind"],
            source_message_id=raw_entry["source_message_id"],
            competition_reference_path=raw_entry.get("competition_reference_path"),
        )
        resolved = resolver.resolve_details(evidence)
        payload = (evidence_root / raw_entry["file_name"]).read_bytes()
        actual_hash = hashlib.sha256(payload).hexdigest()
        expected_hash = str(raw_entry["sha256"]).lower()
        matched = (
            actual_hash == expected_hash
            and resolved.provider_image.content_sha256 == expected_hash
            and resolved.provider_image.byte_length == raw_entry["bytes"]
            and resolved.provider_image.width == raw_entry["dimensions"]["width"]
            and resolved.provider_image.height == raw_entry["dimensions"]["height"]
            and resolved.provider_image.content == payload
        )
        all_match = all_match and matched
        results.append(
            {
                "evidence_id": raw_entry["evidence_id"],
                "source_kind": raw_entry["source_kind"],
                "source_message_id": raw_entry["source_message_id"],
                "competition_reference_path": raw_entry.get("competition_reference_path"),
                "manifest_sha256": raw_entry["sha256"],
                "sha256": actual_hash,
                "byte_length": len(payload),
                "width": resolved.provider_image.width,
                "height": resolved.provider_image.height,
                "matched_manifest": matched,
            }
        )
    return {
        "manifest": "handoff/a/images-manifest.json",
        "evidence_root": "frontend/public/evidence",
        "manifest_entry_count": len(raw_manifest["images"]),
        "resolved_count": len(results),
        "model_or_network_dependency_present": False,
        "all_match": all_match and len(results) == 5,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify3-probe-", dir=args.run_dir) as temp:
        temp_root = Path(temp)
        negative_cases = [
            _negative_case(
                temp_root,
                case_id="missing-dqt",
                payload=_jpeg(include_dqt=False),
                expected_code="jpeg_dqt_undefined",
                two_filenames=True,
            ),
            _negative_case(
                temp_root,
                case_id="missing-dht",
                payload=_jpeg(include_dht=False),
                expected_code="jpeg_dht_undefined",
                two_filenames=True,
            ),
            _negative_case(
                temp_root,
                case_id="undefined-dqt-selector",
                payload=_jpeg(frame_quantization_table=2),
                expected_code="jpeg_dqt_undefined",
                two_filenames=False,
            ),
            _negative_case(
                temp_root,
                case_id="undefined-dc-selector",
                payload=_jpeg(scan_dc_table=2),
                expected_code="jpeg_dht_undefined",
                two_filenames=False,
            ),
            _negative_case(
                temp_root,
                case_id="undefined-ac-selector",
                payload=_jpeg(scan_ac_table=2),
                expected_code="jpeg_dht_undefined",
                two_filenames=False,
            ),
        ]
        positive_case = _positive_filename_independence(temp_root)

    real_images = _real_images(args.repo)
    report = {
        "probe_version": "verify3-1.0",
        "implementation_tests_imported": False,
        "negative_cases": negative_cases,
        "positive_case": positive_case,
        "real_images": real_images,
    }
    report["all_passed"] = (
        all(case["passed"] for case in negative_cases)
        and positive_case["passed"]
        and real_images["all_match"]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
