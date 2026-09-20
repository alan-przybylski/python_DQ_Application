from datetime import date
import sqlite3

import pytest

from database.connection import get_connection, initialize_database
from logic import csv_upload, dq_report, login_functions
from logic.dq_engine import run_checks, export_errors
from logic.rules import archive_rule


@pytest.fixture
def notices(monkeypatch):
    from tkinter import messagebox

    messages = []
    for method in ("showerror", "showinfo", "showwarning"):
        monkeypatch.setattr(
            messagebox,
            method,
            lambda *args, _method=method, **kwargs: messages.append((_method, args)),
        )
    return messages


def test_users_survive_restart_and_existing_password_interface(sqlite_database):
    login_functions.create_user("Żaneta", "Valid123", "admin")
    assert login_functions.login_user("ŻANETA", "Valid123")[0] is None
    assert login_functions.login_user("Żaneta", "Valid123") == (
        "Żaneta",
        "superuser",
        None,
    )
    assert login_functions.login_user("Żaneta", "wrong")[0] is None
    initialize_database()
    assert login_functions.get_all_users(actor="Żaneta") == ["Żaneta"]
    login_functions.create_user("backup", "Backup1", "superuser", actor="Żaneta")
    login_functions.deactivate_user("Żaneta", actor="backup")
    assert login_functions.login_user("Żaneta", "Valid123")[0] is None
    login_functions.change_password("Żaneta", "Newpass2", actor="backup")
    assert login_functions.login_user("Żaneta", "Newpass2") == (
        "Żaneta",
        "superuser",
        None,
    )
    connection = get_connection()
    try:
        assert connection.execute(
            "SELECT typeof(password_hash) FROM users"
        ).fetchone() == ("text",)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO users(username,password_hash) VALUES('zaneta','x')"
            )
    finally:
        connection.close()


def test_import_upsert_and_history_survive_restart(sqlite_database, tmp_path, notices):
    source = tmp_path / "sample.csv"
    source.write_text(
        "id;name;email;age\n1;Anna;anna@example.test;21\n2;Jan;;\n", encoding="cp1250"
    )
    assert csv_upload.load_csv_and_log(str(source), "customers", "demo")[1]
    source.write_text(
        "id;name;email;age\n1;Anna;new@example.test;22\n", encoding="cp1250"
    )
    assert csv_upload.load_csv_and_log(str(source), "customers", "demo")[1]
    initialize_database()
    connection = get_connection()
    try:
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 2
        assert connection.execute(
            "SELECT email,age FROM customers WHERE id=1"
        ).fetchone() == ("new@example.test", 22)
        assert connection.execute(
            "SELECT email,age FROM customers WHERE id=2"
        ).fetchone() == (None, None)
        assert connection.execute(
            "SELECT row_count,loaded_by FROM data_load_log ORDER BY id"
        ).fetchall() == [(2, "demo"), (1, "demo")]
    finally:
        connection.close()
    assert not [message for message in notices if message[0] == "showerror"]


def seed_rule(connection):
    connection.execute(
        "INSERT INTO users(username,password_hash) VALUES('demo','test-only')"
    )
    connection.executemany(
        "INSERT INTO customers(id,name,email,age) VALUES(?,?,?,?)",
        [
            (1, "Anna", "a@test", 21),
            (2, "jan", "B@test", 16),
            (3, None, None, 34),
        ],
    )
    connection.execute(
        "INSERT INTO dq_rules(id,version,rule_type,target_table,description,sql_query) VALUES(1,'1.2','age','customers','Adult',?)",
        (
            "SELECT id, age, CASE WHEN age > 18 THEN 0 ELSE 1 END AS dq_check FROM customers",
        ),
    )
    connection.commit()


def test_single_and_all_checks_append_persistent_results(
    sqlite_database, tmp_path, notices, monkeypatch
):
    export_dir = tmp_path / "excels"
    export_dir.mkdir()
    connection = get_connection()
    seed_rule(connection)
    connection.close()
    first = run_checks("customers", "demo", 1)
    initialize_database()
    second = run_checks("customers", "demo")
    assert first != second
    assert export_errors(first, export_dir / "first.csv") == 1
    assert export_errors(second, export_dir / "second.csv") == 1
    initialize_database()
    connection = get_connection()
    try:
        assert connection.execute(
            "SELECT rule_version,passed_count,failed_count FROM dq_results ORDER BY id"
        ).fetchall() == [("1.2", 2, 1), ("1.2", 2, 1)]
        assert (
            connection.execute("SELECT COUNT(*) FROM dq_field_results").fetchone()[0]
            == 6
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    kpi = dq_report.get_data_from_dq_results()
    assert len(kpi) == 2
    assert all(isinstance(row[2], date) and row[3] == 66.67 for row in kpi)
    assert (export_dir / "first.csv").is_file()
    assert (export_dir / "second.csv").is_file()
    assert not [message for message in notices if message[0] == "showerror"]


def test_regexp_and_case_compatibility(sqlite_database):
    connection = get_connection()
    try:
        assert connection.execute(
            "SELECT 'jan' REGEXP '^[A-Z]', REGEXP_LIKE('jan','[A-Z]','c'), REGEXP_LIKE('JAN','[A-Z]','c'), NULL REGEXP '@'"
        ).fetchone() == (1, 0, 1, None)
        connection.execute(
            "INSERT INTO dq_rules(rule_type,target_table) VALUES('required','customers')"
        )
        assert connection.execute(
            "SELECT status FROM dq_rules WHERE status='active'"
        ).fetchone() == ("ACTIVE",)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO dq_results(rule_id,rule_version) VALUES(999,'1.0')"
            )
    finally:
        connection.close()


def test_archive_rule_preserves_old_version(sqlite_database, notices):
    connection = get_connection()
    seed_rule(connection)
    connection.close()

    archive_rule(1, "demo")
    initialize_database()
    connection = get_connection()
    try:
        assert connection.execute("SELECT status,version FROM dq_rules").fetchone() == (
            "INACTIVE",
            "1.2",
        )
        assert connection.execute(
            "SELECT rule_id,version,deactivated_by FROM dq_rules_history"
        ).fetchone() == (1, "1.2", "demo")
    finally:
        connection.close()
