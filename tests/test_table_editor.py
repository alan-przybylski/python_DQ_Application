import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.datasets import export_template, table_columns
from logic.table_editor import edit_column, strict_conversion


def execute(sql, params=()):
    connection = get_connection()
    try:
        with connection:
            return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def test_add_rename_convert_drop_and_template(sqlite_database, tmp_path):
    execute("INSERT INTO customers(id,name,age) VALUES(9,'Ada',25)")
    backup = edit_column("customers", "add", name="country", kind="TEXT")
    assert backup.exists()
    original = get_connection(backup)
    try:
        assert "country" not in [
            c[1] for c in original.execute("PRAGMA table_info(customers)")
        ]
    finally:
        original.close()
    execute("UPDATE customers SET country='PL'")
    edit_column("customers", "modify", "country", "country_code", "TEXT")
    edit_column("customers", "modify", "age", "age", "TEXT", True)
    assert execute("SELECT id,name,age,country_code FROM customers") == [
        (9, "Ada", "25", "PL")
    ]
    assert next(c for c in table_columns("customers") if c["name"] == "age")["required"]
    # Original case/accent-insensitive comparison survives the rebuild.
    assert execute("SELECT name FROM customers WHERE name='ada'") == [("Ada",)]
    template = tmp_path / "updated.csv"
    export_template("customers", template)
    assert "country_code" in template.read_text(encoding="utf-8-sig")
    edit_column("customers", "drop", "country_code")
    assert "country_code" not in [c["name"] for c in table_columns("customers")]
    execute("INSERT INTO customers(name,age) VALUES('Bob','30')")
    assert execute("SELECT MAX(id) FROM customers") == [(10,)]


@pytest.mark.parametrize(
    "value,kind",
    [
        ("001", "INTEGER"),
        ("12.5", "INTEGER"),
        ("bad", "REAL"),
        ("", "INTEGER"),
        (" 2", "INTEGER"),
        ("NaN", "REAL"),
        ("1e500", "REAL"),
        (2**63, "INTEGER"),
        (9007199254740993, "REAL"),
        ("0.1234567890123456789", "REAL"),
    ],
)
def test_lossy_conversion_rejected(value, kind):
    with pytest.raises(AppError):
        strict_conversion(value, kind)


def test_invalid_conversion_rolls_back_schema_and_rows(sqlite_database):
    execute("INSERT INTO customers(name,age) VALUES('001',22),('Alice',30)")
    before = execute("SELECT * FROM customers")
    with pytest.raises(AppError):
        edit_column("customers", "modify", "name", "renamed", "INTEGER")
    assert execute("SELECT * FROM customers") == before
    assert table_columns("customers")[1]["name"] == "name"
    assert not execute("SELECT name FROM sqlite_master WHERE name LIKE 'dq_edit_%'")


@pytest.mark.parametrize("status", ["ACTIVE", "INACTIVE"])
def test_rules_protect_used_columns_but_allow_unrelated_columns(
    sqlite_database, status
):
    execute(
        "INSERT INTO dq_rules(version,status,description,rule_type,target_table,sql_query) VALUES('1.0',?,'Name','required','customers','SELECT c.id, c.name, 0 AS dq_check FROM customers AS c')",
        (status,),
    )
    for action in ("modify", "drop"):
        with pytest.raises(AppError, match="rule #"):
            edit_column("customers", action, "name", "full_name", "TEXT")
    edit_column("customers", "modify", "age", "years", "INTEGER")
    assert execute("SELECT COUNT(*) FROM dq_rules") == [(1,)]


def test_join_dependency_protected_even_with_other_target_table(sqlite_database):
    execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER)")
    execute(
        "INSERT INTO dq_rules(version,rule_type,target_table,sql_query) VALUES('1.0','test','orders','SELECT o.id,c.name,0 AS dq_check FROM orders o JOIN customers c ON o.customer_id=c.id')"
    )
    with pytest.raises(AppError):
        edit_column("customers", "drop", "name")


def test_id_and_internal_tables_are_protected(sqlite_database):
    with pytest.raises(AppError):
        edit_column("customers", "drop", "id")
    with pytest.raises(AppError):
        edit_column("users", "add", name="other")


def test_required_column_on_nonempty_table_rejected(sqlite_database):
    execute("INSERT INTO customers(name) VALUES('Ada')")
    with pytest.raises(Exception):
        edit_column("customers", "add", name="required_field", required=True)
    assert "required_field" not in [c["name"] for c in table_columns("customers")]


def test_advanced_schema_is_not_silently_rebuilt(sqlite_database):
    execute("CREATE INDEX customers_age ON customers(age)")
    with pytest.raises(AppError):
        edit_column("customers", "modify", "age", "age", "TEXT")
    assert execute("SELECT name FROM sqlite_master WHERE name='customers_age'")


def test_history_remains_unchanged(sqlite_database):
    execute(
        "INSERT INTO dq_rules(id,version,rule_type,target_table,sql_query) VALUES(1,'1.0','test','customers','SELECT id,name,0 AS dq_check FROM customers')"
    )
    execute(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.0',10,2)"
    )
    before = execute("SELECT * FROM dq_results")
    edit_column("customers", "modify", "age", "years", "INTEGER")
    assert execute("SELECT * FROM dq_results") == before


def test_empty_table_rebuild_keeps_autoincrement_high_water_mark(sqlite_database):
    execute("INSERT INTO customers(id,name) VALUES(99,'Deleted')")
    execute("DELETE FROM customers")
    edit_column("customers", "modify", "age", "age", "TEXT")
    execute("INSERT INTO customers(name) VALUES('New')")
    assert execute("SELECT id FROM customers") == [(100,)]


def test_wildcard_and_invalid_rules_fail_closed(sqlite_database):
    execute(
        "INSERT INTO dq_rules(version,rule_type,target_table,sql_query) VALUES('1.0','test','customers','SELECT *,0 AS dq_check FROM customers')"
    )
    with pytest.raises(AppError):
        edit_column("customers", "add", name="country")
    execute("UPDATE dq_rules SET sql_query='SELECT missing FROM customers'")
    with pytest.raises(AppError):
        edit_column("customers", "drop", "age")


def test_required_column_can_be_added_to_empty_table(sqlite_database):
    edit_column("customers", "add", name="country", kind="TEXT", required=True)
    assert table_columns("customers")[-1]["required"]
