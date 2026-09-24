import threading

import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.sql_source import bind_source
from logic.sql_workspace import preview_query
from logic.rules import save_rule
from logic.dq_engine import validate_rule, run_checks, run_details


@pytest.mark.parametrize('placeholder',['{{SOURCE}}','{{source}}','{{ Source }}'])
def test_source_preview_save_and_execution_use_same_local_sql(sqlite_database,placeholder):
    c=get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
        c.execute("INSERT INTO customers(id,name) VALUES(1,'Ada'),(2,NULL)")
    c.close()
    query=f'SELECT id,name,CASE WHEN name IS NULL THEN 1 ELSE 0 END AS dq_check FROM {placeholder}'
    result=preview_query(query,threading.Event(),source_table='customers')
    assert result.rows == [(1,'Ada',0),(2,None,1)]
    validate_rule(query,'customers')
    rid=save_rule('Name required','SQL','customers',query,'Missing')
    c=get_connection()
    saved=c.execute('SELECT sql_query FROM dq_rules WHERE id=?',(rid,)).fetchone()[0]
    c.close()
    assert '{{' not in saved and 'FROM "customers"' in saved
    run=run_details(run_checks('customers','Admin',rid))
    assert (run['passed'],run['failed']) == (1,1)


def test_literals_comments_and_quoted_identifiers_are_not_substituted():
    query="SELECT '{{SOURCE}}', \"{{SOURCE}}\", `{{source}}`, [{{source}}] FROM {{source}} -- {{source}}\n/* {{SOURCE}} */"
    expected=query.replace('FROM {{source}}','FROM "a""b"')
    assert bind_source(query,'a"b') == expected


def test_placeholder_needs_explicit_table_and_cannot_access_internal_data(sqlite_database):
    with pytest.raises(AppError,match='Select a table'):
        preview_query('SELECT * FROM {{SOURCE}}',threading.Event())
    with pytest.raises(AppError):
        preview_query('SELECT * FROM {{SOURCE}}',threading.Event(),source_table='users')
    assert preview_query("SELECT '{{SOURCE}}'",threading.Event()).rows == [('{{SOURCE}}',)]
