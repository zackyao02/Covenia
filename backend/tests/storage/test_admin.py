from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest
from backend.tests.storage.support import ROOT, submit

from covenia_b.ports.errors import LedgerUnavailable
from covenia_b.storage import SQLiteLedgerRepository
from covenia_b.storage.admin import backup_database, restore_database


def test_backup_includes_live_wal_and_restore_preserves_replay(tmp_path):
    repo = SQLiteLedgerRepository(tmp_path / "ledger.db")
    with sqlite3.connect(repo.db_path) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM cases").fetchall()
        first = submit(repo)
        assert (tmp_path / "ledger.db-wal").exists()
        backup = backup_database(repo.db_path, tmp_path / "backup.db")
        reader.rollback()
    submit(repo, key="second-key", request_id="second")
    restore_database(repo.db_path, backup, before_restore=tmp_path / "before-restore.db")
    assert repo.load(first.snapshot.case_id) == first.snapshot
    assert submit(repo).response == first.response
    previous = SQLiteLedgerRepository(tmp_path / "before-restore.db")
    assert previous.load(first.snapshot.case_id).version == 2
    restored = tmp_path / "new-ledger.db"
    restore_database(restored, backup)
    assert SQLiteLedgerRepository(restored).load(first.snapshot.case_id) == first.snapshot


def test_restore_insert_failure_keeps_original_transaction(tmp_path):
    repo = SQLiteLedgerRepository(tmp_path / "ledger.db")
    submit(repo)
    backup = backup_database(repo.db_path, tmp_path / "backup.db")
    second = submit(repo, key="second-key", request_id="second")
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_restore BEFORE INSERT ON cases "
            "BEGIN SELECT RAISE(ABORT, 'injected restore failure'); END"
        )
    with pytest.raises(LedgerUnavailable):
        restore_database(repo.db_path, backup, before_restore=tmp_path / "safe.db")
    assert repo.load(second.snapshot.case_id) == second.snapshot
    assert (tmp_path / "safe.db").exists()


def test_existing_target_requires_new_safety_backup_and_backup_never_overwrites(tmp_path):
    repo = SQLiteLedgerRepository(tmp_path / "ledger.db")
    first = submit(repo)
    backup = backup_database(repo.db_path, tmp_path / "backup.db")
    original = backup.read_bytes()
    with pytest.raises(ValueError):
        backup_database(repo.db_path, backup)
    with pytest.raises(ValueError):
        restore_database(repo.db_path, backup)
    with pytest.raises(ValueError):
        restore_database(repo.db_path, backup, before_restore=backup)
    assert backup.read_bytes() == original and repo.load(first.snapshot.case_id) == first.snapshot


@pytest.mark.parametrize("kind", ["same", "hardlink", "sidecar", "relative", "missing"])
def test_unsafe_admin_paths_are_rejected(tmp_path, kind):
    repo = SQLiteLedgerRepository(tmp_path / "ledger.db")
    if kind == "same":
        target = repo.db_path
    elif kind == "hardlink":
        target = tmp_path / "alias.db"
        target.hardlink_to(repo.db_path)
    elif kind == "sidecar":
        target = tmp_path / "ledger.db-wal"
    elif kind == "relative":
        target = "relative.db"
    else:
        with pytest.raises(ValueError):
            backup_database(tmp_path / "missing.db", tmp_path / "out.db")
        return
    with pytest.raises(ValueError):
        backup_database(repo.db_path, target)


def test_bad_backup_does_not_touch_target_or_create_new_db(tmp_path):
    bad = tmp_path / "bad.db"
    with sqlite3.connect(bad) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    repo = SQLiteLedgerRepository(tmp_path / "ledger.db")
    first = submit(repo)
    with pytest.raises(ValueError):
        restore_database(repo.db_path, bad, before_restore=tmp_path / "safe.db")
    assert repo.load(first.snapshot.case_id) == first.snapshot
    assert not (tmp_path / "safe.db").exists()
    with pytest.raises(ValueError):
        restore_database(tmp_path / "new.db", bad)
    assert not (tmp_path / "new.db").exists()


def test_actual_local_admin_cli_requires_explicit_paths_and_roundtrips(tmp_path):
    db = tmp_path / "ledger.db"
    repo = SQLiteLedgerRepository(db)
    first = submit(repo)
    prefix = [sys.executable, "-m", "covenia_b.storage.admin"]
    backup = tmp_path / "backup.db"
    commands = [
        [*prefix, "backup", "--db", str(db), "--backup", str(backup)],
        [*prefix, "restore", "--db", str(tmp_path / "restored.db"), "--backup", str(backup)],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    assert (
        SQLiteLedgerRepository(tmp_path / "restored.db").load(first.snapshot.case_id)
        == first.snapshot
    )
    missing_paths = subprocess.run([*prefix, "restore"], cwd=ROOT, capture_output=True, timeout=30)
    assert missing_paths.returncode != 0
