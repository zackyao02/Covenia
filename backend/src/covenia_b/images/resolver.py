"""Resolve registered evidence files without inferring anything from their labels.

The resolver deliberately keeps provenance in a server-side record and exposes a
separate, label-free media payload for a future model provider.  It performs no
network I/O and never resolves a path supplied by a caller or an arbitrary URL.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Final

from covenia_b.domain.types import EvidenceImage, ResolvedImage
from covenia_b.ports.errors import ImageUnavailable, ImageUnreadable

_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_MAX_JPEG_TRAILING_BYTES: Final = 64
_SUPPORTED_MEDIA_TYPES: Final = frozenset({"image/jpeg", "image/png"})
_JPEG_SOF_MARKERS: Final = frozenset(
    {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
)
_PNG_CHANNELS: Final = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_PNG_ALLOWED_BITS: Final = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}
_ADAM7_PASSES: Final = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


class _CodedResolutionError:
    """Mix-in for adapter errors that can be safely handed to later batches."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details: Mapping[str, object] = MappingProxyType(dict(details))


class ImageManifestError(_CodedResolutionError, ImageUnavailable):
    """The local manifest cannot safely identify an image source."""


class ImagePathRejected(_CodedResolutionError, ImageUnavailable):
    """A registered image cannot be reached through the configured safe root."""


class ImageContentRejected(_CodedResolutionError, ImageUnreadable):
    """Image bytes exist but fail integrity, type, or structural decoding checks."""


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    """Registered source facts retained outside a provider-visible media payload."""

    evidence_id: str
    source_message_id: str
    source_kind: str
    competition_reference_path: str | None


@dataclass(frozen=True, slots=True)
class ProviderImageInput:
    """Bytes and neutral media metadata suitable for a later provider adapter."""

    content: bytes
    media_type: str
    content_sha256: str
    byte_length: int
    width: int
    height: int

    def safe_media_description(self) -> dict[str, object]:
        """Return neutral metadata with no filename, SKU, view type, or source labels."""

        return {
            "media_type": self.media_type,
            "content_sha256": self.content_sha256,
            "byte_length": self.byte_length,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class ResolvedEvidence:
    """A port-compatible handle plus separate provenance and provider bytes."""

    handle: ResolvedImage
    provider_image: ProviderImageInput
    provenance: EvidenceProvenance


@dataclass(frozen=True, slots=True)
class _ManifestEntry:
    evidence_id: str
    file_name: str
    source_message_id: str
    source_kind: str
    competition_reference_path: str | None
    expected_sha256: str
    expected_bytes: int
    expected_mime: str
    expected_width: int
    expected_height: int


@dataclass(frozen=True, slots=True)
class ImageManifest:
    """Immutable, locally loaded entries keyed by their registered evidence IDs."""

    entries: Mapping[str, _ManifestEntry]

    @classmethod
    def from_file(cls, manifest_path: str | Path) -> ImageManifest:
        path = _local_path(manifest_path, field="manifest_path")
        try:
            raw_document = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ImageManifestError(
                "manifest_missing", "The image manifest is missing."
            ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImageManifestError(
                "manifest_unreadable", "The image manifest is not readable JSON."
            ) from error

        if not isinstance(raw_document, dict) or not isinstance(raw_document.get("images"), list):
            raise ImageManifestError(
                "manifest_shape_invalid", "The image manifest must contain an images list."
            )

        entries: dict[str, _ManifestEntry] = {}
        file_names: set[str] = set()
        for raw_entry in raw_document["images"]:
            entry = _parse_manifest_entry(raw_entry)
            if entry.evidence_id in entries:
                raise ImageManifestError(
                    "duplicate_evidence_id",
                    "The image manifest contains a duplicate evidence ID.",
                    evidence_id=entry.evidence_id,
                )
            if entry.file_name in file_names:
                raise ImageManifestError(
                    "duplicate_file_name",
                    "The image manifest contains a duplicate file name.",
                    file_name=entry.file_name,
                )
            entries[entry.evidence_id] = entry
            file_names.add(entry.file_name)
        return cls(entries=MappingProxyType(entries))


class ManifestImageResolver:
    """A no-network adapter implementing the frozen ``ImageResolver`` port."""

    def __init__(
        self,
        manifest: ImageManifest,
        evidence_root: str | Path,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        max_pixels: int = 16_000_000,
        max_dimension: int = 8_192,
    ) -> None:
        if max_bytes < 1 or max_pixels < 1 or max_dimension < 1:
            raise ValueError("Image limits must be positive.")
        root = _local_path(evidence_root, field="evidence_root")
        try:
            resolved_root = root.resolve(strict=True)
        except FileNotFoundError as error:
            raise ImagePathRejected(
                "safe_root_missing", "The configured evidence root is missing."
            ) from error
        except OSError as error:
            raise ImagePathRejected(
                "safe_root_unreadable", "The configured evidence root is unreadable."
            ) from error
        if not resolved_root.is_dir():
            raise ImagePathRejected(
                "safe_root_not_directory", "The evidence root must be a directory."
            )

        self._manifest = manifest
        self._root = resolved_root
        self._max_bytes = max_bytes
        self._max_pixels = max_pixels
        self._max_dimension = max_dimension

    @classmethod
    def from_manifest_file(
        cls,
        *,
        manifest_path: str | Path,
        evidence_root: str | Path,
        max_bytes: int = 10 * 1024 * 1024,
        max_pixels: int = 16_000_000,
        max_dimension: int = 8_192,
    ) -> ManifestImageResolver:
        return cls(
            ImageManifest.from_file(manifest_path),
            evidence_root,
            max_bytes=max_bytes,
            max_pixels=max_pixels,
            max_dimension=max_dimension,
        )

    def resolve(self, evidence: EvidenceImage) -> ResolvedImage:
        """Return the frozen content-addressed port handle without model bytes."""

        return self.resolve_details(evidence).handle

    def resolve_for_provider(self, evidence: EvidenceImage) -> ProviderImageInput:
        """Return bytes only after every local safety and integrity check passes."""

        return self.resolve_details(evidence).provider_image

    def resolve_details(self, evidence: EvidenceImage) -> ResolvedEvidence:
        """Resolve a registered evidence object into separate trust boundaries."""

        entry = self._entry_for(evidence)
        image_path = self._resolve_registered_path(entry.file_name)
        payload = self._read_validated_bytes(image_path, entry)
        media_type, width, height = _probe_image(payload)

        if media_type != entry.expected_mime:
            raise ImageContentRejected(
                "mime_mismatch",
                "Image bytes do not match the manifest MIME type.",
                expected=entry.expected_mime,
                actual=media_type,
            )
        if (width, height) != (entry.expected_width, entry.expected_height):
            raise ImageContentRejected(
                "dimensions_mismatch",
                "Image dimensions do not match the manifest.",
                expected=[entry.expected_width, entry.expected_height],
                actual=[width, height],
            )
        if width > self._max_dimension or height > self._max_dimension:
            raise ImageContentRejected(
                "dimension_limit_exceeded",
                "Image dimensions exceed the configured limit.",
                width=width,
                height=height,
                max_dimension=self._max_dimension,
            )
        if width * height > self._max_pixels:
            raise ImageContentRejected(
                "pixel_limit_exceeded",
                "Image pixels exceed the configured limit.",
                width=width,
                height=height,
                max_pixels=self._max_pixels,
            )

        content_sha256 = hashlib.sha256(payload).hexdigest()
        provider_image = ProviderImageInput(
            content=payload,
            media_type=media_type,
            content_sha256=content_sha256,
            byte_length=len(payload),
            width=width,
            height=height,
        )
        return ResolvedEvidence(
            handle=ResolvedImage(
                evidence_id=entry.evidence_id,
                media_type=media_type,
                content_sha256=content_sha256,
                byte_length=len(payload),
            ),
            provider_image=provider_image,
            provenance=EvidenceProvenance(
                evidence_id=entry.evidence_id,
                source_message_id=entry.source_message_id,
                source_kind=entry.source_kind,
                competition_reference_path=entry.competition_reference_path,
            ),
        )

    def _entry_for(self, evidence: EvidenceImage) -> _ManifestEntry:
        _require_safe_file_name(evidence.file_name, field="evidence.file_name")
        entry = self._manifest.entries.get(evidence.evidence_id)
        if entry is None:
            raise ImagePathRejected(
                "evidence_id_unregistered",
                "The evidence ID is not registered in the local manifest.",
                evidence_id=evidence.evidence_id,
            )
        if evidence.file_name != entry.file_name:
            raise ImagePathRejected(
                "file_name_not_registered",
                "The evidence file name does not match its manifest entry.",
                evidence_id=evidence.evidence_id,
            )
        if evidence.source_message_id != entry.source_message_id:
            raise ImagePathRejected(
                "source_message_mismatch",
                "The evidence source message does not match its manifest entry.",
                evidence_id=evidence.evidence_id,
            )
        if evidence.source_kind != entry.source_kind:
            raise ImagePathRejected(
                "source_kind_mismatch",
                "The evidence source kind does not match its manifest entry.",
                evidence_id=evidence.evidence_id,
            )
        if evidence.competition_reference_path != entry.competition_reference_path:
            raise ImagePathRejected(
                "competition_reference_mismatch",
                "The original competition reference does not match its manifest entry.",
                evidence_id=evidence.evidence_id,
            )
        return entry

    def _resolve_registered_path(self, file_name: str) -> Path:
        candidate = self._root / file_name
        try:
            resolved_candidate = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            raise ImagePathRejected(
                "missing_file",
                "The registered evidence file is missing.",
                file_name=file_name,
            ) from error
        except OSError as error:
            raise ImagePathRejected(
                "path_unreadable",
                "The registered evidence path cannot be resolved.",
                file_name=file_name,
            ) from error
        if not _is_within(self._root, resolved_candidate):
            raise ImagePathRejected(
                "symlink_outside_root",
                "The registered evidence path resolves outside the configured root.",
                file_name=file_name,
            )
        if not resolved_candidate.is_file():
            raise ImagePathRejected(
                "not_a_regular_file",
                "The registered evidence path is not a file.",
                file_name=file_name,
            )
        return resolved_candidate

    def _read_validated_bytes(self, image_path: Path, entry: _ManifestEntry) -> bytes:
        try:
            with image_path.open("rb") as source:
                payload = source.read(self._max_bytes + 1)
        except OSError as error:
            raise ImageContentRejected(
                "read_failed",
                "The registered evidence file could not be read.",
                evidence_id=entry.evidence_id,
            ) from error
        if len(payload) > self._max_bytes:
            raise ImageContentRejected(
                "file_too_large",
                "The registered evidence file exceeds the configured byte limit.",
                byte_length=len(payload),
                max_bytes=self._max_bytes,
            )

        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if not hmac.compare_digest(actual_sha256, entry.expected_sha256):
            raise ImageContentRejected(
                "sha256_mismatch",
                "The registered evidence bytes do not match the manifest hash.",
                expected_sha256=entry.expected_sha256,
                actual_sha256=actual_sha256,
            )
        if len(payload) != entry.expected_bytes:
            raise ImageContentRejected(
                "byte_length_mismatch",
                "The registered evidence byte length does not match the manifest.",
                expected_bytes=entry.expected_bytes,
                actual_bytes=len(payload),
            )
        return payload


def _parse_manifest_entry(raw_entry: object) -> _ManifestEntry:
    if not isinstance(raw_entry, dict):
        raise ImageManifestError(
            "manifest_entry_invalid", "Each image manifest entry must be an object."
        )

    evidence_id = _required_text(raw_entry, "evidence_id")
    file_name = _required_text(raw_entry, "file_name")
    _require_safe_file_name(file_name, field="manifest.file_name")
    _validate_repo_target(raw_entry.get("repo_target_path"), file_name)
    source_message_id = _required_text(raw_entry, "source_message_id")
    source_kind = _required_text(raw_entry, "source_kind")
    if source_kind not in {
        "TEAM_SYNTHETIC_RECREATION",
        "TEAM_SYNTHETIC_AUGMENTATION",
    }:
        raise ImageManifestError(
            "unsupported_source_kind",
            "The image manifest source kind is not a registered team source type.",
            source_kind=source_kind,
        )
    competition_reference_path = raw_entry.get("competition_reference_path")
    if competition_reference_path is not None and not isinstance(competition_reference_path, str):
        raise ImageManifestError(
            "competition_reference_invalid",
            "The competition reference path must be a string or null.",
        )

    expected_sha256 = _required_text(raw_entry, "sha256").lower()
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_sha256
    ):
        raise ImageManifestError(
            "sha256_invalid", "The image manifest hash must be a SHA-256 hex digest."
        )
    expected_bytes = _positive_int(raw_entry, "bytes")
    expected_mime = _required_text(raw_entry, "mime").lower()
    if expected_mime not in _SUPPORTED_MEDIA_TYPES:
        raise ImageManifestError(
            "unsupported_manifest_mime",
            "The image manifest MIME type is not supported.",
            mime=expected_mime,
        )
    dimensions = raw_entry.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ImageManifestError(
            "dimensions_invalid", "The image manifest dimensions must be an object."
        )
    expected_width = _positive_int(dimensions, "width")
    expected_height = _positive_int(dimensions, "height")
    return _ManifestEntry(
        evidence_id=evidence_id,
        file_name=file_name,
        source_message_id=source_message_id,
        source_kind=source_kind,
        competition_reference_path=competition_reference_path,
        expected_sha256=expected_sha256,
        expected_bytes=expected_bytes,
        expected_mime=expected_mime,
        expected_width=expected_width,
        expected_height=expected_height,
    )


def _required_text(raw_entry: Mapping[str, object], field: str) -> str:
    value = raw_entry.get(field)
    if not isinstance(value, str) or not value:
        raise ImageManifestError(
            "required_text_missing", f"The image manifest field {field} must be text."
        )
    return value


def _positive_int(raw_entry: Mapping[str, object], field: str) -> int:
    value = raw_entry.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ImageManifestError(
            "positive_integer_invalid", f"The image manifest field {field} must be positive."
        )
    return value


def _local_path(value: str | Path, *, field: str) -> Path:
    raw_value = str(value)
    if not raw_value or _looks_like_url(raw_value):
        raise ImageManifestError("remote_path_rejected", f"The {field} must be a local file path.")
    return Path(value)


def _require_safe_file_name(value: str, *, field: str) -> None:
    windows_path = PureWindowsPath(value)
    if (
        not value
        or value != value.strip()
        or _looks_like_url(value)
        or "/" in value
        or "\\" in value
        or windows_path.drive
        or windows_path.is_absolute()
        or value in {".", ".."}
    ):
        raise ImagePathRejected(
            "unsafe_file_name",
            f"The {field} must be a simple local file name.",
        )


def _validate_repo_target(value: object, file_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ImageManifestError(
            "repo_target_missing", "The image manifest repo target path is required."
        )
    normalized = value.replace("\\", "/")
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(normalized)
    if (
        _looks_like_url(value)
        or windows_path.drive
        or windows_path.is_absolute()
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
        or posix_path.name != file_name
    ):
        raise ImageManifestError(
            "unsafe_repo_target",
            "The manifest repo target must be a relative path ending in its registered file name.",
        )


def _looks_like_url(value: str) -> bool:
    return "://" in value or value.lower().startswith("file:")


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _probe_image(payload: bytes) -> tuple[str, int, int]:
    if payload.startswith(_PNG_SIGNATURE):
        width, height = _probe_png(payload)
        return "image/png", width, height
    if payload.startswith(b"\xff\xd8"):
        width, height = _probe_jpeg(payload)
        return "image/jpeg", width, height
    raise ImageContentRejected(
        "unsupported_mime",
        "Evidence bytes are not a supported PNG or JPEG image.",
    )


def _probe_png(payload: bytes) -> tuple[int, int]:
    position = len(_PNG_SIGNATURE)
    width: int | None = None
    height: int | None = None
    bit_depth: int | None = None
    color_type: int | None = None
    interlace: int | None = None
    seen_idat = False
    seen_plte = False
    compressed_chunks: list[bytes] = []

    while position < len(payload):
        if position + 12 > len(payload):
            raise ImageContentRejected("png_truncated", "PNG chunk metadata is truncated.")
        length = struct.unpack(">I", payload[position : position + 4])[0]
        chunk_type = payload[position + 4 : position + 8]
        chunk_end = position + 12 + length
        if chunk_end > len(payload):
            raise ImageContentRejected("png_truncated", "PNG chunk bytes are truncated.")
        chunk_data = payload[position + 8 : position + 8 + length]
        expected_crc = struct.unpack(">I", payload[position + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ImageContentRejected("png_crc_mismatch", "PNG chunk CRC validation failed.")

        if position == len(_PNG_SIGNATURE):
            if chunk_type != b"IHDR" or length != 13:
                raise ImageContentRejected(
                    "png_header_invalid", "PNG must begin with a valid IHDR chunk."
                )
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width < 1 or height < 1:
                raise ImageContentRejected(
                    "png_dimensions_invalid", "PNG dimensions must be positive."
                )
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                raise ImageContentRejected(
                    "png_header_invalid", "PNG header uses unsupported coding values."
                )
            if (
                color_type not in _PNG_ALLOWED_BITS
                or bit_depth not in _PNG_ALLOWED_BITS[color_type]
            ):
                raise ImageContentRejected(
                    "png_header_invalid", "PNG bit depth and color type are invalid."
                )
        elif chunk_type == b"IHDR":
            raise ImageContentRejected(
                "png_header_duplicate", "PNG contains more than one IHDR chunk."
            )
        elif chunk_type == b"PLTE":
            if seen_idat or seen_plte or not chunk_data or len(chunk_data) % 3:
                raise ImageContentRejected("png_palette_invalid", "PNG palette chunk is invalid.")
            seen_plte = True
        elif chunk_type == b"IDAT":
            if width is None:
                raise ImageContentRejected(
                    "png_header_invalid", "PNG image data precedes its header."
                )
            compressed_chunks.append(chunk_data)
            seen_idat = True
        elif chunk_type == b"IEND":
            if length != 0 or not seen_idat or position != len(payload) - 12:
                raise ImageContentRejected("png_end_invalid", "PNG end marker is invalid.")
            if color_type == 3 and not seen_plte:
                raise ImageContentRejected(
                    "png_palette_missing", "Indexed PNG data requires a palette."
                )
            break
        position = chunk_end
    else:
        raise ImageContentRejected("png_end_missing", "PNG is missing its IEND chunk.")

    if (
        width is None
        or height is None
        or bit_depth is None
        or color_type is None
        or interlace is None
    ):
        raise ImageContentRejected("png_header_invalid", "PNG header data is unavailable.")
    compressed = b"".join(compressed_chunks)
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed) + decoder.flush()
    except zlib.error as error:
        raise ImageContentRejected(
            "png_decode_failed", "PNG image data cannot be decompressed."
        ) from error
    if not decoder.eof or decoder.unused_data:
        raise ImageContentRejected(
            "png_decode_failed", "PNG image data is incomplete or has trailing bytes."
        )

    expected_rows = _png_row_lengths(width, height, bit_depth, color_type, interlace)
    expected_length = sum(row_length + 1 for row_length in expected_rows)
    if len(decoded) != expected_length:
        raise ImageContentRejected("png_decode_failed", "PNG scanline length is invalid.")
    offset = 0
    for row_length in expected_rows:
        if decoded[offset] > 4:
            raise ImageContentRejected("png_decode_failed", "PNG uses an invalid scanline filter.")
        offset += row_length + 1
    return width, height


def _png_row_lengths(
    width: int,
    height: int,
    bit_depth: int,
    color_type: int,
    interlace: int,
) -> list[int]:
    channels = _PNG_CHANNELS[color_type]
    if interlace == 0:
        return [_png_row_bytes(width, bit_depth, channels)] * height
    lengths: list[int] = []
    for start_x, start_y, step_x, step_y in _ADAM7_PASSES:
        pass_width = _adam7_length(width, start_x, step_x)
        pass_height = _adam7_length(height, start_y, step_y)
        if pass_width and pass_height:
            lengths.extend([_png_row_bytes(pass_width, bit_depth, channels)] * pass_height)
    return lengths


def _adam7_length(full_length: int, start: int, step: int) -> int:
    if full_length <= start:
        return 0
    return (full_length - start + step - 1) // step


def _png_row_bytes(width: int, bit_depth: int, channels: int) -> int:
    return (width * bit_depth * channels + 7) // 8


def _probe_jpeg(payload: bytes) -> tuple[int, int]:
    position = 2
    width: int | None = None
    height: int | None = None
    saw_start_of_scan = False
    frame_components: dict[int, int] = {}
    quantization_tables: set[int] = set()
    huffman_tables: set[tuple[int, int]] = set()

    while position < len(payload):
        if payload[position] != 0xFF:
            raise ImageContentRejected("jpeg_marker_invalid", "JPEG marker prefix is missing.")
        while position < len(payload) and payload[position] == 0xFF:
            position += 1
        if position >= len(payload):
            raise ImageContentRejected("jpeg_truncated", "JPEG marker is truncated.")
        marker = payload[position]
        position += 1
        if marker == 0xD9:
            if width is None or height is None or not saw_start_of_scan:
                raise ImageContentRejected(
                    "jpeg_end_invalid", "JPEG ended before image data was complete."
                )
            if position != len(payload):
                raise ImageContentRejected(
                    "jpeg_trailing_data", "JPEG contains trailing bytes after EOI."
                )
            return width, height
        if marker == 0x00 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            raise ImageContentRejected(
                "jpeg_marker_invalid", "JPEG marker is invalid outside image data."
            )
        if position + 2 > len(payload):
            raise ImageContentRejected("jpeg_truncated", "JPEG segment length is truncated.")
        segment_length = struct.unpack(">H", payload[position : position + 2])[0]
        if segment_length < 2 or position + segment_length > len(payload):
            raise ImageContentRejected("jpeg_truncated", "JPEG segment is truncated.")
        segment = payload[position + 2 : position + segment_length]
        position += segment_length

        if marker in _JPEG_SOF_MARKERS:
            if len(segment) < 6:
                raise ImageContentRejected("jpeg_frame_invalid", "JPEG frame header is truncated.")
            precision = segment[0]
            height, width = struct.unpack(">HH", segment[1:5])
            component_count = segment[5]
            if precision not in {8, 12} or width < 1 or height < 1:
                raise ImageContentRejected(
                    "jpeg_frame_invalid", "JPEG frame dimensions are invalid."
                )
            if component_count < 1 or len(segment) != 6 + component_count * 3:
                raise ImageContentRejected("jpeg_frame_invalid", "JPEG component data is invalid.")
            frame_components = {}
            for component_offset in range(6, len(segment), 3):
                component_id = segment[component_offset]
                quantization_table_id = segment[component_offset + 2]
                if component_id in frame_components:
                    raise ImageContentRejected(
                        "jpeg_frame_invalid", "JPEG frame component IDs are duplicated."
                    )
                frame_components[component_id] = quantization_table_id
        elif marker == 0xDB:
            _record_jpeg_quantization_tables(segment, quantization_tables)
        elif marker == 0xC4:
            _record_jpeg_huffman_tables(segment, huffman_tables)
        elif marker == 0xDA:
            if width is None or height is None:
                raise ImageContentRejected(
                    "jpeg_frame_missing", "JPEG scan begins before a frame header."
                )
            _validate_jpeg_scan_tables(
                segment,
                frame_components,
                quantization_tables,
                huffman_tables,
            )
            saw_start_of_scan = True
            return _validate_jpeg_entropy(payload, position, width, height)

    raise ImageContentRejected("jpeg_end_missing", "JPEG is missing its EOI marker.")


def _record_jpeg_quantization_tables(
    segment: bytes, defined_tables: set[int]
) -> None:
    position = 0
    while position < len(segment):
        table_specifier = segment[position]
        position += 1
        precision = table_specifier >> 4
        table_id = table_specifier & 0x0F
        if precision not in {0, 1} or table_id > 3:
            raise ImageContentRejected(
                "jpeg_dqt_invalid", "JPEG quantization table selector is invalid."
            )
        value_bytes = 128 if precision == 1 else 64
        if position + value_bytes > len(segment):
            raise ImageContentRejected(
                "jpeg_dqt_invalid", "JPEG quantization table data is truncated."
            )
        position += value_bytes
        defined_tables.add(table_id)
    if not segment:
        raise ImageContentRejected("jpeg_dqt_invalid", "JPEG quantization table data is empty.")


def _record_jpeg_huffman_tables(
    segment: bytes, defined_tables: set[tuple[int, int]]
) -> None:
    position = 0
    while position < len(segment):
        if position + 17 > len(segment):
            raise ImageContentRejected("jpeg_dht_invalid", "JPEG Huffman table is truncated.")
        table_specifier = segment[position]
        table_class = table_specifier >> 4
        table_id = table_specifier & 0x0F
        if table_class not in {0, 1} or table_id > 3:
            raise ImageContentRejected(
                "jpeg_dht_invalid", "JPEG Huffman table selector is invalid."
            )
        code_counts = segment[position + 1 : position + 17]
        symbol_count = sum(code_counts)
        if symbol_count < 1 or symbol_count > 256:
            raise ImageContentRejected("jpeg_dht_invalid", "JPEG Huffman code counts are invalid.")
        table_end = position + 17 + symbol_count
        if table_end > len(segment):
            raise ImageContentRejected("jpeg_dht_invalid", "JPEG Huffman symbols are truncated.")
        defined_tables.add((table_class, table_id))
        position = table_end
    if not segment:
        raise ImageContentRejected("jpeg_dht_invalid", "JPEG Huffman table data is empty.")


def _validate_jpeg_scan_tables(
    segment: bytes,
    frame_components: dict[int, int],
    quantization_tables: set[int],
    huffman_tables: set[tuple[int, int]],
) -> None:
    for component_id, table_id in frame_components.items():
        if table_id not in quantization_tables:
            raise ImageContentRejected(
                "jpeg_dqt_undefined",
                "JPEG frame references an undefined quantization table.",
                component_id=component_id,
                table_id=table_id,
            )
    if len(segment) < 4:
        raise ImageContentRejected("jpeg_scan_invalid", "JPEG scan header is truncated.")
    component_count = segment[0]
    expected_length = 1 + component_count * 2 + 3
    if component_count < 1 or len(segment) != expected_length:
        raise ImageContentRejected("jpeg_scan_invalid", "JPEG scan component data is invalid.")
    seen_components: set[int] = set()
    for component_offset in range(1, 1 + component_count * 2, 2):
        component_id = segment[component_offset]
        table_specifier = segment[component_offset + 1]
        if component_id not in frame_components or component_id in seen_components:
            raise ImageContentRejected(
                "jpeg_scan_invalid", "JPEG scan references an invalid component."
            )
        seen_components.add(component_id)
        dc_table_id = table_specifier >> 4
        ac_table_id = table_specifier & 0x0F
        if (0, dc_table_id) not in huffman_tables:
            raise ImageContentRejected(
                "jpeg_dht_undefined",
                "JPEG scan references an undefined DC Huffman table.",
                component_id=component_id,
                table_class="DC",
                table_id=dc_table_id,
            )
        if (1, ac_table_id) not in huffman_tables:
            raise ImageContentRejected(
                "jpeg_dht_undefined",
                "JPEG scan references an undefined AC Huffman table.",
                component_id=component_id,
                table_class="AC",
                table_id=ac_table_id,
            )


def _validate_jpeg_entropy(
    payload: bytes, position: int, width: int, height: int
) -> tuple[int, int]:
    while position < len(payload):
        if payload[position] != 0xFF:
            position += 1
            continue
        position += 1
        while position < len(payload) and payload[position] == 0xFF:
            position += 1
        if position >= len(payload):
            raise ImageContentRejected("jpeg_truncated", "JPEG entropy data is truncated.")
        marker = payload[position]
        position += 1
        if marker == 0x00 or 0xD0 <= marker <= 0xD7:
            continue
        if marker == 0xD9:
            if len(payload) - position > _MAX_JPEG_TRAILING_BYTES:
                raise ImageContentRejected(
                    "jpeg_trailing_data",
                    "JPEG contains too much trailing data after EOI.",
                    trailing_bytes=len(payload) - position,
                    max_trailing_bytes=_MAX_JPEG_TRAILING_BYTES,
                )
            return width, height
        raise ImageContentRejected(
            "jpeg_entropy_invalid", "JPEG contains an unexpected entropy marker."
        )
    raise ImageContentRejected("jpeg_end_missing", "JPEG entropy data is missing its EOI marker.")
