import json

from database.connection import get_connection
from logic.rule_library import list_rules, rule_details


def execute(sql, params=()):
    connection = get_connection()
    try:
        with connection:
            return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def seed():
    execute(
        "INSERT INTO dq_rules(id,status,version,description,rule_type,target_table,sql_query) VALUES(1,'ACTIVE','1.1','Name','required','customers','SELECT id,name,0 AS dq_check FROM customers'), (2,'INACTIVE','1.0','Age','range','customers','SELECT id,age,0 AS dq_check FROM customers')"
    )
    execute(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.0',20,0),(2,'1.0',10,2)"
    )


def test_one_row_per_rule_and_no_previous_version_kpi(sqlite_database):
    seed()
    rows = list_rules()
    assert len(rows) == 2
    assert rows[0]["result_id"] is None
    assert rows[0]["kpi"] is None
    assert rows[1]["status"] == "INACTIVE"
    execute(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.1',3,1),(1,'1.1',1,1)"
    )
    assert list_rules()[0]["kpi"] == 50


def test_history_deduplicates_current_without_changing_saved_rows(sqlite_database):
    seed()
    for version in ["1.0", "1.0", "1.1"]:
        execute(
            "INSERT INTO dq_rules_history(rule_id,version,description,rule_type,target_table,rule_params) VALUES(1,?,'Old name','required','customers',?)",
            (
                version,
                json.dumps(
                    {
                        "sql_query": "SELECT id,name,1 AS dq_check FROM customers",
                        "error_message": "Old error",
                    }
                ),
            ),
        )
    before = execute("SELECT * FROM dq_rules_history")
    data = rule_details(1)
    assert [row["version"] for row in data["versions"]] == ["1.1", "1.0"]
    assert "1 AS dq_check" in data["versions"][1]["sql_query"]
    assert data["result"] is None
    assert execute("SELECT * FROM dq_rules_history") == before


def test_latest_results_only_link_errors_by_run_and_version(sqlite_database):
    seed()
    execute(
        "INSERT INTO dq_runs(id,table_name,username,mode,status,rules_requested,rules_completed) VALUES(1,'customers','admin','all','completed',2,2), (2,'customers','admin','all','completed',2,2)"
    )
    execute(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count,run_id) VALUES(1,'1.1',1,1,1),(1,'1.1',2,1,2)"
    )
    for run, version, record in [
        (1, "1.1", "old"),
        (2, "1.0", "wrong_version"),
        (2, "1.1", "current"),
    ]:
        execute(
            "INSERT INTO dq_field_results(rule_id,rule_version,record_id,field_name,field_value,test_result,error_message,target_table,run_id) VALUES(1,?,?,'name','',1,'missing','customers',?)",
            (version, record, run),
        )
    data = rule_details(1)
    assert data["result"]["run_id"] == 2
    assert [row["record_id"] for row in data["errors"]] == ["current"]


def test_legacy_results_do_not_invent_links(sqlite_database):
    seed()
    execute(
        "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.1',1,1)"
    )
    execute(
        "INSERT INTO dq_field_results(rule_id,rule_version,record_id,field_name,field_value,test_result,error_message,target_table) VALUES(1,'1.1','legacy','name','',1,'missing','customers')"
    )
    assert rule_details(1)["errors"] == []


def test_invalid_historical_json_does_not_break_details(sqlite_database):
    seed()
    execute(
        "INSERT INTO dq_rules_history(rule_id,version,rule_type,target_table,rule_params) VALUES(1,'1.0','required','customers','invalid')"
    )
    assert rule_details(1)["versions"][1]["sql_query"] is None
