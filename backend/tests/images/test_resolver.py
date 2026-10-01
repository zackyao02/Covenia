"""BATCH-08 security tests use generated minimal images, never team evidence assets."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

import covenia_b.images.resolver as resolver_module
from covenia_b.domain.types import EvidenceImage
from covenia_b.images.resolver import (
    ImageContentRejected,
    ImageManifest,
    ImageManifestError,
    ImagePathRejected,
    ManifestImageResolver,
)


def _png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    return (
        struct.pack(">I", len(chunk_data))
        + chunk_type
        + chunk_data
        + struct.pack(">I", zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
    )


def minimal_test_png(width: int = 1, height: int = 1, pixel: bytes = b"\x12\x34\x56") -> bytes:
    """Create an explicitly synthetic, unlabelled RGB PNG for BATCH-08 tests."""

    if len(pixel) != 3:
        raise ValueError("A minimal RGB test pixel requires exactly three bytes.")
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    scanlines = b"".join(b"\x00" + pixel * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(scanlines))
        + _png_chunk(b"IEND", b"")
    )


def corrupt_test_png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", b"not-zlib-image-data")
        + _png_chunk(b"IEND", b"")
    )


def _jpeg_segment(marker: bytes, segment: bytes) -> bytes:
    return marker + struct.pack(">H", len(segment) + 2) + segment


def minimal_test_jpeg(
    trailing: bytes = b"", *, include_dqt: bool = True, include_dht: bool = True
) -> bytes:
    """Create a minimal table-bearing 1x1 baseline JPEG fixture."""

    dqt = _jpeg_segment(b"\xff\xdb", b"\x00" + b"\x01" * 64)
    dc_table = b"\x00\x01" + b"\x00" * 15 + b"\x00"
    ac_table = b"\x10\x01" + b"\x00" * 15 + b"\x00"
    dht = _jpeg_segment(b"\xff\xc4", dc_table + ac_table)
    sof0 = b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    sos = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    return (
        b"\xff\xd8"
        + (dqt if include_dqt else b"")
        + (dht if include_dht else b"")
        + sof0
        + sos
        + b"\x00\xff\xd9"
        + trailing
    )


def evidence(
    evidence_id: str,
    file_name: str,
    *,
    source_message_id: str = "message-001",
    source_kind: str = "TEAM_SYNTHETIC_RECREATION",
    competition_reference_path: str | None = "mock_images/original.jpg",
) -> EvidenceImage:
    return EvidenceImage(
        evidence_id=evidence_id,
        file_name=file_name,
        submitted_at="2026-09-12T00:00:00+08:00",
        declared_view_type="OTHER",
        source_kind=source_kind,
        source_message_id=source_message_id,
        competition_reference_path=competition_reference_path,
    )


def manifest_entry(
    evidence_id: str,
    file_name: str,
    body: bytes,
    *,
    width: int = 1,
    height: int = 1,
    mime: str = "image/png",
    declared_view_type: str = "NEED_HUMAN_REVIEW",
    source_message_id: str = "message-001",
    source_kind: str = "TEAM_SYNTHETIC_RECREATION",
    competition_reference_path: str | None = "mock_images/original.jpg",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "file_name": file_name,
        "repo_target_path": f"frontend/public/evidence/{file_name}",
        "source_message_id": source_message_id,
        "source_kind": source_kind,
        "competition_reference_path": competition_reference_path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "mime": mime,
        "dimensions": {"width": width, "height": height},
        "declared_view_type": declared_view_type,
        "sku_label": "UNTRUSTED-SKU-LABEL",
    }


def write_manifest(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    manifest_path = tmp_path / "images-manifest.json"
    manifest_path.write_text(json.dumps({"images": entries}), encoding="utf-8")
    return manifest_path


def resolver_for(
    tmp_path: Path,
    entries: list[dict[str, object]],
    *,
    max_bytes: int = 10 * 1024 * 1024,
    max_pixels: int = 16_000_000,
    max_dimension: int = 8_192,
) -> tuple[ManifestImageResolver, Path]:
    root = tmp_path / "evidence"
    root.mkdir(parents=True)
    manifest_path = write_manifest(tmp_path, entries)
    return (
        ManifestImageResolver.from_manifest_file(
            manifest_path=manifest_path,
            evidence_root=root,
            max_bytes=max_bytes,
            max_pixels=max_pixels,
            max_dimension=max_dimension,
        ),
        root,
    )


def test_resolves_registered_bytes_into_separate_provenance_and_provider_payload(
    tmp_path: Path,
) -> None:
    body = minimal_test_png()
    entry = manifest_entry("evidence-001", "minimal.png", body)
    resolver, root = resolver_for(tmp_path, [entry])
    (root / "minimal.png").write_bytes(body)

    resolved = resolver.resolve_details(evidence("evidence-001", "minimal.png"))

    assert resolved.handle.evidence_id == "evidence-001"
    assert resolved.handle.content_sha256 == hashlib.sha256(body).hexdigest()
    assert resolved.provider_image.content == body
    assert resolved.provenance.source_message_id == "message-001"
    assert resolved.provenance.source_kind == "TEAM_SYNTHETIC_RECREATION"
    assert resolved.provenance.competition_reference_path == "mock_images/original.jpg"
    assert resolved.provider_image.safe_media_description() == {
        "media_type": "image/png",
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "byte_length": len(body),
        "width": 1,
        "height": 1,
    }


def test_same_file_name_changed_bytes_are_hashed_and_rejected_before_provider_call(
    tmp_path: Path,
) -> None:
    original = minimal_test_png(pixel=b"\x12\x34\x56")
    replacement = minimal_test_png(pixel=b"\xaa\xbb\xcc")
    entry = manifest_entry("evidence-001", "same-name.png", original)
    resolver, root = resolver_for(tmp_path, [entry])
    image_path = root / "same-name.png"
    image_path.write_bytes(replacement)
    provider_calls: list[object] = []

    def dispatch() -> None:
        provider_calls.append(
            resolver.resolve_for_provider(evidence("evidence-001", "same-name.png"))
        )

    with pytest.raises(ImageContentRejected) as raised:
        dispatch()

    assert raised.value.code == "sha256_mismatch"
    assert raised.value.details["actual_sha256"] == hashlib.sha256(replacement).hexdigest()
    assert raised.value.details["actual_sha256"] != raised.value.details["expected_sha256"]
    assert provider_calls == []


def test_different_registered_file_names_with_same_bytes_have_identical_provider_input(
    tmp_path: Path,
) -> None:
    body = minimal_test_png()
    first = manifest_entry("evidence-001", "first.png", body, declared_view_type="PRODUCT_OVERVIEW")
    second = manifest_entry("evidence-002", "renamed.png", body, declared_view_type="VALID")
    resolver, root = resolver_for(tmp_path, [first, second])
    (root / "first.png").write_bytes(body)
    (root / "renamed.png").write_bytes(body)

    first_input = resolver.resolve_for_provider(evidence("evidence-001", "first.png"))
    second_input = resolver.resolve_for_provider(evidence("evidence-002", "renamed.png"))

    assert first_input == second_input
    description = first_input.safe_media_description()
    assert "file_name" not in description
    assert "declared_view_type" not in description
    assert "sku_label" not in description
    assert "source_message_id" not in description


def test_missing_file_does_not_call_provider(tmp_path: Path) -> None:
    body = minimal_test_png()
    resolver, _ = resolver_for(tmp_path, [manifest_entry("evidence-001", "missing.png", body)])
    provider_calls: list[object] = []

    def dispatch() -> None:
        provider_calls.append(
            resolver.resolve_for_provider(evidence("evidence-001", "missing.png"))
        )

    with pytest.raises(ImagePathRejected) as raised:
        dispatch()

    assert raised.value.code == "missing_file"
    assert provider_calls == []


def test_corrupt_bytes_and_manifest_mime_mismatch_are_rejected(tmp_path: Path) -> None:
    corrupt = corrupt_test_png()
    corrupt_entry = manifest_entry("evidence-001", "corrupt.png", corrupt)
    resolver, root = resolver_for(tmp_path, [corrupt_entry])
    (root / "corrupt.png").write_bytes(corrupt)

    with pytest.raises(ImageContentRejected, match="decompressed") as corrupt_error:
        resolver.resolve(evidence("evidence-001", "corrupt.png"))
    assert corrupt_error.value.code == "png_decode_failed"

    valid = minimal_test_png()
    mismatch_entry = manifest_entry("evidence-002", "mime.png", valid, mime="image/jpeg")
    mismatch_resolver, mismatch_root = resolver_for(tmp_path / "mime", [mismatch_entry])
    (mismatch_root / "mime.png").write_bytes(valid)

    with pytest.raises(ImageContentRejected) as mismatch_error:
        mismatch_resolver.resolve(evidence("evidence-002", "mime.png"))
    assert mismatch_error.value.code == "mime_mismatch"


def test_jpeg_bounded_trailing_data_is_supported_but_excess_is_rejected(tmp_path: Path) -> None:
    accepted = minimal_test_jpeg(b"metadata" * 3)
    accepted_entry = manifest_entry("evidence-001", "accepted.jpg", accepted, mime="image/jpeg")
    accepted_resolver, accepted_root = resolver_for(tmp_path / "accepted", [accepted_entry])
    (accepted_root / "accepted.jpg").write_bytes(accepted)
    assert (
        accepted_resolver.resolve(evidence("evidence-001", "accepted.jpg")).media_type
        == "image/jpeg"
    )

    rejected = minimal_test_jpeg(b"x" * 65)
    rejected_entry = manifest_entry("evidence-002", "rejected.jpg", rejected, mime="image/jpeg")
    rejected_resolver, rejected_root = resolver_for(tmp_path / "rejected", [rejected_entry])
    (rejected_root / "rejected.jpg").write_bytes(rejected)
    with pytest.raises(ImageContentRejected) as raised:
        rejected_resolver.resolve(evidence("evidence-002", "rejected.jpg"))
    assert raised.value.code == "jpeg_trailing_data"


def _assert_jpeg_table_rejection_before_provider_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: bytes,
    file_names: tuple[str, str],
    expected_code: str,
) -> None:
    entries = [
        manifest_entry(f"evidence-{index}", file_name, body, mime="image/jpeg")
        for index, file_name in enumerate(file_names, start=1)
    ]
    resolver, root = resolver_for(tmp_path, entries)
    for file_name in file_names:
        (root / file_name).write_bytes(body)
    provider_dispatch_calls: list[object] = []
    provider_inputs_constructed: list[object] = []

    def unreachable_provider_input(**kwargs: object) -> object:
        provider_inputs_constructed.append(kwargs)
        raise AssertionError("ProviderImageInput must not be constructed for rejected JPEG bytes")

    monkeypatch.setattr(resolver_module, "ProviderImageInput", unreachable_provider_input)

    for index, file_name in enumerate(file_names, start=1):
        with pytest.raises(ImageContentRejected) as raised:
            provider_dispatch_calls.append(
                resolver.resolve_for_provider(evidence(f"evidence-{index}", file_name))
            )

        assert raised.value.code == expected_code
        assert provider_dispatch_calls == []
        assert provider_inputs_constructed == []


def test_jpeg_missing_dqt_is_rejected_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_jpeg_table_rejection_before_provider_input(
        tmp_path,
        monkeypatch,
        body=minimal_test_jpeg(include_dqt=False),
        file_names=("missing-dqt.jpg", "renamed-missing-dqt.jpg"),
        expected_code="jpeg_dqt_undefined",
    )


def test_jpeg_missing_dht_is_rejected_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_jpeg_table_rejection_before_provider_input(
        tmp_path,
        monkeypatch,
        body=minimal_test_jpeg(include_dht=False),
        file_names=("missing-dht.jpg", "renamed-missing-dht.jpg"),
        expected_code="jpeg_dht_undefined",
    )


def test_byte_and_pixel_limits_are_enforced(tmp_path: Path) -> None:
    body = minimal_test_png(width=2, height=2)
    entry = manifest_entry("evidence-001", "limits.png", body, width=2, height=2)
    bytes_resolver, bytes_root = resolver_for(tmp_path / "bytes", [entry], max_bytes=8)
    (bytes_root / "limits.png").write_bytes(body)

    with pytest.raises(ImageContentRejected) as byte_error:
        bytes_resolver.resolve(evidence("evidence-001", "limits.png"))
    assert byte_error.value.code == "file_too_large"

    pixel_resolver, pixel_root = resolver_for(tmp_path / "pixels", [entry], max_pixels=1)
    (pixel_root / "limits.png").write_bytes(body)
    with pytest.raises(ImageContentRejected) as pixel_error:
        pixel_resolver.resolve(evidence("evidence-001", "limits.png"))
    assert pixel_error.value.code == "pixel_limit_exceeded"


@pytest.mark.parametrize(
    ("unsafe_name", "expected_code"),
    [
        ("..\\outside.png", "unsafe_file_name"),
        ("https://169.254.169.254/latest/meta-data", "unsafe_file_name"),
    ],
)
def test_path_traversal_and_urls_are_rejected_without_network(
    tmp_path: Path, unsafe_name: str, expected_code: str
) -> None:
    body = minimal_test_png()
    resolver, root = resolver_for(tmp_path, [manifest_entry("evidence-001", "safe.png", body)])
    (root / "safe.png").write_bytes(body)

    with pytest.raises(ImagePathRejected) as raised:
        resolver.resolve(evidence("evidence-001", unsafe_name))
    assert raised.value.code == expected_code


def test_manifest_rejects_remote_repo_target(tmp_path: Path) -> None:
    body = minimal_test_png()
    entry = manifest_entry("evidence-001", "safe.png", body)
    entry["repo_target_path"] = "https://example.invalid/safe.png"
    manifest_path = write_manifest(tmp_path, [entry])

    with pytest.raises(ImageManifestError) as raised:
        ImageManifest.from_file(manifest_path)
    assert raised.value.code == "unsafe_repo_target"


def test_out_of_root_resolved_link_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = minimal_test_png()
    resolver, root = resolver_for(tmp_path, [manifest_entry("evidence-001", "linked.png", body)])
    outside = tmp_path / "outside.png"
    outside.write_bytes(body)
    link = root / "linked.png"

    real_resolve = Path.resolve

    def resolve_link(path: Path, *, strict: bool = False) -> Path:
        if path == link:
            return real_resolve(outside, strict=True)
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_link)

    with pytest.raises(ImagePathRejected) as raised:
        resolver.resolve(evidence("evidence-001", "linked.png"))
    assert raised.value.code == "symlink_outside_root"


def test_source_provenance_must_match_manifest_and_stays_outside_provider_payload(
    tmp_path: Path,
) -> None:
    body = minimal_test_png()
    entry = manifest_entry(
        "evidence-001",
        "source.png",
        body,
        source_message_id="team-message-77",
        source_kind="TEAM_SYNTHETIC_AUGMENTATION",
        competition_reference_path="mock_images/original-path.jpg",
    )
    resolver, root = resolver_for(tmp_path, [entry])
    (root / "source.png").write_bytes(body)

    details = resolver.resolve_details(
        evidence(
            "evidence-001",
            "source.png",
            source_message_id="team-message-77",
            source_kind="TEAM_SYNTHETIC_AUGMENTATION",
            competition_reference_path="mock_images/original-path.jpg",
        )
    )
    assert details.provenance.source_message_id == "team-message-77"
    assert details.provenance.source_kind == "TEAM_SYNTHETIC_AUGMENTATION"
    assert "team-message-77" not in details.provider_image.safe_media_description().values()

    with pytest.raises(ImagePathRejected) as raised:
        resolver.resolve(evidence("evidence-001", "source.png"))
    assert raised.value.code == "source_message_mismatch"
