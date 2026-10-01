from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from backend.tests.storage.support import INSTANT, ROOT, body, mutate, submit

from covenia_b.domain.types import AuditEntry, CompiledCommitment, CompiledCommitments
from covenia_b.ports import LedgerRepository
from covenia_b.ports.errors import LedgerConflict, LedgerUnavailable
from covenia_b.storage import (
    EventRecord,
    IdempotencyConflict,
    Mutation,
    SQLiteLedgerRepository,
    StoredResponse,
)
from covenia_b.storage.codec import (
    StoredAccountabilityState,
    decode_snapshot,
    encode_snapshot,
    event_digest,
    request_digest,
    time_order,
)
from covenia_b.storage.schema import APPLICATION_ID, TABLES


@pytest.fixture
def repository(tmp_path):
    return SQLiteLedgerRepository(tmp_path / "ledger.db")


def counts(repository):
    with sqlite3.connect(repository.db_path) as connection:
        return {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }


def test_ten_replays_keep_one_change_and_first_complete_response(repository):
    assert isinstance(repository, LedgerRepository)
    first = submit(repository)
    for index in range(10):
        replay = submit(repository, request_id=f"later-{index}")
        assert replay.replayed and replay.response == first.response
        assert replay.snapshot == first.snapshot
    assert counts(repository) == {**dict.fromkeys(TABLES, 1), "events": 0}
    assert repository.load("9007199254740993").version == 1
    assert repository.audit_history("9007199254740993")[0].request_id == "first-request"


def test_normalized_request_replay_excludes_transport_id(repository):
    request = body()
    first = repository.execute(
        case_id=request["case_id"],
        operation="approve",
        idempotency_key=request["idempotency_key"],
        request_body=request,
        mutate=mutate,
    )
    reordered = dict(reversed(list(request.items())))
    reordered.update({"request_id": "second", "X-Request-Id": "second-header"})
    replay = repository.execute(
        case_id=request["case_id"],
        operation="approve",
        idempotency_key=request["idempotency_key"],
        request_body=reordered,
        mutate=lambda _: pytest.fail("replay invoked callback"),
    )
    assert replay.response == first.response
    assert request_digest("approve", {"a": [1, 2]}) != request_digest("approve", {"a": [2, 1]})
    assert request_digest("approve", {"nested": {"request_id": "a"}}) != request_digest(
        "approve", {"nested": {"request_id": "b"}}
    )


@pytest.mark.parametrize("change", ["body", "operation"])
def test_case_scoped_key_conflicts_with_different_body_or_endpoint(repository, change):
    submit(repository)
    before = counts(repository)
    request = body()
    if change == "body":
        request["approver_id"] = "other-actor"
    with pytest.raises(IdempotencyConflict):
        repository.execute(
            case_id=request["case_id"],
            operation="shipment" if change == "operation" else "approve",
            idempotency_key=request["idempotency_key"],
            request_body=request,
            mutate=lambda _: pytest.fail("conflict invoked callback"),
        )
    assert counts(repository) == before
    assert repository.load(request["case_id"]).version == 1


def test_same_key_is_independent_between_cases(repository):
    submit(repository, case_id="alpha")
    submit(repository, case_id="beta")
    assert repository.load("alpha").version == repository.load("beta").version == 1
    assert counts(repository)["idempotent_requests"] == 2


def test_ten_concurrent_connections_only_call_mutation_once(repository):
    barrier = Barrier(10)
    called = []

    def worker(index):
        barrier.wait()
        request = body()

        def callback(current):
            called.append(index)
            return mutate(current, request_id=f"parallel-{index}")

        return repository.execute(
            case_id=request["case_id"],
            operation="approve",
            idempotency_key=request["idempotency_key"],
            request_body=request,
            mutate=callback,
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(worker, range(10)))
    assert len(called) == 1
    assert sum(not result.replayed for result in results) == 1
    assert all(result.response == results[0].response for result in results)
    assert counts(repository) == {**dict.fromkeys(TABLES, 1), "events": 0}


def test_different_keys_callbacks_observe_serialized_current_versions(repository):
    barrier = Barrier(2)

    def worker(index):
        barrier.wait()
        return submit(repository, key=f"distinct-{index}", request_id=f"r-{index}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert sorted(result.snapshot.version for result in results) == [1, 2]
    assert len(repository.audit_history("9007199254740993")) == 2


def test_event_replay_precedes_highwater_and_stale_version_checks(repository):
    first_event = EventRecord("event-a", "SHIPMENT_PICKED_UP", "2030-01-01T10:03:00Z")
    first = submit(repository, event=first_event)
    second_event = EventRecord("event-b", "SHIPMENT_DELIVERED", "2030-01-01T10:04:00Z")
    submit(repository, key="event-b-key", event=second_event)
    replay = submit(repository, key="event-a-alias", request_id="new", event=first_event)
    assert replay.replay_source == "event" and replay.response == first.response
    assert replay.snapshot.version == 1
    assert repository.load("9007199254740993").version == 2
    assert counts(repository)["events"] == counts(repository)["audit_entries"] == 2
    request = body(key="event-a-alias")
    request = {
        "case_id": request["case_id"],
        "idempotency_key": request["idempotency_key"],
        "event_id": first_event.event_id,
        "event_type": first_event.event_type,
        "event_time": first_event.event_time,
    }
    result = repository.execute(
        case_id=request["case_id"],
        operation="shipment",
        idempotency_key=request["idempotency_key"],
        request_body=request,
        event=first_event,
        expected_version=999,
        mutate=lambda _: pytest.fail("replay invoked callback"),
    )
    assert result.response == first.response


@pytest.mark.parametrize("changed", ["type", "time"])
def test_event_identity_different_content_conflicts_without_binding_key(repository, changed):
    event = EventRecord("event-a", "SHIPMENT_PICKED_UP", "2030-01-01T10:03:00Z")
    submit(repository, event=event)
    altered = (
        replace(event, event_type="SHIPMENT_DELIVERED")
        if changed == "type"
        else replace(event, event_time="2030-01-01T10:04:00Z")
    )
    before = counts(repository)
    with pytest.raises(IdempotencyConflict):
        submit(repository, key="other-key", event=altered)
    assert counts(repository) == before


def test_equivalent_event_instants_deduplicate_and_submicrosecond_order_is_exact(repository):
    event = EventRecord("event-a", "SHIPMENT_PICKED_UP", "2030-01-01T10:03:00.000000001Z")
    first = submit(repository, event=event)
    equivalent = replace(event, event_time="2030-01-01T18:03:00.0000000010+08:00")
    assert event_digest(event) == event_digest(equivalent)
    assert submit(repository, key="equivalent-key", event=equivalent).response == first.response
    older = EventRecord("event-b", "SHIPMENT_DELIVERED", "2030-01-01T10:03:00.000000000Z")
    with pytest.raises(LedgerConflict):
        submit(repository, key="older-key", event=older)
    assert time_order(event.event_time) > time_order(older.event_time)


def test_equal_time_event_allowed_storage_does_not_decide_transition(repository):
    first = EventRecord("event-a", "SHIPMENT_DELIVERED", INSTANT)
    submit(repository, event=first)
    second = replace(first, event_id="event-b", event_type="SHIPMENT_PICKED_UP")
    submit(repository, key="second-event", event=second)
    assert repository.load("9007199254740993").version == 2
    assert repository.event_history("9007199254740993") == (first, second)


@pytest.mark.parametrize("table", TABLES)
def test_database_write_failure_rolls_back_every_table(repository, table):
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            f"CREATE TRIGGER fail_write BEFORE INSERT ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'injected write failure'); END"
        )
    event = EventRecord("event-a", "SHIPMENT_PICKED_UP", INSTANT)
    with pytest.raises(LedgerUnavailable):
        submit(repository, event=event)
    assert counts(repository) == dict.fromkeys(TABLES, 0)
    assert repository.load("9007199254740993") is None
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute("DROP TRIGGER fail_write")
    submit(repository, event=event)
    assert counts(repository) == dict.fromkeys(TABLES, 1)


def test_failed_update_retains_preexisting_state_and_audit(repository):
    first = submit(repository)
    before = counts(repository)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_write BEFORE INSERT ON idempotent_requests "
            "BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(LedgerUnavailable):
        submit(repository, key="second-key", request_id="second")
    assert repository.load("9007199254740993") == first.snapshot
    assert counts(repository) == before


def test_callback_exception_rolls_back_and_key_remains_retryable(repository):
    request = body()

    def reject(current):
        mutate(current)
        raise ValueError("synthetic stale candidate")

    with pytest.raises(ValueError, match="stale"):
        repository.execute(
            case_id=request["case_id"],
            operation="approve",
            idempotency_key=request["idempotency_key"],
            request_body=request,
            mutate=reject,
        )
    assert counts(repository) == dict.fromkeys(TABLES, 0)
    assert not submit(repository).replayed


def test_optimistic_save_and_append_only_history(repository):
    proposed = mutate(None).snapshot
    saved = repository.save(proposed, expected_version=None)
    assert saved.version == 1 and saved.event_high_watermark == INSTANT
    with pytest.raises(LedgerConflict):
        repository.save(proposed, expected_version=None)
    with pytest.raises(LedgerConflict):
        repository.save(
            replace(saved, event_high_watermark="2020-01-01T00:00:00Z"), expected_version=1
        )
    erased = saved.accountability_state.model_copy(update={"audit_trail": []})
    with pytest.raises(LedgerConflict):
        repository.save(replace(saved, accountability_state=erased), expected_version=1)
    assert repository.load_version(saved.case_id, 1) == saved


def test_compiled_commitments_and_terminal_null_survive_snapshot_and_response(repository):
    first = submit(repository)
    payload = first.snapshot.accountability_state.to_contract()
    payload["case_status"] = "RESOLVED"
    payload["service_progress_receipt"]["status"] = "COMPLETED"
    payload["service_progress_receipt"]["next_update_by"] = None
    payload["audit_trail"].append(
        AuditEntry(
            at="2030-01-01T10:03:00Z",
            actor="test-actor",
            action="SHIPMENT_DELIVERED",
            changed_fields=["service_progress_receipt"],
            request_id="terminal-request",
        ).model_dump(mode="json")
    )
    terminal = StoredAccountabilityState.from_contract(payload)
    compiled = CompiledCommitments(
        (CompiledCommitment("test promise", "STANDARD_APPROVED", "ACTIVE", INSTANT, INSTANT),), True
    )
    snapshot = replace(first.snapshot, accountability_state=terminal, compiled_commitments=compiled)
    assert (
        decode_snapshot(
            encode_snapshot(snapshot)
        ).accountability_state.service_progress_receipt.next_update_by
        is None
    )
    request = body(key="terminal-request-key")
    response_body = {
        **first.response.body,
        "data": {
            **first.response.body["data"],
            "accountability_state": terminal.to_contract(),
            "audit_trail": payload["audit_trail"],
        },
        "request_id": "terminal-request",
    }
    result = repository.execute(
        case_id=request["case_id"],
        operation="approve",
        idempotency_key=request["idempotency_key"],
        request_body=request,
        expected_version=1,
        mutate=lambda _: Mutation(snapshot, StoredResponse(response_body)),
    )
    saved = result.snapshot
    reopened = SQLiteLedgerRepository(repository.db_path)
    assert reopened.load(saved.case_id).compiled_commitments == compiled
    assert reopened.load(saved.case_id).accountability_state.to_contract() == terminal.to_contract()
    replay = reopened.execute(
        case_id=request["case_id"],
        operation="approve",
        idempotency_key=request["idempotency_key"],
        request_body=request,
        mutate=lambda _: pytest.fail("terminal replay called callback"),
    )
    assert replay.response == result.response
    assert (
        replay.response.body["data"]["accountability_state"]["service_progress_receipt"][
            "next_update_by"
        ]
        is None
    )


def test_stale_expected_version_rejected_before_callback(repository):
    first = submit(repository)
    request = body(key="stale-key-0001")
    with pytest.raises(LedgerConflict):
        repository.execute(
            case_id=request["case_id"],
            operation="approve",
            idempotency_key=request["idempotency_key"],
            request_body=request,
            expected_version=99,
            mutate=lambda _: pytest.fail("stale callback called"),
        )
    assert repository.load(first.snapshot.case_id) == first.snapshot


def test_callback_cannot_rewrite_existing_audit_through_mutable_nested_list(repository):
    first = submit(repository)
    request = body(key="rewrite-key-0001")

    def malicious(current):
        current.accountability_state.audit_trail.clear()
        return mutate(current, request_id="replacement")

    with pytest.raises(LedgerConflict):
        repository.execute(
            case_id=request["case_id"],
            operation="approve",
            idempotency_key=request["idempotency_key"],
            request_body=request,
            mutate=malicious,
        )
    assert repository.load(first.snapshot.case_id) == first.snapshot


def worker_command(db, mode="replay", request_id="child-request"):
    return [sys.executable, "-m", "backend.tests.storage.process_worker", mode, str(db), request_id]


def test_separate_process_restart_replays_first_response(repository):
    first = submit(repository)
    process = subprocess.run(
        worker_command(repository.db_path),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    result = json.loads(process.stdout)
    assert result["replayed"] and result["response"] == first.response.body
    assert result["headers"] == first.response.headers


def test_separate_process_double_click_commits_once(repository):
    clients = [
        subprocess.Popen(
            worker_command(repository.db_path, request_id=f"child-{index}"),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for index in range(2)
    ]
    results = []
    for client in clients:
        out, err = client.communicate(timeout=30)
        assert client.returncode == 0, err
        results.append(json.loads(out))
    assert sum(not result["replayed"] for result in results) == 1
    assert results[0]["response"] == results[1]["response"]
    assert counts(repository) == {**dict.fromkeys(TABLES, 1), "events": 0}


def test_process_death_between_state_and_response_write_recovers_empty_transaction(repository):
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "CREATE TRIGGER kill_write BEFORE INSERT ON idempotent_requests "
            "BEGIN SELECT crash_process(); END"
        )
    process = subprocess.run(
        worker_command(repository.db_path, mode="crash"), cwd=ROOT, capture_output=True, timeout=30
    )
    assert process.returncode == 17
    reopened = SQLiteLedgerRepository(repository.db_path)
    assert counts(reopened) == dict.fromkeys(TABLES, 0)
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute("DROP TRIGGER kill_write")
    assert not submit(reopened).replayed


@pytest.mark.parametrize("kind", ["future", "unidentified"])
def test_unsupported_database_is_refused_without_reset(tmp_path, kind):
    db = tmp_path / "ledger.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE user_content (text TEXT)")
        connection.execute("INSERT INTO user_content VALUES ('preserve')")
        if kind == "future":
            connection.execute("PRAGMA user_version=99")
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    with pytest.raises(LedgerUnavailable):
        SQLiteLedgerRepository(db)
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT text FROM user_content").fetchone()[0] == "preserve"
