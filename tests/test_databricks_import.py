from datetime import date, datetime
from decimal import Decimal
import threading

import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.databricks_import import (
    Source,
    Snapshot,
    download,
    local_columns,
    save_snapshot,
)


SOURCE = Source(
    "dbc-test.cloud.databricks.com",
    "/sql/1.0/warehouses/123abc",
    "workspace",
    "default",
    "customers",
)


class FakeCursor:
    def __init__(self, rows, description=None):
        self.rows = list(rows)
        self.description = description or [("id", "int"), ("name", "string")]
        self.queries = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def execute(self, sql):
        self.queries.append(sql)

    def fetchmany(self, size):
        result, self.rows = self.rows[:size], self.rows[size:]
        return result


class FakeConnection:
    def __init__(self, cursor):
        self.reader = cursor
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def cursor(self):
        return self.reader


def query(sql):
    connection = get_connection()
    try:
        with connection:
            return connection.execute(sql).fetchall()
    finally:
        connection.close()


def snapshot(rows=((7, "Ada"), (7, ""), (None, None))):
    return Snapshot(
        SOURCE, local_columns([("id", "int"), ("name", "string")]), list(rows)
    )


def test_read_only_download_quotes_identifiers_and_closes_handles():
    source = Source(
        SOURCE.hostname, SOURCE.http_path, "cat`alog", "schema", "orders; DROP TABLE x"
    )
    cursor = FakeCursor([(1, "Ada")])
    connection = FakeConnection(cursor)
    result = download(source, 20, connect=lambda _: connection)
    assert cursor.queries == [
        "SELECT * FROM `cat``alog`.`schema`.`orders; DROP TABLE x` LIMIT 21"
    ]
    assert result.rows == [(1, "Ada")]
    assert cursor.closed and connection.closed


def test_overflow_rejects_entire_download():
    cursor = FakeCursor([(1, "A"), (2, "B")])
    with pytest.raises(AppError, match="row limit"):
        download(SOURCE, 1, connect=lambda _: FakeConnection(cursor))
    assert cursor.closed


def test_cancel_before_connection():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AppError, match="cancelled"):
        download(
            SOURCE, cancel=cancel, connect=lambda _: pytest.fail("must not connect")
        )


def test_new_snapshot_preserves_duplicate_source_ids_null_and_empty(sqlite_database):
    count, backup = save_snapshot(snapshot(), "db_customers", "admin")
    assert count == 3 and backup is None
    assert query("SELECT * FROM db_customers") == [
        (1, 7, "Ada"),
        (2, 7, ""),
        (3, None, None),
    ]
    assert query("SELECT table_name,file_name,row_count FROM data_load_log") == [
        ("db_customers", SOURCE.reference, 3)
    ]


def test_refresh_has_backup_replaces_not_appends_and_keeps_history(sqlite_database):
    save_snapshot(snapshot(), "db_customers", "admin")
    query(
        "INSERT INTO dq_rules(id,version,rule_type,target_table,sql_query) VALUES(1,'1.0','test','db_customers','SELECT id,name,0 AS dq_check FROM db_customers')"
    )
    query(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.0',2,1)"
    )
    before = query("SELECT * FROM dq_results")
    count, backup = save_snapshot(
        snapshot([(10, "New")]), "db_customers", "admin", replace=True
    )
    assert count == 1 and backup.exists()
    assert query("SELECT * FROM db_customers") == [(1, 10, "New")]
    assert query("SELECT COUNT(*) FROM data_load_log") == [(2,)]
    assert query("SELECT * FROM dq_results") == before
    connection = get_connection(backup)
    try:
        assert connection.execute("SELECT COUNT(*) FROM db_customers").fetchone() == (
            3,
        )
    finally:
        connection.close()


def test_refresh_rejects_different_source_or_schema(sqlite_database):
    save_snapshot(snapshot(), "db_customers", "admin")
    changed = snapshot([(10, "New")])
    changed.source = Source(
        SOURCE.hostname, SOURCE.http_path, "workspace", "other", "customers"
    )
    with pytest.raises(AppError):
        save_snapshot(changed, "db_customers", "admin", replace=True)
    query("ALTER TABLE db_customers ADD COLUMN extra TEXT")
    with pytest.raises(AppError):
        save_snapshot(snapshot(), "db_customers", "admin", replace=True)
    assert query("SELECT COUNT(*) FROM db_customers") == [(3,)]
    assert query("SELECT COUNT(*) FROM data_load_log") == [(1,)]


def test_refresh_never_replaces_unrelated_table(sqlite_database):
    query("INSERT INTO customers(name) VALUES('Private')")
    with pytest.raises(AppError):
        save_snapshot(snapshot(), "customers", "admin", replace=True)
    assert query("SELECT name FROM customers") == [("Private",)]


def test_empty_source_is_explicitly_supported(sqlite_database):
    save_snapshot(snapshot([]), "db_customers", "admin")
    assert query("SELECT COUNT(*) FROM db_customers") == [(0,)]


def test_invalid_write_rolls_back_delete_and_log(sqlite_database):
    save_snapshot(snapshot(), "db_customers", "admin")
    with pytest.raises(Exception):
        save_snapshot(snapshot([(2**70, "Bad")]), "db_customers", "admin", replace=True)
    assert query("SELECT COUNT(*) FROM db_customers") == [(3,)]
    assert query("SELECT COUNT(*) FROM data_load_log") == [(1,)]


def test_decimal_dates_and_mapping_are_lossless():
    description = [
        ("id", "int"),
        ("source_id", "string"),
        ("Amount €", "decimal"),
        ("day", "date"),
        ("time", "timestamp"),
    ]
    cursor = FakeCursor(
        [
            (
                1,
                "001",
                Decimal("12345678901234567890.0010"),
                date(2026, 9, 17),
                datetime(2026, 9, 17, 12, 30),
            )
        ],
        description,
    )
    result = download(SOURCE, connect=lambda _: FakeConnection(cursor))
    assert [c["name"] for c in result.columns] == [
        "source_id",
        "source_id_2",
        "Amount__",
        "day",
        "time",
    ]
    assert result.rows[0][2:] == (
        "12345678901234567890.0010",
        "2026-09-17",
        "2026-09-17T12:30:00",
    )


def test_error_does_not_expose_credentials():
    def fail(_):
        raise RuntimeError("Authorization: Bearer secret-token")

    with pytest.raises(AppError) as caught:
        download(SOURCE, connect=fail)
    assert "secret-token" not in str(caught.value)


@pytest.mark.parametrize(
    "host",
    [
        "http://test.databricks.com",
        "evil.example.com",
        "test.databricks.com.evil.com",
        "test.databricks.com:443",
        "user@test.databricks.com",
    ],
)
def test_invalid_host_does_not_connect(host):
    source = Source(host, SOURCE.http_path, "a", "b", "c")
    with pytest.raises(AppError):
        download(source, connect=lambda _: pytest.fail("must not connect"))


def test_unsupported_type_rejected():
    with pytest.raises(AppError):
        local_columns([("payload", "array")])


def test_sdk_connection_uses_browser_oauth_not_stored_credentials(monkeypatch):
    from databricks import sql
    from logic.databricks_import import connect_source

    captured = {}
    monkeypatch.setattr(sql, "connect", lambda **kwargs: captured.update(kwargs))
    connect_source(SOURCE)
    assert captured["auth_type"] == "databricks-oauth"
    assert captured["server_hostname"] == SOURCE.hostname
    assert (
        "access_token" not in captured
        and "experimental_oauth_persistence" not in captured
    )


def test_memory_limit_rejects_download(monkeypatch):
    import logic.databricks_import as module

    monkeypatch.setattr(module, "MAX_BYTES", 100)
    cursor = FakeCursor([(None, None)])
    with pytest.raises(AppError, match="50 MB"):
        download(SOURCE, connect=lambda _: FakeConnection(cursor))


def test_failed_new_import_does_not_leave_partial_table(sqlite_database):
    with pytest.raises(Exception):
        save_snapshot(snapshot([(2**70, "Bad")]), "new_snapshot", "admin")
    assert not query("SELECT name FROM sqlite_master WHERE name='new_snapshot'")
    assert query("SELECT COUNT(*) FROM data_load_log") == [(0,)]
