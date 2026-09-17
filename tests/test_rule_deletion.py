import sqlite3

import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.dq_engine import run_checks, run_details
from logic.rule_deletion import delete_rule
from logic.rules import archive_rule


def sql(query, args=()):
    connection = get_connection()
    try:
        with connection:
            return connection.execute(query, args).fetchall()
    finally:
        connection.close()


@pytest.fixture
def history(sqlite_database):
    sql(
        "INSERT INTO users(username,password_hash,role) VALUES('admin','test','superuser')"
    )
    sql("INSERT INTO customers(name,age) VALUES('Ada',30),('Bob',20)")
    for rid in (1, 2):
        sql(
            "INSERT INTO dq_rules(id,version,description,rule_type,target_table,sql_query) VALUES(?,'1.0','Test','test','customers','SELECT id,name,0 AS dq_check FROM customers')",
            (rid,),
        )
    shared = run_checks("customers", "admin")
    solo = run_checks("customers", "admin", 1)
    sql("UPDATE dq_rules SET sql_query='SELECT missing FROM customers' WHERE id=1")
    partial = run_checks("customers", "admin")
    failed_solo = run_checks("customers", "admin", 1)
    # Unrelated no-rules runs must not disappear during deletion.
    empty = run_checks("customers", "admin", 999)
    archive_rule(1, "admin")
    return shared, solo, partial, failed_solo, empty


def test_hard_delete_keeps_other_rule_and_reconciles_shared_runs(history):
    shared, solo, partial, failed_solo, empty = history
    other_results = sql("SELECT * FROM dq_results WHERE rule_id=2")
    other_details = sql("SELECT * FROM dq_field_results WHERE rule_id=2")
    customers = sql("SELECT * FROM customers")
    delete_rule(1, "admin", "1.0")
    assert sql("SELECT id FROM dq_rules") == [(2,)]
    for table, key in [
        ("dq_rules_history", "rule_id"),
        ("dq_results", "rule_id"),
        ("dq_field_results", "rule_id"),
    ]:
        assert sql(f"SELECT COUNT(*) FROM {table} WHERE {key}=1") == [(0,)]
    assert sql("SELECT * FROM dq_results WHERE rule_id=2") == other_results
    assert sql("SELECT * FROM dq_field_results WHERE rule_id=2") == other_details
    assert sql("SELECT * FROM customers") == customers
    assert run_details(solo) is None and run_details(failed_solo) is None
    for rid in (shared, partial):
        run = run_details(rid)
        assert (run["status"], run["rules_requested"], run["rules_completed"]) == (
            "completed",
            1,
            1,
        )
        assert run["execution_errors"] == []
        assert run["failed"] == 2
    assert run_details(empty)["status"] == "no_rules"
    assert sql("PRAGMA foreign_key_check") == []


def test_other_rules_execution_errors_are_kept(history):
    sql(
        "UPDATE dq_rules SET status='ACTIVE',sql_query='SELECT id,name,1 AS dq_check FROM customers' WHERE id=1"
    )
    sql("UPDATE dq_rules SET sql_query='SELECT missing FROM customers' WHERE id=2")
    rid = run_checks("customers", "admin")
    before = run_details(rid)["execution_errors"]
    delete_rule(1, "admin")
    run = run_details(rid)
    assert run["execution_errors"] == before
    assert (run["status"], run["rules_completed"], run["rules_requested"]) == (
        "failed",
        0,
        1,
    )


def test_legacy_unlinked_results_are_removed(history):
    sql(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'0.9',3,0)"
    )
    delete_rule(1, "admin")
    assert not sql("SELECT id FROM dq_results WHERE rule_id=1")


@pytest.mark.parametrize("reason", ["version", "account", "corrupt", "running"])
def test_validation_errors_leave_everything_unchanged(history, reason):
    if reason == "account":
        sql("UPDATE users SET active=0 WHERE username='admin'")
    if reason == "corrupt":
        sql("UPDATE dq_runs SET execution_errors='broken' WHERE id=?", (history[0],))
    if reason == "running":
        sql("UPDATE dq_runs SET status='running' WHERE id=?", (history[0],))
    before = {
        table: sql(f"SELECT * FROM {table}")
        for table in (
            "dq_rules",
            "dq_rules_history",
            "dq_results",
            "dq_field_results",
            "dq_runs",
        )
    }
    with pytest.raises(AppError):
        delete_rule(1, "admin", "newer" if reason == "version" else "1.0")
    for table, rows in before.items():
        assert sql(f"SELECT * FROM {table}") == rows


def test_database_failure_rolls_back_already_deleted_children(history):
    sql(
        "CREATE TRIGGER reject_delete BEFORE DELETE ON dq_rules BEGIN SELECT RAISE(ABORT,'test failure'); END"
    )
    before = sql("SELECT * FROM dq_field_results")
    with pytest.raises(sqlite3.IntegrityError):
        delete_rule(1, "admin")
    assert sql("SELECT * FROM dq_field_results") == before
    assert sql("SELECT COUNT(*) FROM dq_rules_history WHERE rule_id=1") == [(1,)]


def test_repeated_delete_is_not_silent_success(history):
    delete_rule(1, "admin")
    with pytest.raises(AppError):
        delete_rule(1, "admin")


@pytest.mark.parametrize("actor", ["regular", "demoted", "missing"])
def test_only_current_superuser_can_delete(history, actor):
    if actor == "regular":
        sql(
            "INSERT INTO users(username,password_hash,role) VALUES('regular','test','user')"
        )
    if actor == "demoted":
        sql("UPDATE users SET role='user' WHERE username='admin'")
        actor = "admin"
    tables = (
        "dq_rules",
        "dq_rules_history",
        "dq_results",
        "dq_field_results",
        "dq_runs",
    )
    before = {table: sql(f"SELECT * FROM {table}") for table in tables}
    with pytest.raises(AppError, match="superuser"):
        delete_rule(1, actor)
    for table, rows in before.items():
        assert sql(f"SELECT * FROM {table}") == rows
