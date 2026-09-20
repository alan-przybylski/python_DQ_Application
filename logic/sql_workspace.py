"""Bounded, cancellable previews using the same dataset access rules as DQ."""

import sqlite3
import time
from dataclasses import dataclass

from config.i18n import AppError
from database.connection import get_connection
from logic.datasets import list_tables


@dataclass
class Preview:
    columns: list
    rows: list
    truncated: bool
    seconds: float


def preview_query(sql, cancel, database=None, limit=500, timeout=10):
    if not sql.strip():
        raise AppError("Write a query first.")
    start = time.monotonic()
    connection = get_connection(database)
    try:
        connection.execute("PRAGMA busy_timeout=250")
        connection.execute("PRAGMA query_only=ON")
        tables = {name.casefold() for name in list_tables(connection)}
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

        def authorize(action, first, second, db, source):
            if action not in allowed:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and (first or "").casefold() not in tables:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (second or "").casefold() == "load_extension":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        connection.set_progress_handler(
            lambda: int(cancel.is_set() or time.monotonic() - start >= timeout), 1000
        )
        if cancel.is_set():
            raise AppError("Query cancelled.")
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(limit + 1)
        if cancel.is_set():
            raise AppError("Query cancelled.")
        return Preview([col[0] for col in cursor.description], rows[:limit],
                       len(rows) > limit, time.monotonic() - start)
    except sqlite3.Error as error:
        if cancel.is_set():
            raise AppError("Query cancelled.") from error
        if time.monotonic() - start >= timeout:
            raise AppError("Query exceeded the 10-second time limit.") from error
        raise AppError("SQL error: {detail}", detail=str(error)) from error
    finally:
        connection.close()
