"""Local-only online backup and transactional restore: python -m covenia_b.storage.admin."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from covenia_b.ports.errors import LedgerUnavailable
from covenia_b.storage.schema import TABLES, validate_schema
from covenia_b.storage.sqlite import SQLiteLedgerRepository


def _path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("explicit absolute paths are required")
    return path.resolve()


def _distinct(*paths: Path) -> None:
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if first == second or (
                first.exists() and second.exists() and os.path.samefile(first, second)
            ):
                raise ValueError("database and backup paths must be distinct")
            if str(second) in {str(first) + "-wal", str(first) + "-shm", str(first) + "-journal"}:
                raise ValueError("a database sidecar cannot be a backup path")
            if str(first) in {str(second) + "-wal", str(second) + "-shm", str(second) + "-journal"}:
                raise ValueError("a database sidecar cannot be a backup path")


def _validate(connection: sqlite3.Connection) -> None:
    validate_schema(connection)
    if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise ValueError("backup integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("backup referential integrity check failed")


def backup_database(db_path: str | Path, backup_path: str | Path) -> Path:
    """Copy a committed SQLite snapshot including WAL; never overwrite a backup."""

    db, backup = _path(db_path), _path(backup_path)
    _distinct(db, backup)
    if not db.is_file() or backup.exists():
        raise ValueError("database must exist and backup destination must be new")
    with tempfile.TemporaryDirectory(prefix="b18-backup-", dir=backup.parent) as directory:
        staging = Path(directory) / "snapshot.db"
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as source:
            _validate(source)
            with closing(sqlite3.connect(staging)) as target:
                source.backup(target)
                _validate(target)
        # link is an atomic no-overwrite publication on the local filesystem.
        os.link(staging, backup)
    return backup


def restore_database(
    db_path: str | Path, backup_path: str | Path, *, before_restore: str | Path | None = None
) -> Path:
    """Replace owned rows in one write transaction; open connections remain usable.

    Existing targets require a new safety-backup path. The pre-restore backup is
    taken while the target write lock is held; a failure leaves target rows intact.
    Run maintenance with application writers stopped to avoid later stale writes.
    """

    db, backup = _path(db_path), _path(backup_path)
    safety = _path(before_restore) if before_restore is not None else None
    _distinct(*(path for path in (db, backup, safety) if path is not None))
    if db.exists() and safety is None:
        raise ValueError("existing target requires an explicit before-restore backup path")
    if safety is not None and safety.exists():
        raise ValueError("before-restore destination must be new")
    # First make and validate a private stable snapshot, before touching the target.
    with tempfile.TemporaryDirectory(prefix="b18-restore-", dir=db.parent) as directory:
        staging = Path(directory) / "snapshot.db"
        backup_database(backup, staging)
        repository = SQLiteLedgerRepository(db)
        with repository._connection(write=True) as target:
            if safety is not None:
                backup_database(db, safety)
            target.execute("ATTACH DATABASE ? AS restore_source", (staging.as_uri() + "?mode=ro",))
            for table in reversed(TABLES):
                target.execute(f"DELETE FROM main.{table}")
            for table in TABLES:
                target.execute(f"INSERT INTO main.{table} SELECT * FROM restore_source.{table}")
            if target.execute("PRAGMA main.foreign_key_check").fetchone() is not None:
                raise ValueError("restored rows failed referential integrity")
    return db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Covenia ledger backup/restore only")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("backup", "restore"):
        command = commands.add_parser(name)
        command.add_argument("--db", required=True)
        command.add_argument("--backup", required=True)
        if name == "restore":
            command.add_argument("--before-restore")
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            backup_database(args.db, args.backup)
        else:
            restore_database(args.db, args.backup, before_restore=args.before_restore)
    except (ValueError, OSError, sqlite3.Error, LedgerUnavailable) as exc:
        print(f"local maintenance failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(f"{args.command} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
