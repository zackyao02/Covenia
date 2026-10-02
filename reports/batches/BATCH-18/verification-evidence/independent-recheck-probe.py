"""Independent BATCH-18 acceptance probe; deliberately does not invoke pytest."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

from covenia_b.domain.types import AccountabilityState, AuditEntry, CompiledCommitments, LedgerSnapshot
from covenia_b.ports.errors import LedgerUnavailable
from covenia_b.storage import IdempotencyConflict, Mutation, SQLiteLedgerRepository, StoredResponse
from covenia_b.storage.schema import TABLES


CASE_ID = "independent-b18-case"
INSTANT = "2030-01-01T18:02:00+08:00"


def counts(repository: SQLiteLedgerRepository) -> dict[str, int]:
    connection = sqlite3.connect(repository.db_path)
    try:
        return {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
    finally:
        connection.close()


def proposal(current: LedgerSnapshot | None, *, request_id: str) -> Mutation:
    vector_path = Path(__file__).resolve().parents[4] / "tests/contract-vectors/approve.json"
    response = json.loads(vector_path.read_text(encoding="utf-8"))["vectors"][0]["response"]
    if current is None:
        payload = response["data"]["accountability_state"]
        payload["case_id"] = CASE_ID
        payload["audit_trail"] = []
        state = AccountabilityState.from_contract(payload)
        current = LedgerSnapshot(CASE_ID, 0, None, state, CompiledCommitments((), True))
    assert current.accountability_state is not None
    entry = AuditEntry(
        at=INSTANT,
        actor="independent-verifier",
        action="RESOLUTION_APPROVED",
        changed_fields=["open_obligation"],
        request_id=request_id,
    )
    state = current.accountability_state.model_copy(
        update={"audit_trail": [*current.accountability_state.audit_trail, entry]}
    )
    response["data"]["accountability_state"] = state.to_contract()
    response["data"]["audit_trail"] = [item.model_dump(mode="json") for item in state.audit_trail]
    response["request_id"] = request_id
    return Mutation(
        replace(current, accountability_state=state),
        StoredResponse(response, 200, {"X-Request-Id": request_id}),
    )


def submit(
    repository: SQLiteLedgerRepository,
    *,
    key: str,
    request_id: str,
    actor: str = "independent-verifier",
    calls: list[str] | None = None,
):
    request = {
        "case_id": CASE_ID,
        "idempotency_key": key,
        "approver_id": actor,
        "candidate_type": "CHECK_REPLACEMENT_FULFILLMENT",
        "human_edits": {},
        # This top-level transport value must not change the request fingerprint.
        "request_id": request_id,
    }

    def mutate(current: LedgerSnapshot | None) -> Mutation:
        if calls is not None:
            calls.append(request_id)
        return proposal(current, request_id=request_id)

    return repository.execute(
        case_id=CASE_ID,
        operation="approve",
        idempotency_key=key,
        request_body=request,
        mutate=mutate,
    )


def run_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="b18-independent-", dir=Path(__file__).parent) as temporary:
        root = Path(temporary)

        # 1. Idempotency: ten repeats retain exactly one durable mutation and first response.
        replay_repository = SQLiteLedgerRepository(root / "replay.db")
        replay_calls: list[str] = []
        first = submit(replay_repository, key="replay-key", request_id="first", calls=replay_calls)
        replays = [
            submit(replay_repository, key="replay-key", request_id=f"replay-{index}", calls=replay_calls)
            for index in range(10)
        ]
        assert len(replay_calls) == 1
        assert all(result.replayed and result.response == first.response for result in replays)
        assert counts(replay_repository) == {"cases": 1, "case_versions": 1, "audit_entries": 1, "events": 0, "idempotent_requests": 1}

        # 2. Conflict: same case/key with changed request does not change durable state.
        before_conflict = counts(replay_repository)
        try:
            submit(
                replay_repository,
                key="replay-key",
                request_id="conflict",
                actor="different-actor",
                calls=replay_calls,
            )
        except IdempotencyConflict:
            pass
        else:
            raise AssertionError("same key with changed body did not conflict")
        assert counts(replay_repository) == before_conflict
        assert replay_repository.load(CASE_ID) == first.snapshot

        # 3. Rollback: failure at final response/idempotency write leaves no partial snapshot/audit.
        rollback_repository = SQLiteLedgerRepository(root / "rollback.db")
        connection = sqlite3.connect(rollback_repository.db_path)
        try:
            connection.execute(
                "CREATE TRIGGER abort_request BEFORE INSERT ON idempotent_requests "
                "BEGIN SELECT RAISE(ABORT, 'independent injected failure'); END"
            )
            connection.commit()
        finally:
            connection.close()
        try:
            submit(rollback_repository, key="rollback-key", request_id="rollback")
        except LedgerUnavailable:
            pass
        else:
            raise AssertionError("injected write failure unexpectedly committed")
        assert counts(rollback_repository) == dict.fromkeys(TABLES, 0)
        assert rollback_repository.load(CASE_ID) is None

        # 4. Restart recovery: a new repository instance reads persisted snapshot and returns first response.
        restarted = SQLiteLedgerRepository(replay_repository.db_path)
        restart_calls: list[str] = []
        recovered = submit(restarted, key="replay-key", request_id="after-restart", calls=restart_calls)
        assert recovered.replayed and recovered.response == first.response
        assert recovered.snapshot == first.snapshot and restarted.load(CASE_ID) == first.snapshot
        assert restart_calls == []

        # 5. Concurrent transaction admission: ten callers execute the mutation exactly once.
        concurrent_repository = SQLiteLedgerRepository(root / "concurrent.db")
        barrier = Barrier(10)
        concurrent_calls: list[str] = []

        def worker(index: int):
            barrier.wait()
            return submit(
                concurrent_repository,
                key="concurrent-key",
                request_id=f"concurrent-{index}",
                calls=concurrent_calls,
            )

        with ThreadPoolExecutor(max_workers=10) as pool:
            concurrent_results = list(pool.map(worker, range(10)))
        assert len(concurrent_calls) == 1
        assert sum(not result.replayed for result in concurrent_results) == 1
        assert all(result.response == concurrent_results[0].response for result in concurrent_results)
        assert counts(concurrent_repository) == {"cases": 1, "case_versions": 1, "audit_entries": 1, "events": 0, "idempotent_requests": 1}

        return {
            "status": "PASS",
            "checks": {
                "idempotency_ten_replays": "PASS",
                "same_key_different_body_conflict": "PASS",
                "injected_write_rollback": "PASS",
                "restart_recovery": "PASS",
                "ten_concurrent_callers": "PASS",
            },
            "observed": {
                "replay_mutation_callback_count": len(replay_calls),
                "concurrent_mutation_callback_count": len(concurrent_calls),
                "replay_counts": counts(replay_repository),
                "concurrent_counts": counts(concurrent_repository),
            },
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_probe()
    except BaseException as error:
        result = {"status": "FAIL", "error_type": type(error).__name__, "error": str(error)}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
