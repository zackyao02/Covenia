from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from covenia_b.domain.validation import validate_contract_payload
from covenia_b.importing.case_assembler import CaseAssembler, CaseAssociationError
from covenia_b.importing.case_catalog import CaseCatalog, CatalogEvidenceImage, CatalogMessage

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK_PATH = REPOSITORY_ROOT / "data" / "tianchi-track1-mock-data.xlsx"
DEMO_CASES_PATH = REPOSITORY_ROOT / "fixtures" / "demo-cases.json"
MANIFEST_PATH = REPOSITORY_ROOT / "handoff" / "a" / "cases-manifest.json"


@pytest.fixture()
def assembler() -> CaseAssembler:
    return CaseAssembler.from_paths(WORKBOOK_PATH, DEMO_CASES_PATH, MANIFEST_PATH)


def test_hero_case_is_joined_from_real_source_records_and_validates_schema(
    assembler: CaseAssembler,
) -> None:
    assembly = assembler.assemble("DEMO_001")

    assert assembly.status == "ASSEMBLED"
    assert assembly.case_input is not None
    case_input = assembly.case_input
    validate_contract_payload("case-input.schema.json", case_input)
    assert case_input["data_provenance"] == {
        "source_dataset": "TIANCHI_LOREAL_TRACK1_MOCK",
        "source_session_id": "S00001",
        "augmentation_notes": case_input["data_provenance"]["augmentation_notes"],
    }
    assert case_input["evaluation_time"] == "2026-05-07T09:40:00+08:00"
    assert case_input["order"]["order_id"] == "6920185815517983396"
    assert [ticket["ticket_id"] for ticket in case_input["service_tickets"]] == ["BH919209358357"]
    assert [message["source_kind"] for message in case_input["conversation"]] == [
        "COMPETITION_MOCK",
        "COMPETITION_MOCK",
        "COMPETITION_MOCK",
        "COMPETITION_MOCK",
        "COMPETITION_MOCK",
        "COMPETITION_MOCK",
        "DEMO_AUGMENTATION",
    ]

    source_first_message = assembler.dataset.messages[0]
    assert case_input["conversation"][0]["message_id"] == source_first_message.fields["message_id"]
    assert case_input["conversation"][0]["text"] == source_first_message.fields["message_text"]
    assert assembly.association_trace["order"]["source_coordinates"]["order_id"] == "A45"
    assert assembly.association_trace["tickets"][0]["source_coordinates"]["ticket_id"] == "A10"
    assert assembly.association_trace["future_facts_excluded"] == {
        "competition_messages": 0,
        "augmentation_messages": 0,
        "tickets_created_after_evaluation": 0,
        "evidence_images": 0,
        "ticket_completions_after_evaluation": 0,
    }


def test_display_alias_selects_the_same_source_facts(assembler: CaseAssembler) -> None:
    canonical = assembler.assemble("DEMO_001")
    definition = assembler.catalog.resolve("DEMO_001")
    display_alias = next(alias for alias in definition.display_aliases if alias != "DEMO_001")
    alias_assembly = assembler.assemble(display_alias)

    assert canonical.case_input is not None
    assert alias_assembly.case_input == canonical.case_input
    assert alias_assembly.source_session_id == "S00001"
    assert alias_assembly.requested_case_reference == display_alias


def test_reverse_order_and_ticket_associations_are_rejected(assembler: CaseAssembler) -> None:
    hero_order = next(
        order
        for order in assembler.dataset.orders
        if order.fields["order_id"] == "6920185815517983396"
    )
    hero_ticket = next(
        ticket
        for ticket in assembler.dataset.tickets
        if ticket.fields["ticket_id"] == "BH919209358357"
    )

    reverse_order = replace(
        hero_order,
        fields={**hero_order.fields, "session_id": "S00002"},
    )
    reverse_order_dataset = replace(
        assembler.dataset,
        orders=tuple(
            reverse_order if order is hero_order else order for order in assembler.dataset.orders
        ),
    )
    with pytest.raises(CaseAssociationError, match="different source session"):
        CaseAssembler(reverse_order_dataset, assembler.catalog).assemble("DEMO_001")

    reverse_ticket = replace(
        hero_ticket,
        fields={**hero_ticket.fields, "order_id": "not-the-hero-order"},
    )
    reverse_ticket_dataset = replace(
        assembler.dataset,
        tickets=tuple(
            reverse_ticket if ticket is hero_ticket else ticket
            for ticket in assembler.dataset.tickets
        ),
    )
    with pytest.raises(CaseAssociationError, match="session/order relation"):
        CaseAssembler(reverse_ticket_dataset, assembler.catalog).assemble("DEMO_001")


def test_future_messages_tickets_and_images_are_excluded(assembler: CaseAssembler) -> None:
    definition = assembler.catalog.resolve("DEMO_001")
    source_message = assembler.dataset.messages[0]
    source_ticket = next(
        ticket
        for ticket in assembler.dataset.tickets
        if ticket.fields["ticket_id"] == "BH919209358357"
    )
    future_at = definition.evaluation_time + timedelta(minutes=1)
    future_message = replace(
        source_message,
        fields={
            **source_message.fields,
            "message_id": "FUTURE_COMPETITION_MESSAGE",
            "sent_at": future_at,
        },
    )
    future_ticket = replace(
        source_ticket,
        fields={
            **source_ticket.fields,
            "ticket_id": "FUTURE_TICKET",
            "created_at": future_at,
        },
    )
    future_augmentation = CatalogMessage(
        message_id="FUTURE_AUGMENTATION",
        timestamp=future_at,
        speaker="CONSUMER",
        text="future augmentation must not leak",
        source_kind="DEMO_AUGMENTATION",
    )
    future_image = CatalogEvidenceImage(
        evidence_id="FUTURE_IMAGE",
        file_name="future.jpg",
        submitted_at=future_at,
        declared_view_type="OTHER",
        source_kind="TEAM_SYNTHETIC_AUGMENTATION",
        source_message_id="FUTURE_AUGMENTATION",
        competition_reference_path=None,
    )
    future_definition = replace(
        definition,
        augmentation_messages=(*definition.augmentation_messages, future_augmentation),
        evidence_images=(*definition.evidence_images, future_image),
    )
    future_catalog = CaseCatalog(
        definitions=tuple(
            future_definition if item.case_id == definition.case_id else item
            for item in assembler.catalog.definitions
        ),
        source_session_display_aliases=assembler.catalog.source_session_display_aliases,
    )
    future_dataset = replace(
        assembler.dataset,
        messages=(*assembler.dataset.messages, future_message),
        tickets=(*assembler.dataset.tickets, future_ticket),
    )

    assembly = CaseAssembler(future_dataset, future_catalog).assemble("DEMO_001")

    assert assembly.case_input is not None
    assert "FUTURE_COMPETITION_MESSAGE" not in {
        message["message_id"] for message in assembly.case_input["conversation"]
    }
    assert "FUTURE_AUGMENTATION" not in {
        message["message_id"] for message in assembly.case_input["conversation"]
    }
    assert "FUTURE_TICKET" not in {
        ticket["ticket_id"] for ticket in assembly.case_input["service_tickets"]
    }
    assert "FUTURE_IMAGE" not in {
        image["evidence_id"] for image in assembly.case_input["evidence_images"]
    }
    assert assembly.association_trace["future_facts_excluded"] == {
        "competition_messages": 1,
        "augmentation_messages": 1,
        "tickets_created_after_evaluation": 1,
        "evidence_images": 1,
        "ticket_completions_after_evaluation": 0,
    }


def test_all_five_ticket_sheets_are_joined_by_session_then_order(
    assembler: CaseAssembler,
) -> None:
    definition = assembler.catalog.resolve("DEMO_001")
    samples_by_category = {}
    for ticket in assembler.dataset.tickets:
        samples_by_category.setdefault(ticket.ticket_category, ticket)
    assert set(samples_by_category) == {
        "REPLACEMENT_EXCHANGE",
        "OFFLINE_PAYMENT",
        "LOGISTICS",
        "ADVERSE_REACTION",
        "AFTER_SALES_RETURN",
    }
    replacements = {
        ticket.fields["ticket_id"]: replace(
            ticket,
            fields={
                **ticket.fields,
                "session_id": "S00001",
                "order_id": definition.expected_order_id,
                "created_at": definition.evaluation_time - timedelta(seconds=1),
                "completed_at": None,
            },
        )
        for ticket in samples_by_category.values()
    }
    joined_dataset = replace(
        assembler.dataset,
        tickets=tuple(
            replacements.get(ticket.fields["ticket_id"], ticket)
            for ticket in assembler.dataset.tickets
        ),
    )

    assembly = CaseAssembler(joined_dataset, assembler.catalog).assemble("DEMO_001")

    assert assembly.case_input is not None
    assert {ticket["ticket_type"] for ticket in assembly.case_input["service_tickets"]} == {
        "REPLACEMENT",
        "OFFLINE_PAYMENT",
        "LOGISTICS",
        "ADVERSE_REACTION",
        "RETURN",
    }


def test_all_sessions_receive_importability_diagnostics_without_fabrication(
    assembler: CaseAssembler,
) -> None:
    diagnostics = assembler.diagnose_importability()

    assert len(diagnostics) == 138
    hero = next(item for item in diagnostics if item.source_session_id == "S00001")
    assert hero.catalog_case_ids == ("DEMO_001", "DEMO_002", "DEMO_003")
    assert hero.p0_ready is True
    assert any("MISSING_ORDER" in item.diagnostic_codes for item in diagnostics)
    assert any("MISSING_IMAGE_REFERENCE" in item.diagnostic_codes for item in diagnostics)
    assert any("NO_CASE_CATALOG_ENTRY" in item.diagnostic_codes for item in diagnostics)
    assert sum(item.p0_ready for item in diagnostics) == 1


def test_redacted_artifacts_remain_schema_valid_and_trace_all_sessions(
    assembler: CaseAssembler,
    tmp_path: Path,
) -> None:
    artifacts = assembler.write_redacted_artifacts(tmp_path)

    case_payload = json.loads(artifacts["case_input"].read_text(encoding="utf-8"))
    trace_payload = json.loads(artifacts["association_trace"].read_text(encoding="utf-8"))
    hero = next(item for item in case_payload["case_inputs"] if item["case_id"] == "DEMO_001")
    assert hero["status"] == "ASSEMBLED"
    assert hero["case_input"]["conversation"][0]["text"].startswith("[REDACTED ")
    validate_contract_payload("case-input.schema.json", hero["case_input"])
    assert len(trace_payload["dataset_importability"]) == 138
    assert all("prepared_action" not in item for item in case_payload["case_inputs"])
