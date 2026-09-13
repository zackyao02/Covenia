"""Normalize the seven business sheets while preserving workbook provenance."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from covenia_b.importing.workbook import CompetitionWorkbook, SourceCell, SourceRow
from covenia_b.ports.errors import WorkbookUnavailable

BUSINESS_SHEETS = (
    "聊天记录",
    "订单",
    "补发换货工单",
    "线下打款工单",
    "物流工单",
    "不良反应工单",
    "售后退货工单",
)
NON_BUSINESS_SHEETS = ("数据说明",)
TICKET_CATEGORY_BY_SHEET = {
    "补发换货工单": "REPLACEMENT_EXCHANGE",
    "线下打款工单": "OFFLINE_PAYMENT",
    "物流工单": "LOGISTICS",
    "不良反应工单": "ADVERSE_REACTION",
    "售后退货工单": "AFTER_SALES_RETURN",
}
_STRING_CELL_TYPES = frozenset({"s", "str", "inlineStr"})
_ID_FIELDS = frozenset(
    {
        "session_id",
        "message_id",
        "order_id",
        "ticket_id",
        "tracking_id",
        "original_tracking_id",
        "replacement_tracking_id",
        "related_tracking_id",
        "issue_tracking_id",
        "return_tracking_id",
        "refund_id",
    }
)
_TIME_FIELDS = frozenset(
    {"sent_at", "ordered_at", "paid_at", "shipped_at", "created_at", "completed_at"}
)
_INTEGER_FIELDS = frozenset({"message_sequence", "quantity", "age"})
_MONEY_FIELDS = frozenset(
    {"unit_price_cny", "paid_amount_cny", "refund_amount_cny", "order_paid_amount_cny"}
)
_BOOLEAN_FIELDS = frozenset({"is_target_buyer_message"})
_TIMEZONE = timezone(timedelta(hours=8), name="+08:00")
_TIMESTAMP_WITH_OPTIONAL_ANNOTATION = re.compile(
    r"^(?P<timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?P<annotation>（[^（）]+）|\([^()]+\))?$"
)
_HEADER_TO_FIELD = {
    "会话ID": "session_id",
    "消息序号": "message_sequence",
    "message_id": "message_id",
    "发送时间": "sent_at",
    "角色": "role",
    "买家昵称": "buyer_alias",
    "发送方": "sender",
    "店铺": "store_name",
    "scene_major": "scene_major",
    "scene_minor": "scene_minor",
    "is_target_buyer_message": "is_target_buyer_message",
    "message_text": "message_text",
    "内容类型": "content_type",
    "chat_content": "chat_content",
    "category": "category",
    "image_path": "image_path",
    "关联订单号": "order_id",
    "关联工单号": "ticket_id",
    "订单号": "order_id",
    "商品货号": "product_sku",
    "商品名称": "product_name",
    "数量": "quantity",
    "单价(元)": "unit_price_cny",
    "实付金额(元)": "paid_amount_cny",
    "订单状态": "order_status",
    "下单时间": "ordered_at",
    "付款时间": "paid_at",
    "发货时间": "shipped_at",
    "快递公司": "carrier",
    "物流单号": "tracking_id",
    "收货省": "recipient_province",
    "收货市": "recipient_city",
    "赠品": "gift",
    "买家留言": "buyer_note",
    "工单号": "ticket_id",
    "工单类型": "ticket_type",
    "售后原因": "after_sales_reason",
    "发出商品货号": "shipped_product_sku",
    "发出商品名称": "shipped_product_name",
    "原订单物流单号": "original_tracking_id",
    "补发物流单号": "replacement_tracking_id",
    "发货仓库": "fulfillment_warehouse",
    "客诉加急": "escalation_requested",
    "工单状态": "ticket_status",
    "处理人": "handler_id",
    "创建时间": "created_at",
    "完成时间": "completed_at",
    "打款类型": "payment_type",
    "退款问题类型": "refund_issue_type",
    "退款金额(元)": "refund_amount_cny",
    "支付宝实名": "alipay_account_name",
    "支付宝账号": "alipay_account",
    "相关物流单号": "related_tracking_id",
    "转账状态": "transfer_status",
    "问题类型": "issue_type",
    "问题包裹物流单号": "issue_tracking_id",
    "发货仓": "fulfillment_warehouse",
    "订单实付(元)": "order_paid_amount_cny",
    "处理方案": "resolution_plan",
    "类型": "incident_type",
    "年龄": "age",
    "肤质": "skin_type",
    "使用商品": "used_product_name",
    "产品批次号": "product_lot",
    "不适部位": "affected_area",
    "症状描述": "symptoms",
    "用后多久出现": "onset_delay",
    "是否停用": "discontinued",
    "是否就医": "sought_medical_care",
    "任务状态": "ticket_status",
    "包裹类型": "parcel_type",
    "退货原因": "return_reason",
    "退货物流单号": "return_tracking_id",
    "退款编号": "refund_id",
    "签收建议": "receipt_recommendation",
    "是否异常": "is_exception",
}


class WorkbookImportError(WorkbookUnavailable):
    """The workbook can be opened but violates the importing contract."""


class IdentifierTypeError(WorkbookImportError):
    """An identifier was stored as a non-string Excel cell."""


class IdentifierPrecisionError(IdentifierTypeError):
    """A numeric identifier may already have lost precision before import."""


class RequiredIdentifierMissing(WorkbookImportError):
    """A primary source identifier is absent or blank."""


class AssociationIntegrityError(WorkbookImportError):
    """A declared order, ticket, or session association cannot be resolved."""


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    """One normalized row, with raw source-cell metadata kept separately."""

    kind: str
    source_sheet: str
    source_row: int
    fields: Mapping[str, object]
    source_coordinates: Mapping[str, str]
    source_data_types: Mapping[str, str]
    raw_values: Mapping[str, str | None]
    time_annotations: Mapping[str, str]
    ticket_category: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedDataset:
    """The normalized in-memory dataset used by later importing consumers."""

    messages: tuple[NormalizedRecord, ...]
    orders: tuple[NormalizedRecord, ...]
    tickets: tuple[NormalizedRecord, ...]
    field_mappings: Mapping[str, Mapping[str, str]]


def normalize_workbook(workbook: CompetitionWorkbook) -> NormalizedDataset:
    """Read and validate all seven business sheets from a ``Workbook`` adapter."""

    _validate_sheet_layout(workbook)
    messages, message_mapping = _normalize_sheet(workbook, "聊天记录", "message")
    orders, order_mapping = _normalize_sheet(workbook, "订单", "order")
    tickets: list[NormalizedRecord] = []
    field_mappings: dict[str, Mapping[str, str]] = {
        "聊天记录": message_mapping,
        "订单": order_mapping,
    }
    for sheet_name, ticket_category in TICKET_CATEGORY_BY_SHEET.items():
        normalized, mapping = _normalize_sheet(
            workbook,
            sheet_name,
            "ticket",
            ticket_category=ticket_category,
        )
        tickets.extend(normalized)
        field_mappings[sheet_name] = mapping

    dataset = NormalizedDataset(
        messages=tuple(messages),
        orders=tuple(orders),
        tickets=tuple(tickets),
        field_mappings=field_mappings,
    )
    _validate_required_identifiers(dataset)
    _validate_associations(dataset)
    return dataset


def build_counts(dataset: NormalizedDataset) -> dict[str, object]:
    """Compute all published counts from normalized records, never constants."""

    ticket_count_by_sheet = {
        sheet_name: sum(1 for ticket in dataset.tickets if ticket.source_sheet == sheet_name)
        for sheet_name in TICKET_CATEGORY_BY_SHEET
    }
    return {
        "conversation_count": len({record.fields["session_id"] for record in dataset.messages}),
        "message_count": len(dataset.messages),
        "order_count": len(dataset.orders),
        "image_message_count": sum(
            1 for record in dataset.messages if record.fields.get("image_path") is not None
        ),
        "ticket_count_total": len(dataset.tickets),
        "ticket_count_by_sheet": ticket_count_by_sheet,
    }


def build_provenance(dataset: NormalizedDataset) -> dict[str, object]:
    """Build a redacted, deterministic source index without raw message content."""

    return {
        "schema_version": "covenia-b-import-provenance-v1",
        "normalization": {
            "business_sheets": list(BUSINESS_SHEETS),
            "excluded_sheets": list(NON_BUSINESS_SHEETS),
            "null_policy": "blank and absent cells normalize to null",
            "timezone": "+08:00",
            "identifier_policy": "identifier cells must be string-typed source cells",
            "ticket_categories": dict(TICKET_CATEGORY_BY_SHEET),
        },
        "field_mappings": {
            sheet_name: dict(mapping)
            for sheet_name, mapping in sorted(dataset.field_mappings.items())
        },
        "records": {
            "messages": [_record_provenance(record) for record in dataset.messages],
            "orders": [_record_provenance(record) for record in dataset.orders],
            "tickets": [_record_provenance(record) for record in dataset.tickets],
        },
    }


def _normalize_sheet(
    workbook: CompetitionWorkbook,
    sheet_name: str,
    kind: str,
    ticket_category: str | None = None,
) -> tuple[list[NormalizedRecord], Mapping[str, str]]:
    records: list[NormalizedRecord] = []
    field_mapping: dict[str, str] | None = None
    for source_row in workbook.read_rows(sheet_name):
        if not isinstance(source_row, SourceRow):
            raise WorkbookImportError(
                f"{sheet_name!r} returned a row without source-cell metadata"
            )
        record, mapping = _normalize_row(source_row, kind, ticket_category)
        if field_mapping is None:
            field_mapping = mapping
        elif field_mapping != mapping:
            raise WorkbookImportError(f"{sheet_name!r} changed headers between rows")
        records.append(record)
    return records, field_mapping or {}


def _normalize_row(
    source_row: SourceRow,
    kind: str,
    ticket_category: str | None,
) -> tuple[NormalizedRecord, Mapping[str, str]]:
    fields: dict[str, object] = {}
    source_coordinates: dict[str, str] = {}
    source_data_types: dict[str, str] = {}
    raw_values: dict[str, str | None] = {}
    time_annotations: dict[str, str] = {}
    mapping: dict[str, str] = {}
    for header, cell in source_row.items():
        field_name = _canonical_field_name(header)
        if field_name in fields:
            raise WorkbookImportError(
                f"{source_row.sheet}!{cell.coordinate} maps duplicate field {field_name!r}"
            )
        if field_name in _TIME_FIELDS and cell.value is not None:
            fields[field_name], annotation = _normalize_timestamp(
                field_name,
                cell,
                source_row.sheet,
            )
            if annotation is not None:
                time_annotations[field_name] = annotation
        else:
            fields[field_name] = _normalize_value(field_name, cell, source_row.sheet)
        source_coordinates[field_name] = cell.coordinate
        source_data_types[field_name] = cell.data_type
        raw_values[field_name] = cell.value
        mapping[header] = field_name
    return (
        NormalizedRecord(
            kind=kind,
            source_sheet=source_row.sheet,
            source_row=source_row.row_number,
            fields=fields,
            source_coordinates=source_coordinates,
            source_data_types=source_data_types,
            raw_values=raw_values,
            time_annotations=time_annotations,
            ticket_category=ticket_category,
        ),
        mapping,
    )


def _normalize_value(field_name: str, cell: SourceCell, sheet_name: str) -> object:
    if field_name in _ID_FIELDS:
        return _normalize_identifier(field_name, cell, sheet_name)
    if cell.value is None:
        return None
    if field_name in _INTEGER_FIELDS:
        if not re.fullmatch(r"[+-]?[0-9]+", cell.value):
            raise WorkbookImportError(
                f"{sheet_name}!{cell.coordinate} has invalid integer {field_name}={cell.value!r}"
            )
        return int(cell.value)
    if field_name in _MONEY_FIELDS:
        try:
            return Decimal(cell.value)
        except InvalidOperation as exc:
            raise WorkbookImportError(
                f"{sheet_name}!{cell.coordinate} has invalid monetary value {cell.value!r}"
            ) from exc
    if field_name in _BOOLEAN_FIELDS:
        if cell.value == "1":
            return True
        if cell.value == "0":
            return False
        raise WorkbookImportError(
            f"{sheet_name}!{cell.coordinate} has invalid boolean {field_name}={cell.value!r}"
        )
    return cell.value


def _normalize_timestamp(
    field_name: str,
    cell: SourceCell,
    sheet_name: str,
) -> tuple[datetime, str | None]:
    assert cell.value is not None
    match = _TIMESTAMP_WITH_OPTIONAL_ANNOTATION.fullmatch(cell.value)
    if match is None:
        raise WorkbookImportError(
            f"{sheet_name}!{cell.coordinate} has invalid {field_name} timestamp {cell.value!r}"
        )
    try:
        parsed = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_TIMEZONE
        )
    except ValueError as exc:
        raise WorkbookImportError(
            f"{sheet_name}!{cell.coordinate} has invalid {field_name} timestamp {cell.value!r}"
        ) from exc
    annotation = match.group("annotation")
    if annotation is None:
        return parsed, None
    return parsed, annotation[1:-1]


def _normalize_identifier(field_name: str, cell: SourceCell, sheet_name: str) -> str | None:
    if cell.value is None:
        return None
    if cell.data_type not in _STRING_CELL_TYPES:
        if _looks_like_precision_sensitive_number(cell.value):
            raise IdentifierPrecisionError(
                f"{sheet_name}!{cell.coordinate} stores long {field_name} as "
                f"numeric type {cell.data_type!r}; refusing lossy repair"
            )
        raise IdentifierTypeError(
            f"{sheet_name}!{cell.coordinate} stores {field_name} as numeric type "
            f"{cell.data_type!r}; identifiers must be source strings"
        )
    return cell.value


def _looks_like_precision_sensitive_number(value: str) -> bool:
    digits = "".join(character for character in value if character.isdigit())
    return len(digits) >= 16 or "e" in value.lower()


def _canonical_field_name(header: str) -> str:
    if header in _HEADER_TO_FIELD:
        return _HEADER_TO_FIELD[header]
    encoded = "_".join(f"u{ord(character):04x}" for character in header)
    return f"source_{encoded}"


def _validate_sheet_layout(workbook: CompetitionWorkbook) -> None:
    actual = tuple(workbook.sheet_names())
    expected = NON_BUSINESS_SHEETS + BUSINESS_SHEETS
    if actual != expected:
        raise WorkbookImportError(
            f"Workbook sheet layout differs; expected {expected!r}, received {actual!r}"
        )


def _validate_required_identifiers(dataset: NormalizedDataset) -> None:
    required_by_kind = {
        "message": ("session_id", "message_id"),
        "order": ("session_id", "order_id"),
        "ticket": ("session_id", "ticket_id", "order_id"),
    }
    for record in (*dataset.messages, *dataset.orders, *dataset.tickets):
        for field_name in required_by_kind[record.kind]:
            if record.fields.get(field_name) is None:
                coordinate = record.source_coordinates.get(field_name, "<missing header>")
                raise RequiredIdentifierMissing(
                    f"{record.source_sheet}!{coordinate} has no required {field_name}"
                )


def _validate_associations(dataset: NormalizedDataset) -> None:
    message_sessions = {str(record.fields["session_id"]) for record in dataset.messages}
    orders = _unique_index(dataset.orders, "order_id")
    tickets = _unique_index(dataset.tickets, "ticket_id")

    for record in (*dataset.orders, *dataset.tickets):
        session_id = str(record.fields["session_id"])
        if session_id not in message_sessions:
            raise AssociationIntegrityError(
                f"{record.source_sheet}!{record.source_coordinates['session_id']} references "
                f"unknown conversation {session_id!r}"
            )

    for ticket in dataset.tickets:
        order_id = str(ticket.fields["order_id"])
        order = orders.get(order_id)
        if order is None:
            _raise_missing_association(ticket, "order_id", "order", order_id)
        if order.fields["session_id"] != ticket.fields["session_id"]:
            raise AssociationIntegrityError(
                f"{ticket.source_sheet}!{ticket.source_coordinates['session_id']} does not match "
                f"order {order_id!r} conversation"
            )

    for message in dataset.messages:
        order_id = message.fields.get("order_id")
        if order_id is not None:
            order = orders.get(str(order_id))
            if order is None:
                _raise_missing_association(message, "order_id", "order", str(order_id))
            if order.fields["session_id"] != message.fields["session_id"]:
                raise AssociationIntegrityError(
                    f"{message.source_sheet}!{message.source_coordinates['order_id']} does not "
                    f"match order {order_id!r} conversation"
                )
        ticket_id = message.fields.get("ticket_id")
        if ticket_id is not None:
            ticket = tickets.get(str(ticket_id))
            if ticket is None:
                _raise_missing_association(message, "ticket_id", "ticket", str(ticket_id))
            if ticket.fields["session_id"] != message.fields["session_id"]:
                raise AssociationIntegrityError(
                    f"{message.source_sheet}!{message.source_coordinates['ticket_id']} does not "
                    f"match ticket {ticket_id!r} conversation"
                )


def _unique_index(
    records: tuple[NormalizedRecord, ...],
    field_name: str,
) -> dict[str, NormalizedRecord]:
    index: dict[str, NormalizedRecord] = {}
    for record in records:
        value = str(record.fields[field_name])
        if value in index:
            raise AssociationIntegrityError(
                f"Duplicate {field_name} {value!r} at {record.source_sheet}!"
                f"{record.source_coordinates[field_name]}"
            )
        index[value] = record
    return index


def _raise_missing_association(
    record: NormalizedRecord,
    field_name: str,
    target_kind: str,
    value: str,
) -> None:
    raise AssociationIntegrityError(
        f"{record.source_sheet}!{record.source_coordinates[field_name]} references "
        f"unknown {target_kind} {value!r}"
    )


def _record_provenance(record: NormalizedRecord) -> dict[str, object]:
    identifier_fields = ("session_id", "message_id", "order_id", "ticket_id")
    identifiers = {
        field_name: record.fields[field_name]
        for field_name in identifier_fields
        if field_name in record.fields
    }
    coordinates = {
        field_name: record.source_coordinates[field_name]
        for field_name in identifiers
    }
    result: dict[str, object] = {
        "kind": record.kind,
        "source_sheet": record.source_sheet,
        "source_row": record.source_row,
        "identifiers": identifiers,
        "source_coordinates": coordinates,
    }
    if record.ticket_category is not None:
        result["ticket_category"] = record.ticket_category
    if record.time_annotations:
        result["time_annotations"] = dict(record.time_annotations)
    return result
