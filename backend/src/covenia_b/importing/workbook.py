"""Read XLSX workbook cells without coercing source values through floats."""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from covenia_b.ports.errors import WorkbookUnavailable

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"m": _MAIN_NS, "r": _REL_NS, "p": _PACKAGE_REL_NS}
_CELL_REFERENCE = re.compile(r"^([A-Z]+)([0-9]+)$")
_NON_TABULAR_SHEETS = frozenset({"数据说明"})


@dataclass(frozen=True, slots=True)
class SourceCell:
    """A raw cell value together with its immutable source coordinate and type."""

    coordinate: str
    data_type: str
    value: str | None
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class SourceRow(Mapping[str, SourceCell]):
    """A business-sheet row keyed by its original header text."""

    sheet: str
    row_number: int
    cells: Mapping[str, SourceCell]

    def __getitem__(self, key: str) -> SourceCell:
        return self.cells[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.cells)

    def __len__(self) -> int:
        return len(self.cells)


class CompetitionWorkbook:
    """A read-only OOXML adapter that implements the frozen ``Workbook`` port.

    The adapter deliberately reads ``<v>`` XML text directly. In particular it
    never asks a spreadsheet library to materialize numeric identifiers as a
    Python float before the importing layer can inspect their original type.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._loaded: tuple[tuple[str, ...], dict[str, tuple[SourceRow, ...]]] | None = None

    @property
    def source_name(self) -> str:
        return self._path.name

    @property
    def source_path(self) -> Path:
        return self._path

    def sheet_names(self) -> Sequence[str]:
        sheet_names, _ = self._load()
        return sheet_names

    def read_rows(self, sheet_name: str) -> Sequence[SourceRow]:
        _, sheets = self._load()
        try:
            return sheets[sheet_name]
        except KeyError as exc:
            raise WorkbookUnavailable(f"Workbook does not contain sheet {sheet_name!r}") from exc

    def _load(self) -> tuple[tuple[str, ...], dict[str, tuple[SourceRow, ...]]]:
        if self._loaded is not None:
            return self._loaded

        try:
            with zipfile.ZipFile(self._path) as archive:
                shared_strings = _read_shared_strings(archive)
                workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
                relationships = _read_relationships(archive)
                sheet_names: list[str] = []
                sheets: dict[str, tuple[SourceRow, ...]] = {}
                for sheet in workbook_root.findall("m:sheets/m:sheet", _NS):
                    name = sheet.attrib["name"]
                    relationship_id = sheet.attrib[f"{{{_REL_NS}}}id"]
                    try:
                        target = relationships[relationship_id]
                    except KeyError as exc:
                        raise WorkbookUnavailable(
                            f"Workbook sheet {name!r} has no relationship target"
                        ) from exc
                    member = _worksheet_member_name(target)
                    if name in _NON_TABULAR_SHEETS:
                        # The mapping explicitly excludes this prose-only sheet from
                        # business input. Keep it visible in ``sheet_names`` without
                        # inventing a table header for its free-form explanation.
                        sheets[name] = ()
                    else:
                        root = ET.fromstring(archive.read(member))
                        sheets[name] = _read_sheet_rows(root, name, shared_strings)
                    sheet_names.append(name)
        except WorkbookUnavailable:
            raise
        except (ET.ParseError, KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
            raise WorkbookUnavailable(f"Unable to read workbook {self._path}") from exc

        self._loaded = (tuple(sheet_names), sheets)
        return self._loaded


def _read_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("m:si", _NS):
        values.append("".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")))
    return tuple(values)


def _read_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    return {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in root.findall("p:Relationship", _NS)
    }


def _worksheet_member_name(target: str) -> str:
    normalized = target.lstrip("/")
    if normalized.startswith("xl/"):
        return posixpath.normpath(normalized)
    return posixpath.normpath(posixpath.join("xl", normalized))


def _read_sheet_rows(
    root: ET.Element,
    sheet_name: str,
    shared_strings: tuple[str, ...],
) -> tuple[SourceRow, ...]:
    xml_rows = root.findall("m:sheetData/m:row", _NS)
    if not xml_rows:
        raise WorkbookUnavailable(f"Sheet {sheet_name!r} has no rows")

    headers = _read_headers(xml_rows[0], sheet_name, shared_strings)
    rows: list[SourceRow] = []
    for xml_row in xml_rows[1:]:
        row_number = _row_number(xml_row, sheet_name)
        actual_cells: dict[int, SourceCell] = {}
        for xml_cell in xml_row.findall("m:c", _NS):
            source_cell = _read_cell(xml_cell, shared_strings)
            column_index = _column_index(source_cell.coordinate, sheet_name)
            if column_index not in headers and source_cell.value is not None:
                raise WorkbookUnavailable(
                    f"{sheet_name}!{source_cell.coordinate} has no matching header"
                )
            actual_cells[column_index] = source_cell

        cells = {
            header: actual_cells.get(
                column_index,
                SourceCell(
                    coordinate=f"{_column_label(column_index)}{row_number}",
                    data_type="missing",
                    value=None,
                ),
            )
            for column_index, header in headers.items()
        }
        if any(cell.value is not None for cell in cells.values()):
            rows.append(
                SourceRow(
                    sheet=sheet_name,
                    row_number=row_number,
                    cells=MappingProxyType(cells),
                )
            )
    return tuple(rows)


def _read_headers(
    xml_row: ET.Element,
    sheet_name: str,
    shared_strings: tuple[str, ...],
) -> dict[int, str]:
    headers: dict[int, str] = {}
    for xml_cell in xml_row.findall("m:c", _NS):
        source_cell = _read_cell(xml_cell, shared_strings)
        if source_cell.value is None:
            continue
        column_index = _column_index(source_cell.coordinate, sheet_name)
        if source_cell.value in headers.values():
            raise WorkbookUnavailable(
                f"Sheet {sheet_name!r} has duplicate header {source_cell.value!r}"
            )
        headers[column_index] = source_cell.value
    if not headers:
        raise WorkbookUnavailable(f"Sheet {sheet_name!r} has no headers")
    return headers


def _read_cell(xml_cell: ET.Element, shared_strings: tuple[str, ...]) -> SourceCell:
    coordinate = xml_cell.attrib.get("r")
    if coordinate is None:
        raise WorkbookUnavailable("Workbook cell is missing a coordinate")
    data_type = xml_cell.attrib.get("t", "n")
    formula = xml_cell.findtext("m:f", default=None, namespaces=_NS)
    raw_value = xml_cell.findtext("m:v", default=None, namespaces=_NS)

    if data_type == "s":
        if raw_value is None:
            raise WorkbookUnavailable(f"Shared-string cell {coordinate} has no index")
        try:
            value = shared_strings[int(raw_value)]
        except (IndexError, ValueError) as exc:
            raise WorkbookUnavailable(
                f"Shared-string cell {coordinate} has an invalid index"
            ) from exc
    elif data_type == "inlineStr":
        value = "".join(node.text or "" for node in xml_cell.iter(f"{{{_MAIN_NS}}}t"))
    else:
        value = raw_value

    return SourceCell(
        coordinate=coordinate,
        data_type=data_type,
        value=value if value not in (None, "") else None,
        formula=formula,
    )


def _column_index(coordinate: str, sheet_name: str) -> int:
    match = _CELL_REFERENCE.match(coordinate)
    if match is None:
        raise WorkbookUnavailable(f"Invalid cell coordinate {sheet_name}!{coordinate}")
    index = 0
    for character in match.group(1):
        index = index * 26 + (ord(character) - ord("A") + 1)
    return index


def _row_number(xml_row: ET.Element, sheet_name: str) -> int:
    value = xml_row.attrib.get("r")
    if value is None or not value.isdecimal():
        raise WorkbookUnavailable(f"Sheet {sheet_name!r} has a row without a numeric coordinate")
    return int(value)


def _column_label(index: int) -> str:
    characters: list[str] = []
    while index:
        index, remainder = divmod(index - 1, 26)
        characters.append(chr(ord("A") + remainder))
    return "".join(reversed(characters))
