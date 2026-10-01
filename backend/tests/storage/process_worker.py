"""Actual separate-process replay and crash-at-response-write test driver."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager

from backend.tests.storage.support import submit

from covenia_b.storage import SQLiteLedgerRepository


class CrashRepository(SQLiteLedgerRepository):
    @contextmanager
    def _connection(self, *, write=False):
        with super()._connection(write=write) as connection:
            if write:
                connection.create_function("crash_process", 0, lambda: os._exit(17))
            yield connection


def main():
    mode, db, request_id = sys.argv[1:]
    repository = CrashRepository(db) if mode == "crash" else SQLiteLedgerRepository(db)
    result = submit(repository, request_id=request_id)
    print(
        json.dumps(
            {
                "replayed": result.replayed,
                "version": result.snapshot.version,
                "response": result.response.body,
                "headers": result.response.headers,
            }
        )
    )


if __name__ == "__main__":
    main()
