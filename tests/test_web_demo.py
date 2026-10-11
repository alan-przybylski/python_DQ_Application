"""Exercise isolation, row-level evidence and the repair/verification workflow."""

import sqlite3

import pytest

from config.db_config import config
from config.i18n import AppError
from web_demo.service import DemoSession, TABLES


@pytest.fixture
def demo():
    session = DemoSession()
    try:
        yield session
    finally:
        session.close()


def test_seed_has_two_datasets_eight_rules_and_real_baseline_reports(demo):
    assert demo.query("SELECT COUNT(*) AS n FROM dq_rules")[0]["n"] == 8
    for table in TABLES:
        assert len(demo.query(f"SELECT * FROM {table}")) == 12
        assert len(demo.rules(table)) == 4
        run = demo.runs(table)[0]
        assert run["rules_completed"] == 4
        assert run["status"] == "completed"
        assert run["passed"] + run["failed"] == 48
        assert run["failed"] > 0
        assert len(demo.failures(run["id"])) == run["failed"]
    assert demo.query("PRAGMA foreign_key_check") == []


@pytest.mark.parametrize("table", TABLES)
def test_repair_creates_clean_run_preserving_original_evidence(demo, table):
    baseline = demo.runs(table)[0]
    evidence = demo.failures(baseline["id"])
    demo.clean(table)
    run_id = demo.run(table)
    assert demo.runs(table)[0]["failed"] == 0
    assert demo.runs(table)[0]["passed"] == 48
    assert demo.failures(run_id) == []
    assert demo.failures(baseline["id"]) == evidence
    assert demo.query("SELECT status FROM dq_tickets WHERE table_name=?", (table,))
    assert all(row["status"] == "closed" for row in demo.query("SELECT status FROM dq_tickets WHERE table_name=?", (table,)))


def test_visitors_do_not_share_data_or_change_desktop_configuration(demo):
    original = config.copy()
    other = DemoSession()
    try:
        demo.clean("customers")
        demo.run("customers")
        assert other.runs("customers")[0]["failed"] > 0
        assert len(other.runs("customers")) == 1
        assert demo.database != other.database
        assert config == original
        other.close()
        assert demo.query("SELECT COUNT(*) AS n FROM customers")[0]["n"] == 12
    finally:
        other.close()


def test_single_rule_run_and_source_placeholder(demo):
    run_id = demo.run("products", 8)
    assert len(demo.report(run_id)) == 1
    assert demo.runs("products")[0]["rules_completed"] == 1
    sql = "SELECT p.id, p.name, CASE WHEN c.id IS NULL THEN 1 ELSE 0 END AS dq_check FROM {{SOURCE}} p LEFT JOIN customers c ON c.id=p.id"
    assert len(demo.preview(sql, "products")) == 12


@pytest.mark.parametrize("sql", [
    "DELETE FROM customers",
    "SELECT id, password_hash, 0 AS dq_check FROM users",
    "SELECT id, name, 2 AS dq_check FROM customers",
    "SELECT p.id, p.name, 0 AS dq_check FROM products p CROSS JOIN customers a CROSS JOIN customers b",
])
def test_preview_rejects_mutation_private_tables_invalid_results_and_huge_outputs(demo, sql):
    with pytest.raises((sqlite3.Error, AppError)):
        demo.preview(sql, "customers")
    assert len(demo.query("SELECT * FROM customers")) == 12


def test_bad_edit_rolls_back_instead_of_losing_dataset(demo):
    before = demo.query("SELECT * FROM products")
    with pytest.raises(ValueError):
        demo.save_rows("products", [(1, "oops")])
    assert demo.query("SELECT * FROM products") == before


def test_web_navigation_run_cleanup_reset_and_sql_error():
    pytest.importorskip("streamlit")
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "web_demo" / "app.py", default_timeout=20).run()
    try:
        assert not app.exception
        for page in ("Data workspace", "Rule library", "SQL playground", "Quality report", "About", "Overview"):
            app.radio[0].set_value(page).run()
            assert not app.exception
        app.radio[0].set_value("SQL playground").run()
        app.text_area[0].set_value("DELETE FROM customers")
        next(button for button in app.button if button.label == "Preview SQL").click().run()
        assert app.error
        assert not app.exception
        app.radio[0].set_value("Data workspace").run()
        next(button for button in app.button if button.label == "Apply clean sample + run checks").click().run()
        assert not app.exception
        assert app.session_state.demo.runs("customers")[0]["failed"] == 0
        next(button for button in app.button if button.label == "Reset demo").click().run()
        assert not app.exception
        assert app.session_state.demo.runs("customers")[0]["failed"] > 0
        assert len(app.session_state.demo.runs("customers")) == 1
    finally:
        if "demo" in app.session_state:
            app.session_state.demo.close()
