from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from covenia_b.importing.cli import run_import
from covenia_b.importing.normalization import (
    AssociationIntegrityError,
    IdentifierPrecisionError,
    RequiredIdentifierMissing,
    build_counts,
    normalize_workbook,
)
from covenia_b.importing.workbook import CompetitionWorkbook

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK_PATH = REPOSITORY_ROOT / "data" / "tianchi-track1-mock-data.xlsx"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS = {"m": MAIN_NS}


def test_normalizes_real_workbook_and_computes_measured_counts() -> None:
    dataset = normalize_workbook(CompetitionWorkbook(WORKBOOK_PATH))
    counts = build_counts(dataset)

    assert counts == {
        "conversation_count": 138,
        "message_count": 998,
        "order_count": 113,
        "image_message_count": 29,
        "ticket_count_total": 80,
        "ticket_count_by_sheet": {
            "补发换货工单": 24,
            "线下打款工单": 13,
            "物流工单": 15,
            "不良反应工单": 10,
            "售后退货工单": 18,
        },
    }
    first_message = dataset.messages[0]
    assert first_message.fields["sent_at"].isoformat() == "2026-05-05T10:18:45+08:00"
    assert first_message.source_coordinates["message_id"] == "C2"
    assert first_message.fields["buyer_alias"] == "邓e**"
    assert all(ticket.ticket_category for ticket in dataset.tickets)
    deposit_order = next(
        order for order in dataset.orders if order.source_coordinates["paid_at"] == "L55"
    )
    assert deposit_order.fields["paid_at"].isoformat() == "2026-04-30T09:53:30+08:00"
    assert deposit_order.time_annotations["paid_at"] == "定金"
    assert deposit_order.raw_values["paid_at"] == "2026-04-30 09:53:30（定金）"


def test_cli_is_deterministic_and_does_not_change_input_bytes(tmp_path: Path) -> None:
    original_hash = _sha256(WORKBOOK_PATH)
    first = run_import(WORKBOOK_PATH, tmp_path / "first")
    second = run_import(WORKBOOK_PATH, tmp_path / "second")

    assert _sha256(WORKBOOK_PATH) == original_hash
    assert first["counts"] == second["counts"]
    for artifact in ("counts.json", "provenance.json", "input-hashes.json"):
        assert (tmp_path / "first" / artifact).read_bytes() == (
            tmp_path / "second" / artifact
        ).read_bytes()
    provenance = json.loads((tmp_path / "first" / "provenance.json").read_text("utf-8"))
    assert provenance["records"]["messages"][0]["source_coordinates"]["message_id"] == "C2"
    assert "buyer_alias" not in provenance["records"]["messages"][0]


def test_numeric_long_identifier_is_rejected_without_float_repair(tmp_path: Path) -> None:
    damaged = _copy_workbook(tmp_path, "numeric-long-id.xlsx")
    _replace_cell(damaged, "xl/worksheets/sheet3.xml", "A2", "6920185815517983396", "n")

    with pytest.raises(IdentifierPrecisionError, match="refusing lossy repair"):
        normalize_workbook(CompetitionWorkbook(damaged))


def test_empty_primary_identifier_and_bad_association_are_detected(tmp_path: Path) -> None:
    empty_id = _copy_workbook(tmp_path, "empty-id.xlsx")
    _replace_cell(empty_id, "xl/worksheets/sheet3.xml", "A2", "", "inlineStr")
    with pytest.raises(RequiredIdentifierMissing, match="required order_id"):
        normalize_workbook(CompetitionWorkbook(empty_id))

    bad_link = _copy_workbook(tmp_path, "bad-link.xlsx")
    _replace_cell(bad_link, "xl/worksheets/sheet2.xml", "Q2", "unknown-order", "inlineStr")
    with pytest.raises(AssociationIntegrityError, match="unknown order"):
        normalize_workbook(CompetitionWorkbook(bad_link))


def test_deleted_and_added_rows_change_real_import_counts(tmp_path: Path) -> None:
    deleted = _copy_workbook(tmp_path, "deleted-row.xlsx")
    _delete_last_row(deleted, "xl/worksheets/sheet2.xml")
    assert build_counts(normalize_workbook(CompetitionWorkbook(deleted)))["message_count"] == 997

    added = _copy_workbook(tmp_path, "added-row.xlsx")
    _append_message_row(added)
    assert build_counts(normalize_workbook(CompetitionWorkbook(added)))["message_count"] == 999


def _copy_workbook(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copyfile(WORKBOOK_PATH, target)
    return target


def _replace_cell(path: Path, member: str, coordinate: str, value: str, data_type: str) -> None:
    def mutate(root: ET.Element) -> None:
        cell = root.find(f".//m:c[@r='{coordinate}']", NS)
        assert cell is not None
        for child in list(cell):
            cell.remove(child)
        cell.attrib["t"] = data_type
        if data_type == "inlineStr":
            inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
            ET.SubElement(inline, f"{{{MAIN_NS}}}t").text = value
        else:
            ET.SubElement(cell, f"{{{MAIN_NS}}}v").text = value

    _mutate_member(path, member, mutate)


def _delete_last_row(path: Path, member: str) -> None:
    def mutate(root: ET.Element) -> None:
        sheet_data = root.find("m:sheetData", NS)
        assert sheet_data is not None
        rows = sheet_data.findall("m:row", NS)
        sheet_data.remove(rows[-1])

    _mutate_member(path, member, mutate)


def _append_message_row(path: Path) -> None:
    def mutate(root: ET.Element) -> None:
        sheet_data = root.find("m:sheetData", NS)
        assert sheet_data is not None
        row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": "1000"})
        _inline_cell(row, "A1000", "S00001")
        _number_cell(row, "B1000", "999")
        _inline_cell(row, "C1000", "BATCH05_TEST_MESSAGE")
        _inline_cell(row, "D1000", "2026-05-05 10:21:00")
        _inline_cell(row, "M1000", "文本")

    _mutate_member(path, "xl/worksheets/sheet2.xml", mutate)


def _inline_cell(row: ET.Element, coordinate: str, value: str) -> None:
    cell = ET.SubElement(row, f"{{{MAIN_NS}}}c", {"r": coordinate, "t": "inlineStr"})
    inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
    ET.SubElement(inline, f"{{{MAIN_NS}}}t").text = value


def _number_cell(row: ET.Element, coordinate: str, value: str) -> None:
    cell = ET.SubElement(row, f"{{{MAIN_NS}}}c", {"r": coordinate})
    ET.SubElement(cell, f"{{{MAIN_NS}}}v").text = value


def _mutate_member(path: Path, member: str, mutate: object) -> None:
    temporary = path.with_suffix(".rewritten.xlsx")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == member:
                root = ET.fromstring(content)
                mutate(root)  # type: ignore[operator]
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, content)
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
