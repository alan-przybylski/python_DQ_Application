from datetime import datetime, timedelta

import pytest

from config.i18n import AppError
from database.connection import get_connection, initialize_database
from logic.datasets import list_tables
from logic.dq_engine import run_checks
from logic.rules import save_rule, archive_rule
from logic.tickets import list_tickets, ticket_details, update_ticket, sync_ticket


@pytest.fixture
def seeded(sqlite_database):
    c = get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('owner','test','superuser'),('worker','test','user'),('stranger','test','user')")
        c.execute("INSERT INTO customers(id,name) VALUES(1,NULL),(2,'Anna')")
        c.execute("INSERT INTO data_load_log(table_name,file_name,row_count,loaded_by) VALUES('customers','sample.csv',2,'worker')")
    c.close()
    return save_rule('Name required', 'required', 'customers',
                     'SELECT id,name,CASE WHEN name IS NULL THEN 1 ELSE 0 END AS dq_check FROM customers', '', severity='high')


def test_ticket_lifecycle_deduplication_and_deadline(seeded):
    run_checks('customers', 'owner')
    first = list_tickets()[0]
    assert first['assignee'] == first['reporter'] == 'owner'
    assert first['imported_by'] == 'worker'
    assert first['severity'] == 'high' and first['failed_count'] == 1
    assert datetime.fromisoformat(first['due_at']) - datetime.fromisoformat(first['created_at']) == timedelta(days=1)
    update_ticket(first['id'], 'owner', 'worker', 'to_verify', 'Please check source')
    run_checks('customers', 'worker')
    current = list_tickets()[0]
    assert current['status'] == 'in_progress'
    assert current['due_at'] == first['due_at']
    assert current['assignee'] == 'worker' and current['reporter'] == 'owner'
    c = get_connection()
    with c:
        c.execute("UPDATE dq_rules SET severity='low'")
        c.execute("UPDATE customers SET name='Fixed' WHERE id=1")
    c.close()
    run_checks('customers', 'owner')
    ticket, history, errors = ticket_details(first['id'])
    assert ticket['status'] == 'closed' and ticket['failed_count'] == 0
    assert ticket['severity'] == 'high' and ticket['due_at'] == first['due_at']
    assert len(errors) == 1 and any(e['kind'] == 'comment' for e in history)
    c = get_connection()
    with c:
        c.execute('UPDATE customers SET name=NULL WHERE id=1')
    c.close()
    run_checks('customers', 'owner')
    assert len(list_tickets()) == 2
    new = next(t for t in list_tickets() if t['status'] != 'closed')
    assert new['severity'] == 'low'


@pytest.mark.parametrize('severity,days', [('low',7),('medium',3),('high',1)])
def test_calendar_deadlines(seeded, severity, days):
    c = get_connection()
    now = datetime(2026, 9, 25, 15, 0, 0)
    with c:
        sync_ticket(c, seeded, '1.0', 'customers', 'Name', severity, None, 'owner', 1, 2, now)
    c.close()
    assert list_tickets()[0]['due_at'] == (now + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')


def test_errors_empty_results_and_no_rules_do_not_close(seeded):
    run_checks('customers', 'owner')
    c = get_connection()
    for sql in ['SELECT missing FROM customers', 'SELECT id,name,0 AS dq_check FROM customers WHERE 0']:
        with c:
            c.execute('UPDATE dq_rules SET sql_query=?', (sql,))
        run_checks('customers', 'owner')
        assert list_tickets()[0]['status'] == 'new'
    with c:
        c.execute("UPDATE dq_rules SET status='INACTIVE'")
    run_checks('customers', 'owner')
    assert len(list_tickets()) == 1 and list_tickets()[0]['status'] == 'new'
    c.close()


def test_authorization_and_rule_severity_history(seeded):
    run_checks('customers', 'owner')
    tid = list_tickets()[0]['id']
    with pytest.raises(AppError):
        update_ticket(tid, 'stranger', 'stranger', 'in_progress')
    with pytest.raises(AppError):
        update_ticket(tid, 'owner', 'worker', 'closed')
    with pytest.raises(AppError):
        update_ticket(tid, 'owner', 'missing', 'new')
    archive_rule(seeded, 'owner')
    from logic.rule_library import rule_details
    save_rule('Name', 'required', 'customers', 'SELECT id,name,0 AS dq_check FROM customers', '', seeded, severity='low')
    assert rule_details(seeded)['versions'][1]['severity'] == 'high'
    initialize_database()
    assert list_tickets()[0]['severity'] == 'high'
    assert 'dq_tickets' not in list_tables() and 'dq_ticket_events' not in list_tables()


def test_deleting_rule_keeps_ticket_audit(seeded):
    from logic.rule_deletion import delete_rule
    run_checks('customers', 'owner')
    delete_rule(seeded, 'owner')
    ticket, history, errors = ticket_details(list_tickets()[0]['id'])
    assert ticket['rule_id'] is None and history and not errors
    assert ticket['status'] == 'cancelled'
    assert history[-1]['kind'] == 'rule_deleted'


def test_upgrade_defaults_existing_rules_to_medium_without_backfill(sqlite_database):
    c = get_connection()
    with c:
        c.execute('DROP TABLE dq_ticket_events')
        c.execute('DROP TABLE dq_tickets')
        c.execute('ALTER TABLE dq_rules DROP COLUMN severity')
        c.execute("INSERT INTO dq_rules(rule_type,target_table,sql_query) VALUES('test','customers','SELECT id,name,1 AS dq_check FROM customers')")
        c.execute('PRAGMA user_version=3')
    c.close()
    initialize_database()
    initialize_database()
    c = get_connection()
    try:
        assert c.execute('SELECT severity,sql_query FROM dq_rules').fetchall() == [('medium','SELECT id,name,1 AS dq_check FROM customers')]
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        assert not list_tickets()
    finally:
        c.close()


def test_ticket_write_failure_rolls_back_rule_results(seeded, monkeypatch):
    import sqlite3
    import logic.tickets as tickets
    def fail(*args, **kwargs):
        raise sqlite3.IntegrityError('simulated event write failure')
    monkeypatch.setattr(tickets, 'event', fail)
    run_id = run_checks('customers', 'owner')
    c = get_connection()
    try:
        assert c.execute('SELECT COUNT(*) FROM dq_tickets').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM dq_results').fetchone()[0] == 0
        assert c.execute('SELECT COUNT(*) FROM dq_field_results').fetchone()[0] == 0
        assert c.execute('SELECT status,rules_completed FROM dq_runs WHERE id=?', (run_id,)).fetchone() == ('failed', 0)
    finally:
        c.close()
