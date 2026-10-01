"""Small integration compatibility smoke; no independent acceptance verdict."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import covenia_b.images.resolver as resolver_module
from covenia_b.domain.types import EvidenceImage
from covenia_b.images import ImageContentRejected, ManifestImageResolver, ProviderImageInput
from covenia_b.ports.contracts import ModelProvider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    assert ModelProvider is not None
    assert ProviderImageInput.__dataclass_params__.frozen
    assert [f.name for f in dataclasses.fields(ProviderImageInput)] == [
        "content", "media_type", "content_sha256", "byte_length", "width", "height"
    ]
    spec = importlib.util.spec_from_file_location(
        "batch08_smoke_test_helpers", args.repo / "backend/tests/images/test_resolver.py"
    )
    assert spec and spec.loader
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    manifest_path = args.repo / "handoff/a/images-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = args.repo / "frontend/public/evidence"
    resolver = ManifestImageResolver.from_manifest_file(manifest_path=manifest_path, evidence_root=root)
    real = []
    for entry in manifest["images"]:
        evidence = EvidenceImage(
            evidence_id=entry["evidence_id"], file_name=entry["file_name"],
            submitted_at="2026-10-02T00:12:00+08:00", declared_view_type="OTHER",
            source_kind=entry["source_kind"], source_message_id=entry["source_message_id"],
            competition_reference_path=entry.get("competition_reference_path"),
        )
        resolved = resolver.resolve_details(evidence)
        payload = (root / entry["file_name"]).read_bytes()
        assert isinstance(resolved.provider_image, ProviderImageInput)
        assert resolved.provider_image.content == payload
        actual_hash = hashlib.sha256(payload).hexdigest()
        assert actual_hash == entry["sha256"].lower() == resolved.provider_image.content_sha256
        real.append({"evidence_id": entry["evidence_id"], "bytes": len(payload),
                     "verified_provider_content_sha256": actual_hash,
                     "media_type": resolved.provider_image.media_type,
                     "width": resolved.provider_image.width, "height": resolved.provider_image.height})
    assert len(real) == 5
    controls = []
    cases = (
        ("missing-dqt", helpers.minimal_test_jpeg(include_dqt=False), "jpeg_dqt_undefined"),
        ("missing-dht", helpers.minimal_test_jpeg(include_dht=False), "jpeg_dht_undefined"),
        ("valid-table-bearing", helpers.minimal_test_jpeg(), None),
    )
    original_class = resolver_module.ProviderImageInput
    for name, body, expected in cases:
        entries = [helpers.manifest_entry(f"smoke-{i}", filename, body, mime="image/jpeg")
                   for i, filename in enumerate(("registered-first.jpg", "registered-renamed.jpg"))]
        fixture = args.run_dir / "probe" / name
        local_resolver, local_root = helpers.resolver_for(fixture, entries)
        for entry in entries:
            (local_root / str(entry["file_name"])).write_bytes(body)
        inputs = []
        results = []
        dispatches = 0
        with patch.object(resolver_module, "ProviderImageInput", wraps=original_class) as constructor:
            for entry in entries:
                try:
                    provider_input = local_resolver.resolve_for_provider(
                        helpers.evidence(str(entry["evidence_id"]), str(entry["file_name"]))
                    )
                    dispatches += 1  # Protocol double only, no provider/network call.
                    inputs.append(provider_input)
                    results.append("ACCEPTED")
                except ImageContentRejected as exc:
                    results.append(exc.code)
            constructors = constructor.call_count
        if expected:
            assert results == [expected, expected]
            assert constructors == 0 and dispatches == 0
        else:
            assert results == ["ACCEPTED", "ACCEPTED"]
            assert inputs[0] == inputs[1]
            assert inputs[0].safe_media_description() == inputs[1].safe_media_description()
        controls.append({"case": name, "results_under_two_filenames": results,
                         "ProviderImageInput_constructions": constructors,
                         "protocol_double_dispatches": dispatches, "passed": True})
    result = {
        "role": "integration compatibility smoke", "independent_acceptance_repeated": False,
        "real_local_images_resolved": len(real), "real_images": real,
        "frozen_provider_image_input_interface": "PASS", "controls": controls,
        "model_or_network_calls": 0, "live_model_inference": False, "all_passed": True,
        "asset_hash_note": "SHA-256 here is runtime media integrity, not Git file provenance; file provenance is raw git show in commit-and-protection.json",
    }
    (args.run_dir / "image-smoke.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
