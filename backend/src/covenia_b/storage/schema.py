"""Transactional, additive schema initialization. Unknown versions are refused."""

from __future__ import annotations

import sqlite3

APPLICATION_ID = 0x434F5642
SCHEMA_VERSION = 1
TABLES = ("cases", "case_versions", "audit_entries", "events", "idempotent_requests")
DDL = (
    """CREATE TABLE cases (
        case_id TEXT PRIMARY KEY, version INTEGER NOT NULL CHECK(version >= 1),
        event_high_watermark TEXT, snapshot_json TEXT NOT NULL)""",
    """CREATE TABLE case_versions (
        case_id TEXT NOT NULL REFERENCES cases(case_id), version INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL, PRIMARY KEY(case_id, version))""",
    """CREATE TABLE audit_entries (
        case_id TEXT NOT NULL, sequence INTEGER NOT NULL, version INTEGER NOT NULL,
        entry_json TEXT NOT NULL, PRIMARY KEY(case_id, sequence),
        FOREIGN KEY(case_id, version) REFERENCES case_versions(case_id, version))""",
    """CREATE TABLE events (
        case_id TEXT NOT NULL, event_id TEXT NOT NULL, digest TEXT NOT NULL,
        event_type TEXT NOT NULL, event_time TEXT NOT NULL, version INTEGER NOT NULL,
        response_json TEXT NOT NULL, PRIMARY KEY(case_id, event_id),
        FOREIGN KEY(case_id, version) REFERENCES case_versions(case_id, version))""",
    """CREATE TABLE idempotent_requests (
        case_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, operation TEXT NOT NULL,
        digest TEXT NOT NULL, version INTEGER NOT NULL, response_json TEXT NOT NULL,
        PRIMARY KEY(case_id, idempotency_key),
        FOREIGN KEY(case_id, version) REFERENCES case_versions(case_id, version))""",
)


def validate_schema(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise ValueError("unsupported database schema version")
    if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ValueError("not a Covenia ledger database")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != set(TABLES):
        raise ValueError("unexpected ledger tables")


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            objects = connection.execute("SELECT name FROM sqlite_master").fetchall()
            if objects or connection.execute("PRAGMA application_id").fetchone()[0] != 0:
                raise ValueError("refusing to migrate an unidentified database")
            for statement in DDL:
                connection.execute(statement)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        validate_schema(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
