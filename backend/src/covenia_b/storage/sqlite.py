"""SQLite LedgerRepository with one serialized service transaction per mutation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from covenia_b.domain.types import AuditEntry, LedgerSnapshot
from covenia_b.ports.errors import LedgerConflict, LedgerUnavailable
from covenia_b.storage.codec import (
    canonical_json,
    decode_response,
    decode_snapshot,
    encode_response,
    encode_snapshot,
    event_digest,
    request_digest,
    time_order,
)
from covenia_b.storage.models import (
    EventRecord,
    IdempotencyConflict,
    Mutation,
    TransactionResult,
)
from covenia_b.storage.schema import initialize


class SQLiteLedgerRepository:
    """Connections are operation-local; BEGIN IMMEDIATE precedes reads and callbacks.

    Callback code owns business validation and must avoid external side effects.
    ``save`` supports the frozen port for initialization/re-analysis; approve and
    shipment services must use ``execute`` for atomic first-response persistence.
    """

    def __init__(self, db_path: str | Path, *, timeout: float = 10.0) -> None:
        path = Path(db_path)
        if not path.is_absolute() or str(db_path) == ":memory:":
            raise LedgerUnavailable("an explicit absolute local database path is required")
        self.db_path = path.resolve()
        self.timeout = timeout
        with self._connection() as connection:
            try:
                initialize(connection)
            except ValueError as exc:
                raise LedgerUnavailable("unsupported ledger database") from exc
            connection.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = None
        try:
            connection = sqlite3.connect(
                self.db_path, timeout=self.timeout, isolation_level=None, uri=True
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except sqlite3.Error as exc:
            raise LedgerUnavailable("local ledger operation failed") from exc
        finally:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()

    @staticmethod
    def _decode(encoded: str) -> LedgerSnapshot:
        try:
            return decode_snapshot(encoded)
        except (ValueError, TypeError, KeyError) as exc:
            raise LedgerUnavailable("invalid persisted snapshot") from exc

    def _load(self, connection: sqlite3.Connection, case_id: str) -> LedgerSnapshot | None:
        row = connection.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            return None
        snapshot = self._decode(row["snapshot_json"])
        if (snapshot.case_id, snapshot.version, snapshot.event_high_watermark) != (
            row["case_id"],
            row["version"],
            row["event_high_watermark"],
        ):
            raise LedgerUnavailable("inconsistent persisted snapshot metadata")
        return snapshot

    def load(self, case_id: str) -> LedgerSnapshot | None:
        with self._connection() as connection:
            return self._load(connection, case_id)

    def load_version(self, case_id: str, version: int) -> LedgerSnapshot | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM case_versions WHERE case_id=? AND version=?",
                (case_id, version),
            ).fetchone()
            return self._decode(row[0]) if row is not None else None

    def audit_history(self, case_id: str) -> tuple[AuditEntry, ...]:
        import json

        with self._connection() as connection:
            rows = connection.execute(
                "SELECT entry_json FROM audit_entries WHERE case_id=? ORDER BY sequence", (case_id,)
            ).fetchall()
            try:
                return tuple(AuditEntry.model_validate(json.loads(row[0])) for row in rows)
            except (ValueError, TypeError) as exc:
                raise LedgerUnavailable("invalid persisted audit history") from exc

    def event_history(self, case_id: str) -> tuple[EventRecord, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT event_id,event_type,event_time FROM events "
                "WHERE case_id=? ORDER BY version",
                (case_id,),
            ).fetchall()
            return tuple(EventRecord(*row) for row in rows)

    def save(self, snapshot: LedgerSnapshot, *, expected_version: int | None) -> LedgerSnapshot:
        with self._connection(write=True) as connection:
            current = self._load(connection, snapshot.case_id)
            actual = current.version if current is not None else None
            if actual != expected_version:
                raise LedgerConflict("ledger version changed")
            return self._persist(connection, current, snapshot)

    def execute(
        self,
        *,
        case_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, Any],
        mutate: Callable[[LedgerSnapshot | None], Mutation],
        event: EventRecord | None = None,
        expected_version: int | None = None,
    ) -> TransactionResult:
        """Replays precede version/time checks; different operations conflict on a case key.

        ``expected_version`` optionally guards a precomputed candidate. A callback
        always receives the locked current state, including on first initialization.
        Events are explicit service facts and must match the shipment request fields.
        """

        if not all(isinstance(s, str) and s.strip() for s in (case_id, operation, idempotency_key)):
            raise LedgerUnavailable("case, operation and idempotency key are required")
        if operation not in {"analyze", "evaluate", "approve", "shipment"}:
            raise LedgerUnavailable("unknown operation name")
        if (
            request_body.get("case_id") != case_id
            or request_body.get("idempotency_key") != idempotency_key
        ):
            raise LedgerUnavailable("request identity does not match transaction identity")
        if event is not None:
            if (
                not event.event_id
                or not event.event_type
                or any(
                    request_body.get(name) != getattr(event, name)
                    for name in ("event_id", "event_type", "event_time")
                )
            ):
                raise LedgerUnavailable("event does not match request")
            event_fingerprint = event_digest(event)
        else:
            event_fingerprint = None
        digest = request_digest(operation, request_body)
        with self._connection(write=True) as connection:
            request = connection.execute(
                "SELECT * FROM idempotent_requests WHERE case_id=? AND idempotency_key=?",
                (case_id, idempotency_key),
            ).fetchone()
            if request is not None:
                if request["digest"] != digest:
                    raise IdempotencyConflict("case key has different request content")
                return self._replay(connection, request, "request")
            if (operation == "shipment") != (event is not None):
                raise LedgerUnavailable("shipment requires its explicit event record")
            if event is not None:
                prior_event = connection.execute(
                    "SELECT * FROM events WHERE case_id=? AND event_id=?", (case_id, event.event_id)
                ).fetchone()
                if prior_event is not None:
                    if prior_event["digest"] != event_fingerprint:
                        raise IdempotencyConflict("event identity has different content")
                    # Bind the new request key to the same first response atomically.
                    connection.execute(
                        "INSERT INTO idempotent_requests VALUES (?,?,?,?,?,?)",
                        (
                            case_id,
                            idempotency_key,
                            operation,
                            digest,
                            prior_event["version"],
                            prior_event["response_json"],
                        ),
                    )
                    return self._replay(connection, prior_event, "event")
            current = self._load(connection, case_id)
            if expected_version is not None and (
                current is None or current.version != expected_version
            ):
                raise LedgerConflict("ledger version changed")
            if (
                event is not None
                and current is not None
                and current.event_high_watermark is not None
                and time_order(event.event_time) < time_order(current.event_high_watermark)
            ):
                raise LedgerConflict("event time is below the persisted high-water mark")
            # A callback cannot mutate the baseline used for append-only comparisons.
            callback_state = self._decode(encode_snapshot(current)) if current is not None else None
            mutation = mutate(callback_state)
            if mutation.snapshot.case_id != case_id:
                raise LedgerConflict("mutation changed case identity")
            response_json = encode_response(mutation.response)
            saved = self._persist(connection, current, mutation.snapshot, event=event)
            if event is not None:
                connection.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                    (
                        case_id,
                        event.event_id,
                        event_fingerprint,
                        event.event_type,
                        event.event_time,
                        saved.version,
                        response_json,
                    ),
                )
            connection.execute(
                "INSERT INTO idempotent_requests VALUES (?,?,?,?,?,?)",
                (case_id, idempotency_key, operation, digest, saved.version, response_json),
            )
            return TransactionResult(saved, decode_response(response_json), False)

    def _replay(
        self, connection: sqlite3.Connection, row: sqlite3.Row, source: str
    ) -> TransactionResult:
        version = connection.execute(
            "SELECT snapshot_json FROM case_versions WHERE case_id=? AND version=?",
            (row["case_id"], row["version"]),
        ).fetchone()
        if version is None:
            raise LedgerUnavailable("replay snapshot is missing")
        try:
            response = decode_response(row["response_json"])
        except (ValueError, TypeError, KeyError) as exc:
            raise LedgerUnavailable("invalid persisted response") from exc
        return TransactionResult(self._decode(version[0]), response, True, source)

    def _persist(
        self,
        connection: sqlite3.Connection,
        current: LedgerSnapshot | None,
        proposed: LedgerSnapshot,
        *,
        event: EventRecord | None = None,
    ) -> LedgerSnapshot:
        version = current.version if current is not None else 0
        if type(proposed.version) is not int or proposed.version != version:
            raise LedgerConflict("proposed snapshot must carry the current version (new: 0)")
        if not isinstance(proposed.case_id, str) or not proposed.case_id.strip():
            raise LedgerConflict("snapshot case identity is required")
        state = proposed.accountability_state
        if state is not None and state.case_id != proposed.case_id:
            raise LedgerConflict("state case identity differs from snapshot")
        previous_audit = (
            current.accountability_state.audit_trail
            if current is not None and current.accountability_state is not None
            else []
        )
        audit = state.audit_trail if state is not None else []
        old_entries = [entry.model_dump(mode="json") for entry in previous_audit]
        entries = [entry.model_dump(mode="json") for entry in audit]
        if entries[: len(old_entries)] != old_entries:
            raise LedgerConflict("audit history must be append-only")
        if current is not None and current.accountability_state is not None and state is None:
            raise LedgerConflict("cannot discard persisted accountability state")
        high = proposed.event_high_watermark
        old_high = current.event_high_watermark if current is not None else None
        if old_high is not None and (high is None or time_order(high) < time_order(old_high)):
            raise LedgerConflict("snapshot high-water mark cannot regress")
        if (
            state is not None
            and len(entries) == len(old_entries)
            and (
                current is None
                or state != current.accountability_state
                or proposed.compiled_commitments != current.compiled_commitments
            )
        ):
            raise LedgerConflict("changed state or commitments require an appended audit entry")
        for entry in audit[len(old_entries) :]:
            if old_high is not None and time_order(entry.at) < time_order(old_high):
                raise LedgerConflict("new audit time is below the persisted high-water mark")
        instants = [
            stamp
            for stamp in (old_high, high, event.event_time if event else None)
            if stamp is not None
        ]
        instants.extend(entry.at for entry in audit)
        watermark = max(instants, key=time_order) if instants else None
        saved = replace(proposed, version=version + 1, event_high_watermark=watermark)
        encoded = encode_snapshot(saved)
        connection.execute(
            "INSERT INTO cases VALUES (?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET "
            "version=excluded.version,event_high_watermark=excluded.event_high_watermark,"
            "snapshot_json=excluded.snapshot_json",
            (saved.case_id, saved.version, saved.event_high_watermark, encoded),
        )
        connection.execute(
            "INSERT INTO case_versions VALUES (?,?,?)", (saved.case_id, saved.version, encoded)
        )
        for index, entry in enumerate(entries[len(old_entries) :], start=len(old_entries)):
            connection.execute(
                "INSERT INTO audit_entries VALUES (?,?,?,?)",
                (saved.case_id, index, saved.version, canonical_json(entry)),
            )
        return self._decode(encoded)
