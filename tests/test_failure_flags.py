import json

import pytest

from database.connection import get_connection, initialize_database
from database.failure_flags import convert_sql
from logic.dq_engine import run_checks, run_details


def test_migration_preserves_outcomes_archives_and_kpi(sqlite_database):
    c = get_connection()
    old_sql = "WITH source AS (SELECT * FROM customers) SELECT id,name,CASE WHEN name IS NOT NULL THEN 1 ELSE 0 END AS dq_check FROM source; -- old convention"
    with c:
        c.execute("INSERT INTO users(username,password_hash) VALUES('tester','unused')")
        c.execute("INSERT INTO customers(id,name) VALUES(1,'Anna'),(2,NULL)")
        c.execute("INSERT INTO dq_rules(id,version,rule_type,target_table,sql_query) VALUES(1,'1.0','required','customers',?)", (old_sql,))
        c.execute("INSERT INTO dq_rules_history(rule_id,version,rule_type,target_table,rule_params) VALUES(1,'0.9','required','customers',?)", (json.dumps({'sql_query': old_sql}),))
        c.execute("INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.0',1,1)")
        c.execute("INSERT INTO dq_field_results(rule_id,rule_version,record_id,field_name,test_result,target_table) VALUES(1,'1.0','1','name',1,'customers'),(1,'1.0','2','name',0,'customers')")
        c.execute('PRAGMA user_version=2')
    c.close()
    initialize_database()
    c = get_connection()
    sql = c.execute('SELECT sql_query FROM dq_rules').fetchone()[0]
    assert c.execute(sql).fetchall() == [(1,'Anna',0),(2,None,1)]
    archived = json.loads(c.execute('SELECT rule_params FROM dq_rules_history').fetchone()[0])
    assert c.execute(archived['sql_query']).fetchall() == [(1,'Anna',0),(2,None,1)]
    assert c.execute('SELECT test_result FROM dq_field_results ORDER BY id').fetchall() == [(0,), (1,)]
    assert c.execute('SELECT passed_count,failed_count FROM dq_results').fetchall() == [(1,1)]
    c.close()
    initialize_database()
    c = get_connection()
    assert c.execute('SELECT sql_query FROM dq_rules').fetchone()[0] == sql
    assert c.execute('SELECT test_result FROM dq_field_results ORDER BY id').fetchall() == [(0,), (1,)]
    c.close()
    assert len(list((sqlite_database.parent / 'backups').glob('*before_failure_flags*'))) == 1
    result = run_details(run_checks('customers', 'tester'))
    assert (result['passed'], result['failed']) == (1,1)
    assert len(result['errors']) == 1


def test_invalid_sql_rolls_back_entire_migration(sqlite_database):
    c = get_connection()
    with c:
        c.execute("INSERT INTO dq_rules(rule_type,target_table,sql_query) VALUES('test','customers','SELECT broken FROM missing')")
        c.execute('PRAGMA user_version=2')
    c.close()
    with pytest.raises(Exception):
        initialize_database()
    c = get_connection()
    assert c.execute('PRAGMA user_version').fetchone()[0] == 2
    assert c.execute('SELECT sql_query FROM dq_rules').fetchone()[0] == 'SELECT broken FROM missing'
    c.close()


def test_converter_preserves_literals_and_invalid_flags(sqlite_database):
    c = get_connection()
    try:
        sql = "SELECT 1 AS id, 'a;--b/*c*/' AS value, 2 AS dq_check;"
        assert c.execute(convert_sql(c, sql)).fetchone() == (1, 'a;--b/*c*/', 2)
    finally:
        c.close()
