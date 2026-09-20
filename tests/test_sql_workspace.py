import threading

import pytest

from config.db_config import config
from config.i18n import AppError
from database.connection import get_connection, initialize_database
from logic.sql_workspace import preview_query


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    monkeypatch.setitem(config, "database", str(path))
    initialize_database()
    connection = get_connection()
    with connection:
        connection.executemany("INSERT INTO customers(id,name) VALUES(?,?)",
                               [(i, f"Name {i}") for i in range(1, 505)])
    connection.close()
    return path


def test_preview_limit_and_fresh_data(database):
    result = preview_query('SELECT id,name FROM customers ORDER BY id', threading.Event())
    assert result.columns == ["id", "name"]
    assert len(result.rows) == 500 and result.truncated
    connection = get_connection()
    with connection:
        connection.execute("UPDATE customers SET name='Updated' WHERE id=1")
    connection.close()
    assert preview_query('SELECT name FROM customers WHERE id=1', threading.Event()).rows == [('Updated',)]


@pytest.mark.parametrize("sql", [
    "DELETE FROM customers", "UPDATE customers SET name='x'", "DROP TABLE customers",
    "PRAGMA user_version=42", "ATTACH DATABASE ':memory:' AS other",
    "SELECT * FROM users", "SELECT * FROM sqlite_master",
    "SELECT 1; SELECT 2", "SELECT load_extension('missing')",
])
def test_disallowed_sql(database, sql):
    with pytest.raises(AppError):
        preview_query(sql, threading.Event())
    assert preview_query('SELECT count(*) FROM customers', threading.Event()).rows == [(504,)]


def test_cte_empty_and_duplicate_columns(database):
    assert preview_query('WITH c AS (SELECT id FROM customers) SELECT count(*) FROM c', threading.Event()).rows == [(504,)]
    assert preview_query('SELECT id,id FROM customers WHERE 0', threading.Event()).columns == ['id', 'id']


def test_cancel_and_timeout(database):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(AppError, match='cancelled'):
        preview_query('SELECT 1', cancel)
    with pytest.raises(AppError, match='time limit'):
        preview_query('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) SELECT sum(x) FROM n',
                      threading.Event(), timeout=0.01)
