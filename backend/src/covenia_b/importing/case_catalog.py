"""Load approved case metadata without treating a prefilled CaseInput as facts.

The accepted A-line fixture contains both competition-derived examples and
team-authored augmentations.  This module deliberately extracts only the
directory, augmentation, image, and scope metadata needed to *locate* source
records.  The competition conversation, order, and ticket facts are joined by
``case_assembler`` from the normalized workbook instead of being copied from
the fixture's ready-made ``case_input`` object.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal


class CaseCatalogError(ValueError):
    """Raised when approved catalog inputs cannot be consumed safely."""


class CatalogIntegrityError(CaseCatalogError):
    """Raised when fixture metadata conflicts with the accepted manifest."""


class UnknownCaseReference(CaseCatalogError):
    """Raised when neither a case ID nor an approved display alias resolves."""


CaseSpeaker = Literal["CONSUMER", "AGENT", "SYSTEM"]
MessageSourceKind = Literal["DEMO_AUGMENTATION"]
EvidenceSourceKind = Literal["TEAM_SYNTHETIC_RECREATION", "TEAM_SYNTHETIC_AUGMENTATION"]
ItemRole = Literal["PRIMARY", "GIFT", "BUNDLE_COMPONENT"]


@dataclass(frozen=True, slots=True)
class CatalogMessage:
    """A team-authored message that supplements, but never replaces, source chat."""

    message_id: str
    timestamp: datetime
    speaker: CaseSpeaker
    text: str
    source_kind: MessageSourceKind


@dataclass(frozen=True, slots=True)
class CatalogItem:
    """A declared case item used to validate and enrich an order association."""

    fulfillment_item_id: str
    sku_id: str
    product_name: str
    batch_code: str | None
    item_role: ItemRole


@dataclass(frozen=True, slots=True)
class CatalogEvidenceImage:
    """Approved image mapping metadata; image bytes remain outside this layer."""

    evidence_id: str
    file_name: str
    submitted_at: datetime
    declared_view_type: Literal["PRODUCT_OVERVIEW", "ISSUE_DETAIL", "PACKAGE_CONTEXT", "OTHER"]
    source_kind: EvidenceSourceKind
    source_message_id: str
    competition_reference_path: str | None


@dataclass(frozen=True, slots=True)
class CatalogIssue:
    """The A-line declared scope for a case, not an evidence conclusion."""

    fulfillment_item_id: str
    sku_id: str
    issue_type: Literal["PACKAGE_DAMAGE", "LOGISTICS_STALLED", "ADVERSE_REACTION"]
    affected_component: Literal["BOTTLE", "PUMP", "CAP", "SEAL", "OUTER_PACKAGE", "UNKNOWN"] | None


@dataclass(frozen=True, slots=True)
class CaseDefinition:
    """Directory entry linking a stable case reference to a source session."""

    case_id: str
    display_aliases: tuple[str, ...]
    source_session_id: str
    evaluation_time: datetime
    augmentation_notes: tuple[str, ...]
    augmentation_messages: tuple[CatalogMessage, ...]
    expected_order_id: str
    expected_ticket_ids: tuple[str, ...]
    item_descriptors: tuple[CatalogItem, ...]
    evidence_images: tuple[CatalogEvidenceImage, ...]
    current_issue: CatalogIssue
    policy_requirement_id: str


@dataclass(frozen=True, slots=True)
class CaseCatalog:
    """Data-driven case directory with non-primary display alias support.

    The source-session display aliases originate from the accepted A-line
    manifest.  They are deliberately kept separate from case lookup: an alias
    can collide, so only a source session ID is a primary join key.
    """

    definitions: tuple[CaseDefinition, ...]
    source_session_display_aliases: Mapping[str, str]
    _by_reference: Mapping[str, CaseDefinition] = field(init=False, repr=False)
    _by_session: Mapping[str, tuple[CaseDefinition, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        by_reference: dict[str, CaseDefinition] = {}
        by_session: defaultdict[str, list[CaseDefinition]] = defaultdict(list)
        for definition in self.definitions:
            if not definition.case_id:
                raise CaseCatalogError("case_id cannot be blank")
            references = (definition.case_id, *definition.display_aliases)
            for reference in references:
                if not reference:
                    raise CaseCatalogError("display aliases cannot be blank")
                existing = by_reference.get(reference)
                if existing is not None and existing != definition:
                    raise CaseCatalogError(
                        f"display reference {reference!r} resolves to multiple cases"
                    )
                by_reference[reference] = definition
            by_session[definition.source_session_id].append(definition)

        object.__setattr__(self, "_by_reference", MappingProxyType(dict(by_reference)))
        object.__setattr__(
            self,
            "_by_session",
            MappingProxyType(
                {
                    session_id: tuple(sorted(entries, key=lambda entry: entry.case_id))
                    for session_id, entries in by_session.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "source_session_display_aliases",
            MappingProxyType(dict(self.source_session_display_aliases)),
        )

    @property
    def case_ids(self) -> tuple[str, ...]:
        """Return deterministic canonical IDs; aliases do not create cases."""

        return tuple(sorted(definition.case_id for definition in self.definitions))

    def resolve(self, case_reference: str) -> CaseDefinition:
        """Resolve a canonical case ID or approved display alias."""

        try:
            return self._by_reference[case_reference]
        except KeyError as error:
            raise UnknownCaseReference(f"unknown case reference {case_reference!r}") from error

    def definitions_for_source_session(self, source_session_id: str) -> tuple[CaseDefinition, ...]:
        """Return every catalog case that is grounded in one source session."""

        return self._by_session.get(source_session_id, ())

    def source_sessions_for_display_alias(self, display_alias: str) -> tuple[str, ...]:
        """Return all sessions for an alias without treating it as a primary key."""

        return tuple(
            sorted(
                session_id
                for session_id, alias in self.source_session_display_aliases.items()
                if alias == display_alias
            )
        )

    @classmethod
    def from_accepted_materials(
        cls,
        demo_cases_path: str | Path,
        manifest_path: str | Path,
    ) -> CaseCatalog:
        """Build a catalog from immutable A-line inputs.

        ``demo-cases.json`` is read only for its case directory and
        team-authored augmentations.  Competition messages, order values, and
        ticket values within its prefilled sample are intentionally ignored.
        """

        demo_path = Path(demo_cases_path)
        manifest_path = Path(manifest_path)
        fixtures = _load_json_sequence(demo_path)
        manifest = _load_json_mapping(manifest_path)
        _verify_fixture_hash(demo_path, manifest)

        definitions = tuple(_definition_from_fixture(item) for item in fixtures)
        if not definitions:
            raise CaseCatalogError("accepted demo fixture has no case directory entries")

        aliases = _manifest_aliases(manifest)
        for definition in definitions:
            if definition.source_session_id not in aliases:
                raise CatalogIntegrityError(
                    f"manifest has no display alias for {definition.source_session_id!r}"
                )

        _verify_manifest_provenance(definitions, manifest)
        return cls(
            definitions=definitions,
            source_session_display_aliases=aliases,
        )


def _definition_from_fixture(value: object) -> CaseDefinition:
    fixture = _require_mapping(value, "fixture case")
    case_id = _require_string(fixture.get("demo_case_id"), "demo_case_id")
    display_aliases = _distinct_strings(
        (case_id, _require_string(fixture.get("title"), f"{case_id}.title"))
    )
    # This is metadata extraction, not a direct CaseInput conversion.  The
    # assembler obtains all competition-origin facts from the workbook.
    sample = _require_mapping(fixture.get("case_input"), f"{case_id}.case_input")
    provenance = _require_mapping(sample.get("data_provenance"), f"{case_id}.data_provenance")
    source_session_id = _require_string(
        provenance.get("source_session_id"),
        f"{case_id}.data_provenance.source_session_id",
    )
    notes = tuple(
        _require_string(note, f"{case_id}.augmentation_notes")
        for note in _require_sequence(provenance.get("augmentation_notes"), f"{case_id}.notes")
    )
    evaluation_time = _parse_timestamp(sample.get("evaluation_time"), f"{case_id}.evaluation_time")

    conversation = _require_sequence(sample.get("conversation"), f"{case_id}.conversation")
    augmentation_messages = tuple(
        _catalog_message(message, case_id)
        for message in conversation
        if _require_mapping(message, f"{case_id}.conversation").get("source_kind")
        == "DEMO_AUGMENTATION"
    )

    order = _require_mapping(sample.get("order"), f"{case_id}.order")
    expected_order_id = _require_string(order.get("order_id"), f"{case_id}.order.order_id")
    item_descriptors = tuple(
        _catalog_item(item, case_id)
        for item in _require_sequence(order.get("items"), f"{case_id}.order.items")
    )
    if not item_descriptors:
        raise CaseCatalogError(f"{case_id} has no item descriptors")

    expected_ticket_ids = tuple(
        _require_string(
            _require_mapping(ticket, f"{case_id}.service_tickets").get("ticket_id"),
            f"{case_id}.service_tickets.ticket_id",
        )
        for ticket in _require_sequence(sample.get("service_tickets"), f"{case_id}.service_tickets")
    )
    evidence_images = tuple(
        _catalog_evidence(image, case_id)
        for image in _require_sequence(sample.get("evidence_images"), f"{case_id}.evidence_images")
    )
    issue = _catalog_issue(sample.get("current_issue"), case_id)

    return CaseDefinition(
        case_id=case_id,
        display_aliases=display_aliases,
        source_session_id=source_session_id,
        evaluation_time=evaluation_time,
        augmentation_notes=notes,
        augmentation_messages=augmentation_messages,
        expected_order_id=expected_order_id,
        expected_ticket_ids=_distinct_strings(expected_ticket_ids),
        item_descriptors=item_descriptors,
        evidence_images=evidence_images,
        current_issue=issue,
        policy_requirement_id=_require_string(
            sample.get("policy_requirement_id"),
            f"{case_id}.policy_requirement_id",
        ),
    )


def _catalog_message(value: object, case_id: str) -> CatalogMessage:
    message = _require_mapping(value, f"{case_id}.augmentation_message")
    source_kind = _require_string(message.get("source_kind"), f"{case_id}.message.source_kind")
    if source_kind != "DEMO_AUGMENTATION":
        raise CaseCatalogError(f"{case_id} contains a non-augmentation catalog message")
    speaker = _require_string(message.get("speaker"), f"{case_id}.message.speaker")
    if speaker not in {"CONSUMER", "AGENT", "SYSTEM"}:
        raise CaseCatalogError(f"{case_id} has unsupported speaker {speaker!r}")
    return CatalogMessage(
        message_id=_require_string(message.get("message_id"), f"{case_id}.message_id"),
        timestamp=_parse_timestamp(message.get("timestamp"), f"{case_id}.message.timestamp"),
        speaker=speaker,
        text=_require_string(message.get("text"), f"{case_id}.message.text"),
        source_kind="DEMO_AUGMENTATION",
    )


def _catalog_item(value: object, case_id: str) -> CatalogItem:
    item = _require_mapping(value, f"{case_id}.item")
    role = _require_string(item.get("item_role"), f"{case_id}.item.item_role")
    if role not in {"PRIMARY", "GIFT", "BUNDLE_COMPONENT"}:
        raise CaseCatalogError(f"{case_id} has unsupported item role {role!r}")
    batch_code = item.get("batch_code")
    if batch_code is not None:
        batch_code = _require_string(batch_code, f"{case_id}.item.batch_code")
    return CatalogItem(
        fulfillment_item_id=_require_string(
            item.get("fulfillment_item_id"),
            f"{case_id}.item.fulfillment_item_id",
        ),
        sku_id=_require_string(item.get("sku_id"), f"{case_id}.item.sku_id"),
        product_name=_require_string(item.get("product_name"), f"{case_id}.item.product_name"),
        batch_code=batch_code,
        item_role=role,
    )


def _catalog_evidence(value: object, case_id: str) -> CatalogEvidenceImage:
    image = _require_mapping(value, f"{case_id}.evidence_image")
    view_type = _require_string(image.get("declared_view_type"), f"{case_id}.view_type")
    allowed_views = {"PRODUCT_OVERVIEW", "ISSUE_DETAIL", "PACKAGE_CONTEXT", "OTHER"}
    if view_type not in allowed_views:
        raise CaseCatalogError(f"{case_id} has unsupported image view type {view_type!r}")
    source_kind = _require_string(image.get("source_kind"), f"{case_id}.image.source_kind")
    allowed_sources = {"TEAM_SYNTHETIC_RECREATION", "TEAM_SYNTHETIC_AUGMENTATION"}
    if source_kind not in allowed_sources:
        raise CaseCatalogError(f"{case_id} has unsupported image source kind {source_kind!r}")
    reference_path = image.get("competition_reference_path")
    if reference_path is not None:
        reference_path = _require_string(reference_path, f"{case_id}.image.reference_path")
    return CatalogEvidenceImage(
        evidence_id=_require_string(image.get("evidence_id"), f"{case_id}.image.evidence_id"),
        file_name=_require_string(image.get("file_name"), f"{case_id}.image.file_name"),
        submitted_at=_parse_timestamp(image.get("submitted_at"), f"{case_id}.image.submitted_at"),
        declared_view_type=view_type,
        source_kind=source_kind,
        source_message_id=_require_string(
            image.get("source_message_id"),
            f"{case_id}.image.source_message_id",
        ),
        competition_reference_path=reference_path,
    )


def _catalog_issue(value: object, case_id: str) -> CatalogIssue:
    issue = _require_mapping(value, f"{case_id}.current_issue")
    issue_type = _require_string(issue.get("issue_type"), f"{case_id}.issue_type")
    allowed_issues = {"PACKAGE_DAMAGE", "LOGISTICS_STALLED", "ADVERSE_REACTION"}
    if issue_type not in allowed_issues:
        raise CaseCatalogError(f"{case_id} has unsupported issue type {issue_type!r}")
    affected_component = issue.get("affected_component")
    allowed_components = {"BOTTLE", "PUMP", "CAP", "SEAL", "OUTER_PACKAGE", "UNKNOWN"}
    if affected_component is not None:
        affected_component = _require_string(
            affected_component,
            f"{case_id}.affected_component",
        )
        if affected_component not in allowed_components:
            raise CaseCatalogError(
                f"{case_id} has unsupported affected component {affected_component!r}"
            )
    return CatalogIssue(
        fulfillment_item_id=_require_string(
            issue.get("fulfillment_item_id"),
            f"{case_id}.issue.fulfillment_item_id",
        ),
        sku_id=_require_string(issue.get("sku_id"), f"{case_id}.issue.sku_id"),
        issue_type=issue_type,
        affected_component=affected_component,
    )


def _verify_fixture_hash(demo_path: Path, manifest: Mapping[str, object]) -> None:
    fixtures = _require_mapping(manifest.get("fixtures"), "manifest.fixtures")
    corrected = _require_sequence(fixtures.get("corrected"), "manifest.fixtures.corrected")
    expected = next(
        (
            _require_mapping(entry, "manifest.fixtures.corrected")
            for entry in corrected
            if _require_mapping(entry, "manifest.fixtures.corrected").get("path")
            == f"fixtures/{demo_path.name}"
        ),
        None,
    )
    if expected is None:
        raise CatalogIntegrityError(f"manifest has no corrected-hash entry for {demo_path.name}")
    expected_digest = _require_string(expected.get("sha256"), "manifest fixture sha256")
    # The accepted value is a raw Git-blob digest.  A Windows checkout may
    # materialize the same text blob with CRLF line endings, so hash the
    # canonical LF bytes rather than rejecting an otherwise unchanged input.
    canonical_blob_bytes = demo_path.read_bytes().replace(b"\r\n", b"\n")
    actual_digest = hashlib.sha256(canonical_blob_bytes).hexdigest().upper()
    if actual_digest != expected_digest:
        raise CatalogIntegrityError(
            f"accepted fixture hash mismatch for {demo_path.name}: "
            f"{actual_digest} != {expected_digest}"
        )


def _manifest_aliases(manifest: Mapping[str, object]) -> Mapping[str, str]:
    aliases = _require_mapping(manifest.get("alias_to_session"), "manifest.alias_to_session")
    mapping = _require_mapping(aliases.get("mapping"), "manifest.alias_to_session.mapping")
    return {
        _require_string(session_id, "manifest session_id"): _require_string(
            alias,
            f"manifest display alias for {session_id}",
        )
        for session_id, alias in mapping.items()
    }


def _verify_manifest_provenance(
    definitions: Sequence[CaseDefinition],
    manifest: Mapping[str, object],
) -> None:
    provenance = _require_mapping(manifest.get("message_provenance"), "manifest.message_provenance")
    for definition in definitions:
        manifest_messages = provenance.get(definition.case_id)
        if manifest_messages is None:
            continue
        expected_messages = tuple(
            _catalog_message(message, definition.case_id)
            for message in _require_sequence(manifest_messages, definition.case_id)
            if _require_mapping(message, definition.case_id).get("source_kind")
            == "DEMO_AUGMENTATION"
        )
        if expected_messages != definition.augmentation_messages:
            raise CatalogIntegrityError(
                f"{definition.case_id} augmentation messages differ from accepted manifest"
            )

    timeline = _require_mapping(manifest.get("hero_timeline"), "manifest.hero_timeline")
    second_contact = _parse_timestamp(timeline.get("second_contact"), "manifest.second_contact")
    evaluation_time = _parse_timestamp(timeline.get("evaluation_time"), "manifest.evaluation_time")
    matches_freeze = any(
        definition.evaluation_time == evaluation_time
        and any(message.timestamp == second_contact for message in definition.augmentation_messages)
        for definition in definitions
    )
    if not matches_freeze:
        raise CatalogIntegrityError("no catalog case matches the accepted 09:32/09:40 freeze")

    evidence_mapping = _require_mapping(
        manifest.get("evidence_mapping"), "manifest.evidence_mapping"
    )
    manifest_images = _require_sequence(
        evidence_mapping.get("images"), "manifest.evidence_mapping.images"
    )
    manifest_names = {
        _require_string(
            _require_mapping(image, "manifest.evidence_mapping.image").get("file_name"),
            "manifest evidence file_name",
        )
        for image in manifest_images
    }
    catalog_names = {
        image.file_name for definition in definitions for image in definition.evidence_images
    }
    if not manifest_names.issubset(catalog_names):
        raise CatalogIntegrityError("catalog omits an approved evidence mapping")


def _load_json_mapping(path: Path) -> Mapping[str, object]:
    try:
        return _require_mapping(json.loads(path.read_text(encoding="utf-8")), str(path))
    except OSError as error:
        raise CaseCatalogError(f"unable to read {path}") from error
    except json.JSONDecodeError as error:
        raise CaseCatalogError(f"invalid JSON in {path}") from error


def _load_json_sequence(path: Path) -> Sequence[object]:
    try:
        return _require_sequence(json.loads(path.read_text(encoding="utf-8")), str(path))
    except OSError as error:
        raise CaseCatalogError(f"unable to read {path}") from error
    except json.JSONDecodeError as error:
        raise CaseCatalogError(f"invalid JSON in {path}") from error


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CaseCatalogError(f"{label} must be an object")
    return value


def _require_sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise CaseCatalogError(f"{label} must be an array")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaseCatalogError(f"{label} must be a non-empty string")
    return value


def _parse_timestamp(value: object, label: str) -> datetime:
    rendered = _require_string(value, label)
    try:
        timestamp = datetime.fromisoformat(rendered)
    except ValueError as error:
        raise CaseCatalogError(f"{label} must be RFC 3339") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise CaseCatalogError(f"{label} must have an offset")
    return timestamp


def _distinct_strings(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
