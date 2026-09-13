"""Assemble traceable CaseInput payloads from normalized source records.

Case IDs select a catalog entry.  They never select a conclusion: all
competition facts are joined through the source session, then checked against
the declared order and ticket identifiers before a schema-valid CaseInput is
emitted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from covenia_b.domain.validation import validate_contract_payload
from covenia_b.importing.case_catalog import (
    CaseCatalog,
    CaseDefinition,
    CatalogEvidenceImage,
    CatalogMessage,
)
from covenia_b.importing.normalization import (
    NormalizedDataset,
    NormalizedRecord,
    normalize_workbook,
)
from covenia_b.importing.workbook import CompetitionWorkbook


class CaseAssemblyError(ValueError):
    """Base class for safe CaseInput assembly failures."""


class CaseAssociationError(CaseAssemblyError):
    """Raised when source-session, order, or ticket relations disagree."""


class CaseSourceError(CaseAssemblyError):
    """Raised when a required source record is malformed rather than absent."""


@dataclass(frozen=True, slots=True)
class ImportDiagnostic:
    """A non-fabricating explanation for why an input cannot become P0."""

    code: str
    source_session_id: str
    detail: str
    case_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        result = {
            "code": self.code,
            "source_session_id": self.source_session_id,
            "detail": self.detail,
        }
        if self.case_id is not None:
            result["case_id"] = self.case_id
        return result


@dataclass(frozen=True, slots=True)
class ImportabilityDiagnostic:
    """Dataset-level diagnostic; it intentionally is not a generated CaseInput."""

    source_session_id: str
    catalog_case_ids: tuple[str, ...]
    diagnostic_codes: tuple[str, ...]
    p0_ready: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "source_session_id": self.source_session_id,
            "catalog_case_ids": list(self.catalog_case_ids),
            "diagnostic_codes": list(self.diagnostic_codes),
            "p0_ready": self.p0_ready,
        }


@dataclass(frozen=True, slots=True)
class CaseAssembly:
    """One assembled payload or an explicit diagnostic with its join trace."""

    requested_case_reference: str
    case_id: str
    source_session_id: str
    status: Literal["ASSEMBLED", "DIAGNOSTIC"]
    case_input: Mapping[str, object] | None
    diagnostics: tuple[ImportDiagnostic, ...]
    association_trace: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CaseAssembler:
    """Join BATCH-05 normalized records with A-line directory metadata."""

    dataset: NormalizedDataset
    catalog: CaseCatalog

    @classmethod
    def from_paths(
        cls,
        workbook_path: str | Path,
        demo_cases_path: str | Path,
        manifest_path: str | Path,
    ) -> CaseAssembler:
        """Load the normalized competition dataset and accepted case catalog."""

        dataset = normalize_workbook(CompetitionWorkbook(workbook_path))
        catalog = CaseCatalog.from_accepted_materials(demo_cases_path, manifest_path)
        return cls(dataset=dataset, catalog=catalog)

    def assemble(self, case_reference: str) -> CaseAssembly:
        """Build one CaseInput from data joins, or return an import diagnostic."""

        definition = self.catalog.resolve(case_reference)
        source_session_id = definition.source_session_id
        evaluation_time = definition.evaluation_time
        orders_by_id = _unique_index(self.dataset.orders, "order_id", "order")
        tickets_by_id = _unique_index(self.dataset.tickets, "ticket_id", "ticket")

        source_messages = _records_for_session(self.dataset.messages, source_session_id)
        visible_messages, future_source_messages = _before_or_at(
            source_messages,
            "sent_at",
            evaluation_time,
        )
        session_orders = _records_for_session(self.dataset.orders, source_session_id)
        session_tickets = _records_for_session(self.dataset.tickets, source_session_id)
        visible_tickets, future_tickets = _before_or_at(
            session_tickets,
            "created_at",
            evaluation_time,
        )
        visible_augmentations = tuple(
            message
            for message in definition.augmentation_messages
            if message.timestamp <= evaluation_time
        )
        future_augmentations = tuple(
            message
            for message in definition.augmentation_messages
            if message.timestamp > evaluation_time
        )
        visible_images = tuple(
            image for image in definition.evidence_images if image.submitted_at <= evaluation_time
        )
        future_images = tuple(
            image for image in definition.evidence_images if image.submitted_at > evaluation_time
        )

        diagnostics: list[ImportDiagnostic] = []
        if not visible_messages:
            diagnostics.append(
                ImportDiagnostic(
                    code="MISSING_CONVERSATION",
                    source_session_id=source_session_id,
                    case_id=definition.case_id,
                    detail="no competition chat message exists at or before evaluation_time",
                )
            )
        if not visible_images:
            diagnostics.append(
                ImportDiagnostic(
                    code="MISSING_EVIDENCE_IMAGES",
                    source_session_id=source_session_id,
                    case_id=definition.case_id,
                    detail="no approved image mapping exists at or before evaluation_time",
                )
            )

        expected_order = orders_by_id.get(definition.expected_order_id)
        if expected_order is None:
            diagnostics.append(
                ImportDiagnostic(
                    code="MISSING_ORDER",
                    source_session_id=source_session_id,
                    case_id=definition.case_id,
                    detail="catalog order_id is absent from the normalized source dataset",
                )
            )
        else:
            expected_order_session = _identifier(expected_order, "session_id")
            if expected_order_session != source_session_id:
                raise CaseAssociationError(
                    "catalog order_id resolves to a different source session: "
                    f"{definition.expected_order_id!r} -> {expected_order_session!r}"
                )
            if expected_order not in session_orders:
                raise CaseAssociationError(
                    f"session-first order join omitted {definition.expected_order_id!r}"
                )

        for ticket_id in definition.expected_ticket_ids:
            ticket = tickets_by_id.get(ticket_id)
            if ticket is None:
                diagnostics.append(
                    ImportDiagnostic(
                        code="MISSING_REQUIRED_TICKET",
                        source_session_id=source_session_id,
                        case_id=definition.case_id,
                        detail=f"catalog ticket_id {ticket_id!r} is absent from the source dataset",
                    )
                )
                continue
            ticket_session = _identifier(ticket, "session_id")
            ticket_order = _identifier(ticket, "order_id")
            if ticket_session != source_session_id or ticket_order != definition.expected_order_id:
                raise CaseAssociationError(
                    "catalog ticket_id does not preserve the source session/order relation: "
                    f"{ticket_id!r}"
                )
            if _record_timestamp(ticket, "created_at") > evaluation_time:
                diagnostics.append(
                    ImportDiagnostic(
                        code="REQUIRED_TICKET_AFTER_EVALUATION",
                        source_session_id=source_session_id,
                        case_id=definition.case_id,
                        detail=f"catalog ticket_id {ticket_id!r} only exists after evaluation_time",
                    )
                )

        _validate_visible_message_links(
            visible_messages,
            source_session_id,
            orders_by_id,
            tickets_by_id,
        )
        _validate_visible_ticket_links(visible_tickets, source_session_id, orders_by_id)

        if diagnostics:
            trace = _partial_trace(
                definition,
                case_reference,
                visible_messages,
                expected_order,
                visible_tickets,
                diagnostics,
                future_source_messages,
                future_augmentations,
                future_tickets,
                future_images,
            )
            return CaseAssembly(
                requested_case_reference=case_reference,
                case_id=definition.case_id,
                source_session_id=source_session_id,
                status="DIAGNOSTIC",
                case_input=None,
                diagnostics=tuple(diagnostics),
                association_trace=trace,
            )

        assert expected_order is not None
        target_tickets = tuple(
            ticket
            for ticket in visible_tickets
            if _identifier(ticket, "order_id") == definition.expected_order_id
        )
        conversation = _build_conversation(visible_messages, visible_augmentations)
        order, item_trace = _build_order(definition, expected_order)
        tickets, ticket_completion_after_evaluation = _build_tickets(
            target_tickets,
            evaluation_time,
        )
        _validate_recreated_images(visible_images, visible_messages)
        case_input = _build_case_input(definition, conversation, order, tickets, visible_images)
        validate_contract_payload("case-input.schema.json", case_input)
        trace = _success_trace(
            definition,
            case_reference,
            visible_messages,
            expected_order,
            target_tickets,
            visible_augmentations,
            visible_images,
            item_trace,
            future_source_messages,
            future_augmentations,
            future_tickets,
            future_images,
            ticket_completion_after_evaluation,
        )
        return CaseAssembly(
            requested_case_reference=case_reference,
            case_id=definition.case_id,
            source_session_id=source_session_id,
            status="ASSEMBLED",
            case_input=case_input,
            diagnostics=(),
            association_trace=trace,
        )

    def diagnose_importability(self) -> tuple[ImportabilityDiagnostic, ...]:
        """Report why source sessions do or do not form a P0 CaseInput.

        This intentionally examines all 138 imported sessions without inventing
        catalog records, business objects, images, or case scenarios for the
        ones that the approved directory does not identify.
        """

        session_ids = sorted(
            {_identifier(message, "session_id") for message in self.dataset.messages}
        )
        result: list[ImportabilityDiagnostic] = []
        for session_id in session_ids:
            messages = _records_for_session(self.dataset.messages, session_id)
            orders = _records_for_session(self.dataset.orders, session_id)
            definitions = self.catalog.definitions_for_source_session(session_id)
            codes: list[str] = []
            if not orders:
                codes.append("MISSING_ORDER")
            if not any(_optional_text(message.fields.get("image_path")) for message in messages):
                codes.append("MISSING_IMAGE_REFERENCE")
            if not definitions:
                codes.append("NO_CASE_CATALOG_ENTRY")
            elif not any(definition.evidence_images for definition in definitions):
                codes.append("MISSING_EVIDENCE_MAPPING")
            result.append(
                ImportabilityDiagnostic(
                    source_session_id=session_id,
                    catalog_case_ids=tuple(definition.case_id for definition in definitions),
                    diagnostic_codes=tuple(codes),
                    p0_ready=not codes,
                )
            )
        return tuple(result)

    def write_redacted_artifacts(
        self,
        output_dir: str | Path,
        case_references: Sequence[str] | None = None,
    ) -> Mapping[str, Path]:
        """Write deterministic, redacted implementation artifacts only."""

        references = tuple(case_references or self.catalog.case_ids)
        assemblies = tuple(self.assemble(reference) for reference in references)
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        case_input_path = output / "case-input.redacted.json"
        trace_path = output / "association-trace.json"
        case_payload = {
            "schema_version": "covenia-b-case-input-redacted-v1",
            "case_inputs": [
                {
                    "case_id": assembly.case_id,
                    "source_session_id": assembly.source_session_id,
                    "status": assembly.status,
                    "case_input": (
                        redact_case_input(assembly.case_input)
                        if assembly.case_input is not None
                        else None
                    ),
                    "diagnostics": [diagnostic.as_dict() for diagnostic in assembly.diagnostics],
                }
                for assembly in assemblies
            ],
        }
        trace_payload = {
            "schema_version": "covenia-b-association-trace-v1",
            "cases": [dict(assembly.association_trace) for assembly in assemblies],
            "dataset_importability": [
                diagnostic.as_dict() for diagnostic in self.diagnose_importability()
            ],
        }
        _write_json(case_input_path, case_payload)
        _write_json(trace_path, trace_payload)
        return {"case_input": case_input_path, "association_trace": trace_path}


def redact_case_input(case_input: Mapping[str, object]) -> dict[str, object]:
    """Return a contract-valid report sample without raw conversation text."""

    redacted = json.loads(json.dumps(case_input))
    for message in redacted["conversation"]:
        message["text"] = f"[REDACTED {message['source_kind']} MESSAGE]"
    validate_contract_payload("case-input.schema.json", redacted)
    return redacted


def _unique_index(
    records: Sequence[NormalizedRecord],
    field_name: str,
    record_kind: str,
) -> Mapping[str, NormalizedRecord]:
    index: dict[str, NormalizedRecord] = {}
    for record in records:
        identifier = _identifier(record, field_name)
        if identifier in index:
            raise CaseAssociationError(f"duplicate {record_kind} {field_name} {identifier!r}")
        index[identifier] = record
    return index


def _records_for_session(
    records: Sequence[NormalizedRecord],
    source_session_id: str,
) -> tuple[NormalizedRecord, ...]:
    return tuple(
        record for record in records if _identifier(record, "session_id") == source_session_id
    )


def _before_or_at(
    records: Sequence[NormalizedRecord],
    field_name: str,
    evaluation_time: datetime,
) -> tuple[tuple[NormalizedRecord, ...], tuple[NormalizedRecord, ...]]:
    visible: list[NormalizedRecord] = []
    future: list[NormalizedRecord] = []
    for record in records:
        if _record_timestamp(record, field_name) <= evaluation_time:
            visible.append(record)
        else:
            future.append(record)
    return tuple(visible), tuple(future)


def _validate_visible_message_links(
    messages: Sequence[NormalizedRecord],
    source_session_id: str,
    orders_by_id: Mapping[str, NormalizedRecord],
    tickets_by_id: Mapping[str, NormalizedRecord],
) -> None:
    for message in messages:
        order_id = _optional_text(message.fields.get("order_id"))
        if order_id is not None:
            order = orders_by_id.get(order_id)
            if order is None:
                message_id = _identifier(message, "message_id")
                raise CaseAssociationError(
                    f"message {message_id!r} references missing order {order_id!r}"
                )
            if _identifier(order, "session_id") != source_session_id:
                message_id = _identifier(message, "message_id")
                raise CaseAssociationError(
                    f"message {message_id!r} has a reversed order/session link"
                )
        ticket_id = _optional_text(message.fields.get("ticket_id"))
        if ticket_id is not None:
            ticket = tickets_by_id.get(ticket_id)
            if ticket is None:
                message_id = _identifier(message, "message_id")
                raise CaseAssociationError(
                    f"message {message_id!r} references missing ticket {ticket_id!r}"
                )
            if _identifier(ticket, "session_id") != source_session_id:
                message_id = _identifier(message, "message_id")
                raise CaseAssociationError(
                    f"message {message_id!r} has a reversed ticket/session link"
                )


def _validate_visible_ticket_links(
    tickets: Sequence[NormalizedRecord],
    source_session_id: str,
    orders_by_id: Mapping[str, NormalizedRecord],
) -> None:
    for ticket in tickets:
        order_id = _identifier(ticket, "order_id")
        order = orders_by_id.get(order_id)
        if order is None:
            raise CaseAssociationError(
                f"ticket {_identifier(ticket, 'ticket_id')!r} references missing order {order_id!r}"
            )
        if _identifier(order, "session_id") != source_session_id:
            raise CaseAssociationError(
                f"ticket {_identifier(ticket, 'ticket_id')!r} has a reversed order/session link"
            )


def _build_conversation(
    source_messages: Sequence[NormalizedRecord],
    augmentations: Sequence[CatalogMessage],
) -> list[dict[str, str]]:
    items: list[tuple[datetime, int, str, dict[str, str]]] = []
    seen_ids: set[str] = set()
    for message in source_messages:
        message_id = _identifier(message, "message_id")
        text = _optional_text(message.fields.get("message_text"))
        if text is None:
            raise CaseSourceError(f"source message {message_id!r} has no message_text")
        seen_ids.add(message_id)
        items.append(
            (
                _record_timestamp(message, "sent_at"),
                int(message.fields.get("message_sequence", 0)),
                message_id,
                {
                    "message_id": message_id,
                    "timestamp": _record_timestamp(message, "sent_at").isoformat(),
                    "speaker": _speaker_for_source_message(message),
                    "text": text,
                    "source_kind": "COMPETITION_MOCK",
                },
            )
        )
    for augmentation in augmentations:
        message_id = augmentation.message_id
        if message_id in seen_ids:
            raise CaseAssociationError(f"duplicate source/augmentation message_id {message_id!r}")
        seen_ids.add(message_id)
        items.append(
            (
                augmentation.timestamp,
                1_000_000,
                message_id,
                {
                    "message_id": message_id,
                    "timestamp": augmentation.timestamp.isoformat(),
                    "speaker": augmentation.speaker,
                    "text": augmentation.text,
                    "source_kind": augmentation.source_kind,
                },
            )
        )
    return [payload for _, _, _, payload in sorted(items)]


def _speaker_for_source_message(
    message: NormalizedRecord,
) -> Literal["CONSUMER", "AGENT", "SYSTEM"]:
    if message.fields.get("is_target_buyer_message") is True:
        return "CONSUMER"
    role = _optional_text(message.fields.get("role")) or ""
    if role.casefold() == "system" or role == "系统消息":
        return "SYSTEM"
    return "AGENT"


def _build_order(
    definition: CaseDefinition,
    source_order: NormalizedRecord,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    order_id = _identifier(source_order, "order_id")
    sku_id = _identifier(source_order, "product_sku")
    product_name = _required_text(
        source_order.fields.get("product_name"),
        "source order product_name",
    )
    primary_items = [
        item
        for item in definition.item_descriptors
        if item.item_role == "PRIMARY" and item.sku_id == sku_id
    ]
    if len(primary_items) != 1:
        raise CaseAssociationError(
            f"catalog must declare exactly one primary item for source SKU {sku_id!r}"
        )
    primary = primary_items[0]
    if primary.product_name != product_name:
        raise CaseAssociationError("catalog primary product_name does not match source order")
    if (
        definition.current_issue.fulfillment_item_id != primary.fulfillment_item_id
        or definition.current_issue.sku_id != primary.sku_id
    ):
        raise CaseAssociationError("declared issue scope does not match the source primary item")

    output_items: list[dict[str, object]] = [
        {
            "fulfillment_item_id": primary.fulfillment_item_id,
            "sku_id": sku_id,
            "product_name": product_name,
            "batch_code": primary.batch_code,
            "item_role": "PRIMARY",
        }
    ]
    trace_items: list[dict[str, object]] = [
        {
            "fulfillment_item_id": primary.fulfillment_item_id,
            "sku_id": sku_id,
            "item_role": "PRIMARY",
            "source_kind": "COMPETITION_MOCK",
            "source_sheet": source_order.source_sheet,
            "source_row": source_order.source_row,
            "source_coordinates": {
                "order_id": source_order.source_coordinates["order_id"],
                "product_sku": source_order.source_coordinates["product_sku"],
                "product_name": source_order.source_coordinates["product_name"],
            },
        }
    ]
    source_gift = _optional_text(source_order.fields.get("gift"))
    for item in definition.item_descriptors:
        if item is primary:
            continue
        if item.item_role != "GIFT":
            raise CaseSourceError(
                f"catalog item role {item.item_role!r} has no source-backed assembly rule"
            )
        if source_gift != item.product_name:
            raise CaseAssociationError("catalog gift descriptor does not match source order gift")
        output_items.append(
            {
                "fulfillment_item_id": item.fulfillment_item_id,
                "sku_id": item.sku_id,
                "product_name": item.product_name,
                "batch_code": item.batch_code,
                "item_role": "GIFT",
            }
        )
        trace_items.append(
            {
                "fulfillment_item_id": item.fulfillment_item_id,
                "sku_id": item.sku_id,
                "item_role": "GIFT",
                "source_kind": "DEMO_AUGMENTATION",
                "source_sheet": source_order.source_sheet,
                "source_row": source_order.source_row,
                "source_coordinates": {"gift": source_order.source_coordinates["gift"]},
            }
        )

    return (
        {
            "order_id": order_id,
            "channel": "TIANCHI_MOCK_QIANNIU",
            "original_logistics_number": _required_text(
                source_order.fields.get("tracking_id"),
                "source order tracking_id",
            ),
            "items": output_items,
        },
        trace_items,
    )


def _build_tickets(
    tickets: Sequence[NormalizedRecord],
    evaluation_time: datetime,
) -> tuple[list[dict[str, object]], int]:
    category_to_type = {
        "REPLACEMENT_EXCHANGE": "REPLACEMENT",
        "OFFLINE_PAYMENT": "OFFLINE_PAYMENT",
        "LOGISTICS": "LOGISTICS",
        "ADVERSE_REACTION": "ADVERSE_REACTION",
        "AFTER_SALES_RETURN": "RETURN",
    }
    output: list[dict[str, object]] = []
    completion_after_evaluation = 0
    for ticket in sorted(
        tickets,
        key=lambda record: (
            _record_timestamp(record, "created_at"),
            _identifier(record, "ticket_id"),
        ),
    ):
        try:
            ticket_type = category_to_type[ticket.ticket_category or ""]
        except KeyError as error:
            raise CaseSourceError(
                f"unsupported source ticket category {ticket.ticket_category!r}"
            ) from error
        completed_at = ticket.fields.get("completed_at")
        if completed_at is not None:
            completed_at = _record_timestamp(ticket, "completed_at")
            if completed_at > evaluation_time:
                completion_after_evaluation += 1
                completed_at = None
        output.append(
            {
                "ticket_id": _identifier(ticket, "ticket_id"),
                "ticket_type": ticket_type,
                "status": _required_text(ticket.fields.get("ticket_status"), "ticket_status"),
                "assignee_id": _required_text(ticket.fields.get("handler_id"), "handler_id"),
                "executor_name": _optional_text(ticket.fields.get("fulfillment_warehouse")),
                "replacement_logistics_number": _optional_text(
                    ticket.fields.get("replacement_tracking_id")
                ),
                "created_at": _record_timestamp(ticket, "created_at").isoformat(),
                "completed_at": completed_at.isoformat() if completed_at is not None else None,
                "source_sheet": ticket.source_sheet,
            }
        )
    return output, completion_after_evaluation


def _validate_recreated_images(
    images: Sequence[CatalogEvidenceImage],
    source_messages: Sequence[NormalizedRecord],
) -> None:
    source_by_id = {_identifier(message, "message_id"): message for message in source_messages}
    for image in images:
        if image.competition_reference_path is None:
            continue
        source_message = source_by_id.get(image.source_message_id)
        if source_message is None:
            raise CaseAssociationError(
                f"recreated image {image.evidence_id!r} has no source message association"
            )
        if source_message.fields.get("image_path") != image.competition_reference_path:
            raise CaseAssociationError(
                f"recreated image {image.evidence_id!r} disagrees with source image path"
            )


def _build_case_input(
    definition: CaseDefinition,
    conversation: list[dict[str, str]],
    order: dict[str, object],
    tickets: list[dict[str, object]],
    images: Sequence[CatalogEvidenceImage],
) -> dict[str, object]:
    issue: dict[str, object] = {
        "fulfillment_item_id": definition.current_issue.fulfillment_item_id,
        "sku_id": definition.current_issue.sku_id,
        "issue_type": definition.current_issue.issue_type,
    }
    if definition.current_issue.affected_component is not None:
        issue["affected_component"] = definition.current_issue.affected_component
    return {
        "case_id": definition.case_id,
        "data_provenance": {
            "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
            "source_session_id": definition.source_session_id,
            "augmentation_notes": list(definition.augmentation_notes),
        },
        "evaluation_time": definition.evaluation_time.isoformat(),
        "conversation": conversation,
        "order": order,
        "service_tickets": tickets,
        "evidence_images": [
            {
                "evidence_id": image.evidence_id,
                "file_name": image.file_name,
                "submitted_at": image.submitted_at.isoformat(),
                "declared_view_type": image.declared_view_type,
                "source_kind": image.source_kind,
                "source_message_id": image.source_message_id,
                "competition_reference_path": image.competition_reference_path,
            }
            for image in images
        ],
        "current_issue": issue,
        "policy_requirement_id": definition.policy_requirement_id,
    }


def _partial_trace(
    definition: CaseDefinition,
    requested_reference: str,
    messages: Sequence[NormalizedRecord],
    order: NormalizedRecord | None,
    tickets: Sequence[NormalizedRecord],
    diagnostics: Sequence[ImportDiagnostic],
    future_messages: Sequence[NormalizedRecord],
    future_augmentations: Sequence[CatalogMessage],
    future_tickets: Sequence[NormalizedRecord],
    future_images: Sequence[CatalogEvidenceImage],
) -> Mapping[str, object]:
    return {
        **_trace_header(definition, requested_reference, "DIAGNOSTIC"),
        "competition_messages": [_message_trace(message) for message in messages],
        "order": _order_trace(order) if order is not None else None,
        "tickets": [_ticket_trace(ticket) for ticket in tickets],
        "diagnostics": [diagnostic.as_dict() for diagnostic in diagnostics],
        "future_facts_excluded": _future_counts(
            future_messages,
            future_augmentations,
            future_tickets,
            future_images,
            0,
        ),
    }


def _success_trace(
    definition: CaseDefinition,
    requested_reference: str,
    messages: Sequence[NormalizedRecord],
    order: NormalizedRecord,
    tickets: Sequence[NormalizedRecord],
    augmentations: Sequence[CatalogMessage],
    images: Sequence[CatalogEvidenceImage],
    item_trace: Sequence[Mapping[str, object]],
    future_messages: Sequence[NormalizedRecord],
    future_augmentations: Sequence[CatalogMessage],
    future_tickets: Sequence[NormalizedRecord],
    future_images: Sequence[CatalogEvidenceImage],
    ticket_completion_after_evaluation: int,
) -> Mapping[str, object]:
    return {
        **_trace_header(definition, requested_reference, "ASSEMBLED"),
        "join_checks": [
            {
                "check": "session_to_competition_messages",
                "status": "PASS",
                "source_session_id": definition.source_session_id,
            },
            {
                "check": "session_to_order_then_catalog_order_id",
                "status": "PASS",
                "order_id": definition.expected_order_id,
            },
            {
                "check": "session_to_ticket_then_order_id",
                "status": "PASS",
                "ticket_ids": [_identifier(ticket, "ticket_id") for ticket in tickets],
            },
            {
                "check": "catalog_evidence_to_source_image_path",
                "status": "PASS",
                "evidence_ids": [image.evidence_id for image in images],
            },
        ],
        "competition_messages": [_message_trace(message) for message in messages],
        "order": _order_trace(order),
        "tickets": [_ticket_trace(ticket) for ticket in tickets],
        "augmentation_messages": [
            {
                "message_id": message.message_id,
                "timestamp": message.timestamp.isoformat(),
                "source_kind": message.source_kind,
            }
            for message in augmentations
        ],
        "items": [dict(item) for item in item_trace],
        "evidence_images": [
            {
                "evidence_id": image.evidence_id,
                "file_name": image.file_name,
                "submitted_at": image.submitted_at.isoformat(),
                "source_kind": image.source_kind,
                "source_message_id": image.source_message_id,
                "competition_reference_path": image.competition_reference_path,
            }
            for image in images
        ],
        "future_facts_excluded": _future_counts(
            future_messages,
            future_augmentations,
            future_tickets,
            future_images,
            ticket_completion_after_evaluation,
        ),
    }


def _trace_header(
    definition: CaseDefinition,
    requested_reference: str,
    status: Literal["ASSEMBLED", "DIAGNOSTIC"],
) -> Mapping[str, object]:
    return {
        "case_id": definition.case_id,
        "requested_case_reference": requested_reference,
        "display_aliases": list(definition.display_aliases),
        "source_session_id": definition.source_session_id,
        "evaluation_time": definition.evaluation_time.isoformat(),
        "status": status,
    }


def _message_trace(message: NormalizedRecord) -> Mapping[str, object]:
    return {
        "message_id": _identifier(message, "message_id"),
        "timestamp": _record_timestamp(message, "sent_at").isoformat(),
        "source_kind": "COMPETITION_MOCK",
        "source_sheet": message.source_sheet,
        "source_row": message.source_row,
        "source_coordinates": {
            field_name: message.source_coordinates[field_name]
            for field_name in ("session_id", "message_id", "sent_at", "order_id", "ticket_id")
            if field_name in message.source_coordinates
        },
    }


def _order_trace(order: NormalizedRecord) -> Mapping[str, object]:
    return {
        "order_id": _identifier(order, "order_id"),
        "source_kind": "COMPETITION_MOCK",
        "source_sheet": order.source_sheet,
        "source_row": order.source_row,
        "source_coordinates": {
            field_name: order.source_coordinates[field_name]
            for field_name in ("session_id", "order_id", "product_sku", "tracking_id", "gift")
            if field_name in order.source_coordinates
        },
    }


def _ticket_trace(ticket: NormalizedRecord) -> Mapping[str, object]:
    return {
        "ticket_id": _identifier(ticket, "ticket_id"),
        "order_id": _identifier(ticket, "order_id"),
        "source_kind": "COMPETITION_MOCK",
        "source_sheet": ticket.source_sheet,
        "source_row": ticket.source_row,
        "source_coordinates": {
            field_name: ticket.source_coordinates[field_name]
            for field_name in ("session_id", "ticket_id", "order_id", "created_at", "completed_at")
            if field_name in ticket.source_coordinates
        },
    }


def _future_counts(
    messages: Sequence[NormalizedRecord],
    augmentations: Sequence[CatalogMessage],
    tickets: Sequence[NormalizedRecord],
    images: Sequence[CatalogEvidenceImage],
    ticket_completions: int,
) -> Mapping[str, int]:
    return {
        "competition_messages": len(messages),
        "augmentation_messages": len(augmentations),
        "tickets_created_after_evaluation": len(tickets),
        "evidence_images": len(images),
        "ticket_completions_after_evaluation": ticket_completions,
    }


def _identifier(record: NormalizedRecord, field_name: str) -> str:
    value = record.fields.get(field_name)
    if not isinstance(value, str) or not value:
        raise CaseSourceError(
            f"{record.kind} source field {field_name!r} is not a non-empty string"
        )
    return value


def _record_timestamp(record: NormalizedRecord, field_name: str) -> datetime:
    value = record.fields.get(field_name)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CaseSourceError(f"{record.kind} source field {field_name!r} is not an aware datetime")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CaseSourceError("source text field is not a non-empty string or null")
    return value


def _required_text(value: object, label: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise CaseSourceError(f"{label} is required")
    return text


def _write_json(path: Path, payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(path)
