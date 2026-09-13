from __future__ import annotations

from pathlib import Path

from covenia_b.importing.workbook import CompetitionWorkbook

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK_PATH = REPOSITORY_ROOT / "data" / "tianchi-track1-mock-data.xlsx"


def test_reads_business_sheets_as_raw_source_rows() -> None:
    workbook = CompetitionWorkbook(WORKBOOK_PATH)

    assert tuple(workbook.sheet_names()) == (
        "数据说明",
        "聊天记录",
        "订单",
        "补发换货工单",
        "线下打款工单",
        "物流工单",
        "不良反应工单",
        "售后退货工单",
    )
    messages = workbook.read_rows("聊天记录")
    assert len(messages) == 998
    first = messages[0]
    assert first.sheet == "聊天记录"
    assert first.row_number == 2
    assert first["会话ID"].coordinate == "A2"
    assert first["会话ID"].data_type == "s"
    assert first["会话ID"].value == "S00001"
    assert first["消息序号"].coordinate == "B2"
    assert first["消息序号"].data_type == "n"
    assert first["消息序号"].value == "1"


def test_preserves_long_order_identifier_as_shared_string() -> None:
    workbook = CompetitionWorkbook(WORKBOOK_PATH)
    matching = [
        row
        for row in workbook.read_rows("订单")
        if row["订单号"].value == "6920185815517983396"
    ]

    assert len(matching) == 1
    source = matching[0]["订单号"]
    assert source.coordinate.startswith("A")
    assert source.data_type == "s"
    assert source.value == "6920185815517983396"
