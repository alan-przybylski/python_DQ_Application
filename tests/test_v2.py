"""V2 behavior contracts: authorization, atomic imports and linked run history."""

import ast
from pathlib import Path

import bcrypt
import pytest

from config import i18n
from config.i18n import AppError
from database.connection import get_connection, initialize_database
from logic.accounts import save_user, validate_password, list_users
from logic.datasets import (
    CsvData,
    create_dataset,
    import_data,
    list_tables,
    read_csv,
    export_table,
    export_template,
    suggested_type,
)
from logic.dq_engine import (
    run_checks,
    run_details,
    runs_for_table,
    validate_rule,
    export_errors,
)
from logic.login_functions import login_user
from logic.rules import save_rule

ROOT = Path(__file__).resolve().parents[1]


def query(sql, params=()):
    connection = get_connection()
    try:
        with connection:
            return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


@pytest.fixture
def accounts(sqlite_database):
    save_user("admin", "Admin123", "superuser", create=True)
    save_user("reader", "Reader1", actor="admin", create=True)
    return sqlite_database


@pytest.mark.parametrize(
    "password,missing",
    [
        ("A1", "6 characters"),
        ("abcdef1", "uppercase"),
        ("Abcdef", "digit"),
        ("", "6 characters"),
        ("A1" + "x" * 71, "72 UTF-8 bytes"),
    ],
)
def test_password_errors_identify_missing_requirement(password, missing):
    with pytest.raises(AppError, match=missing):
        validate_password(password)


@pytest.mark.parametrize("password", ["Abcde1", "Password2026", "Żółw123"])
def test_valid_passwords(password):
    validate_password(password)


def test_account_roles_require_an_active_superuser(accounts):
    with pytest.raises(AppError, match="superuser account"):
        save_user("reader", role="superuser", actor="reader")
    with pytest.raises(AppError, match="superuser account"):
        list_users("reader")
    with pytest.raises(AppError, match="last active superuser"):
        save_user("admin", role="user", actor="admin")
    with pytest.raises(AppError, match="last active superuser"):
        save_user("admin", role="superuser", active=False, actor="admin")
    old_hash = query("SELECT password_hash FROM users WHERE username='reader'")[0][0]
    save_user("reader", role="superuser", actor="admin")
    assert (
        query("SELECT password_hash FROM users WHERE username='reader'")[0][0]
        == old_hash
    )
    assert login_user("reader", "Reader1")[1] == "superuser"
    save_user("admin", role="user", actor="reader")
    with pytest.raises(AppError, match="superuser account"):
        save_user("new", "Valid1", actor="admin", create=True)
    save_user("reader", "Changed1", role="superuser", actor="reader")
    assert login_user("reader", "Reader1")[0] is None
    assert login_user("reader", "Changed1")[1] == "superuser"


def test_additive_migration_preserves_legacy_rows_and_weak_login(tmp_path, monkeypatch):
    from config.db_config import config

    path = tmp_path / "legacy.db"
    monkeypatch.setitem(config, "database", str(path))
    connection = get_connection(path)
    connection.executescript((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
    password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode()
    connection.execute(
        "INSERT INTO users(username,password_hash,role) VALUES('admin',?,'admin')",
        (password_hash,),
    )
    connection.execute("INSERT INTO customers(id,name) VALUES(1,'Unchanged')")
    connection.execute(
        "INSERT INTO dq_rules(id,version,rule_type,target_table) VALUES(1,'1.2','required','customers')"
    )
    connection.execute(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.2',3,2)"
    )
    connection.execute("""INSERT INTO dq_field_results
        (rule_id,rule_version,record_id,field_name,field_value,test_result,target_table)
        VALUES(1,'1.2',1,'name','Old',0,'customers')""")
    connection.commit()
    old_tables = {}
    for table in ("customers", "dq_rules", "dq_results", "dq_field_results"):
        cursor = connection.execute(f'SELECT * FROM "{table}"')
        old_tables[table] = ([col[0] for col in cursor.description], cursor.fetchall())
    connection.close()
    initialize_database(path)
    initialize_database(path)
    for table, (columns, rows) in old_tables.items():
        assert query(f'SELECT {",".join(columns)} FROM "{table}"') == rows
    assert query("SELECT run_id FROM dq_results") == [(None,)]
    assert query("SELECT run_id FROM dq_field_results") == [(None,)]
    assert query("SELECT COUNT(*) FROM dq_runs") == [(0,)]
    assert query("SELECT password_hash,role FROM users") == [
        (password_hash, "superuser")
    ]
    assert login_user("admin", "admin") == ("admin", "superuser", None)
    assert query("PRAGMA foreign_key_check") == []
    assert query("PRAGMA integrity_check") == [("ok",)]
    backups = list((tmp_path / "backups").glob("legacy_before_runs_*.db"))
    assert len(backups) == 1
    backup = get_connection(backups[0])
    try:
        assert backup.execute("SELECT role FROM users").fetchone() == ("admin",)
        assert "run_id" not in [
            row[1] for row in backup.execute("PRAGMA table_info(dq_results)")
        ]
    finally:
        backup.close()


def test_csv_preserves_text_and_mapping_and_supports_templates(
    sqlite_database, tmp_path
):
    source = tmp_path / "input.csv"
    source.write_text(
        'Code;Full name;Comment\n001;Żaneta;"semi;colon"\n002;NA;\n',
        encoding="utf-8-sig",
    )
    data = read_csv(source)
    assert data.rows[0] == ["001", "Żaneta", "semi;colon"]
    assert suggested_type(["001", "002"]) == "TEXT"
    columns = [
        {"name": "code", "type": "TEXT", "required": True},
        {"name": "name", "type": "TEXT"},
        {"name": "comment", "type": "TEXT"},
    ]
    assert (
        import_data(
            data,
            "suppliers",
            "demo",
            {"Code": "code", "Full name": "name", "Comment": "comment"},
            columns,
        )
        == 2
    )
    assert "suppliers" in list_tables()
    assert query("SELECT id,code,name,comment FROM suppliers ORDER BY id") == [
        (1, "001", "Żaneta", "semi;colon"),
        (2, "002", "NA", None),
    ]
    export_template("suppliers", tmp_path / "template.csv")
    assert read_csv(tmp_path / "template.csv") == CsvData(
        ["id", "code", "name", "comment"], [], "template.csv"
    )
    export_table("suppliers", tmp_path / "export.csv")
    exported = read_csv(tmp_path / "export.csv")
    assert exported.rows[0] == ["1", "001", "Żaneta", "semi;colon"]
    assert query("SELECT row_count,table_name FROM data_load_log") == [(2, "suppliers")]


@pytest.mark.parametrize("bad_value", ["bad", "2.5", str(2**63)])
def test_bad_import_rolls_back_existing_updates_and_log(sqlite_database, bad_value):
    query("INSERT INTO customers(id,name,age) VALUES(1,'original',20)")
    data = CsvData(
        ["id", "name", "age"],
        [["1", "changed", "21"], ["2", "new", bad_value]],
        "bad.csv",
    )
    with pytest.raises(AppError, match="No data was saved"):
        import_data(data, "customers", "demo")
    assert query("SELECT id,name,age FROM customers") == [(1, "original", 20)]
    assert query("SELECT COUNT(*) FROM data_load_log") == [(0,)]


def test_failed_new_table_import_rolls_back_ddl(sqlite_database):
    columns = [{"name": "amount", "type": "REAL", "required": True}]
    with pytest.raises(AppError, match="No data was saved"):
        import_data(
            CsvData(["amount"], [["2.5"], ["nan"]], "bad.csv"),
            "payments",
            "demo",
            new_columns=columns,
        )
    assert "payments" not in list_tables()
    assert query("SELECT COUNT(*) FROM data_load_log") == [(0,)]


def test_mapping_is_explicit_and_internal_tables_are_protected(
    sqlite_database, tmp_path
):
    data = CsvData(["Name", "Extra"], [["Anna", "x"]], "file.csv")
    with pytest.raises(AppError, match="Map every"):
        import_data(data, "customers", "demo", {"Name": "name", "Extra": ""})
    assert import_data(data, "customers", "demo", {"Name": "name", "Extra": None}) == 1
    for name in ("users", "dq_runs", "dq_hidden", "sqlite_bad"):
        with pytest.raises(AppError, match="reserved"):
            create_dataset(name, [{"name": "value", "type": "TEXT"}])
    for name in ("users", 'customers"; DROP TABLE users;--'):
        with pytest.raises(AppError):
            export_table(name, tmp_path / "blocked.csv")
        assert not (tmp_path / "blocked.csv").exists()


def test_text_ids_and_duplicate_csv_ids(sqlite_database):
    columns = [{"name": "id", "type": "TEXT"}, {"name": "label", "type": "TEXT"}]
    import_data(
        CsvData(["id", "label"], [["001", "A"]], "one.csv"),
        "codes",
        "demo",
        new_columns=columns,
    )
    import_data(CsvData(["id", "label"], [["001", "B"]], "two.csv"), "codes", "demo")
    assert query("SELECT * FROM codes") == [("001", "B")]
    with pytest.raises(AppError, match="Duplicate id"):
        import_data(
            CsvData(["id", "label"], [["001", "C"], ["001", "D"]], "dup.csv"),
            "codes",
            "demo",
        )
    assert query("SELECT * FROM codes") == [("001", "B")]
    with pytest.raises(AppError, match="required"):
        import_data(CsvData(["label"], [["E"]], "noid.csv"), "codes", "demo")


def test_export_formula_protection_is_explicit(sqlite_database, tmp_path):
    query("INSERT INTO customers(name) VALUES('=1+1')")
    safe, raw = tmp_path / "safe.csv", tmp_path / "raw.csv"
    export_table("customers", safe)
    export_table("customers", raw, spreadsheet_safe=False)
    assert read_csv(safe).rows[0][1] == "'=1+1"
    assert read_csv(raw).rows[0][1] == "=1+1"
    with pytest.raises(AppError, match=".csv"):
        export_table("customers", tmp_path / "bad.db")


@pytest.fixture
def rules(accounts):
    query("INSERT INTO customers(id,name,age) VALUES(1,'Anna',21),(2,'Jan',16)")
    save_rule(
        "Adult",
        "range",
        "customers",
        "SELECT id, age, CASE WHEN age >= 18 THEN 1 ELSE 0 END AS dq_check FROM customers",
        "Must be an adult",
    )
    return query("SELECT id FROM dq_rules")[0][0]


def test_runs_do_not_mix_errors_and_survive_restart(rules, tmp_path):
    first = run_checks("customers", "admin")
    query("UPDATE customers SET age=20 WHERE id=2")
    second = run_checks("customers", "admin", rules)
    initialize_database()
    assert first != second
    assert run_details(first)["failed"] == 1
    assert run_details(second)["failed"] == 0
    assert run_details(second)["errors"] == []
    assert run_details(first)["errors"][0]["field_value"] == "16"
    assert run_details(first)["errors"][0]["record_id"] == "2"
    assert [run["id"] for run in runs_for_table("customers")] == [second, first]
    assert export_errors(first, tmp_path / "errors.csv") == 1
    assert export_errors(second, tmp_path / "clean.csv") == 0
    assert read_csv(tmp_path / "errors.csv").rows[0][0] == str(first)
    assert read_csv(tmp_path / "clean.csv").rows == []
    assert query("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "DROP TABLE customers",
        "PRAGMA table_info(customers)",
        "ATTACH DATABASE ':memory:' AS other",
        "SELECT id,password_hash,1 AS dq_check FROM users",
        "SELECT id,name,'0' AS dq_check FROM customers",
        "SELECT id,name,2 AS dq_check FROM customers",
        "SELECT NULL AS id,name,0 AS dq_check FROM customers",
        "SELECT name,age,1 AS dq_check FROM customers",
        "SELECT id,name,name AS dq_check FROM customers",
        "SELECT id,name,1 AS dq_check FROM customers; DELETE FROM customers",
    ],
)
def test_rule_sql_is_read_only_and_contract_checked(rules, sql):
    with pytest.raises(AppError):
        validate_rule(sql, "customers")
    assert query("SELECT COUNT(*) FROM customers") == [(2,)]
    assert query("SELECT COUNT(*) FROM users") == [(2,)]


def test_partial_execution_keeps_consistent_kpi_and_details(rules):
    query("""INSERT INTO dq_rules(version,description,rule_type,target_table,sql_query)
        VALUES('1.0','Broken','test','customers','SELECT missing FROM customers')""")
    run = run_details(run_checks("customers", "admin"))
    assert (run["status"], run["rules_requested"], run["rules_completed"]) == (
        "partial",
        2,
        1,
    )
    assert (
        run["passed"],
        run["failed"],
        len(run["errors"]),
        len(run["execution_errors"]),
    ) == (1, 1, 1, 1)
    assert query("SELECT COUNT(*) FROM dq_results WHERE run_id=?", (run["id"],)) == [
        (1,)
    ]
    assert query(
        "SELECT COUNT(*) FROM dq_field_results WHERE run_id=?", (run["id"],)
    ) == [(2,)]
    assert query("SELECT COUNT(*) FROM customers") == [(2,)]


def test_empty_results_and_no_rules_are_not_reported_as_failures(rules):
    query("DELETE FROM customers")
    run = run_details(run_checks("customers", "admin"))
    assert (run["status"], run["passed"], run["failed"]) == ("completed", 0, 0)
    query("UPDATE dq_rules SET status='INACTIVE'")
    run = run_details(run_checks("customers", "admin"))
    assert (run["status"], run["rules_requested"], run["rules_completed"]) == (
        "no_rules",
        0,
        0,
    )


def test_all_literal_translations_exist():
    missing = set()
    for folder in ("config", "logic", "ui"):
        for path in (ROOT / folder).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"tr", "AppError"}
                ):
                    if (
                        node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        if node.args[0].value not in i18n.PL:
                            missing.add(node.args[0].value)
    assert not missing


def test_language_preference_and_localized_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "SETTINGS_PATH", tmp_path / "settings.json")
    try:
        i18n.set_language("PL")
        with pytest.raises(AppError, match="duża litera"):
            validate_password("abcdef1")
        i18n.set_language("EN", persist=False)
        i18n.load_language()
        assert i18n.language() == "PL"
        i18n.SETTINGS_PATH.write_text("invalid", encoding="utf-8")
        i18n.load_language()
        assert i18n.language() == "EN"
    finally:
        i18n.set_language("EN", persist=False)
