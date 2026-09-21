"""Tickets track ownership and repair; DQ results remain the source of evidence."""

from datetime import datetime, timedelta
import json

from config.i18n import AppError
from database.connection import get_connection, dict_row_factory

SEVERITY_DAYS = {'low': 7, 'medium': 3, 'high': 1}
STATUS_LABELS = {'new': 'New', 'in_progress': 'In progress', 'to_verify': 'To verify', 'closed': 'Closed', 'cancelled': 'Rule deleted'}


def event(connection, ticket_id, actor, kind, detail, run_id=None):
    connection.execute('INSERT INTO dq_ticket_events(ticket_id,actor,kind,detail,run_id) VALUES(?,?,?,?,?)',
                       (ticket_id, actor, kind, detail, run_id))


def sync_ticket(connection, rule_id, version, table, title, severity, run_id, actor, failed, checked, now=None):
    """Called within the rule-result savepoint, never after SQL execution errors."""
    now = now or datetime.now()
    timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
    existing = connection.execute("SELECT id,status FROM dq_tickets WHERE rule_id=? AND table_name=? AND status NOT IN ('closed','cancelled')",
                                  (rule_id, table)).fetchone()
    if failed:
        if existing:
            tid, status = existing
            connection.execute("UPDATE dq_tickets SET last_seen=?,latest_run_id=?,failure_run_id=?,failed_count=?,rule_version=?,status=? WHERE id=?",
                               (timestamp, run_id, run_id, failed, version, 'in_progress' if status == 'to_verify' else status, tid))
            event(connection, tid, actor, 'failed', str(failed), run_id)
        else:
            source = connection.execute('SELECT loaded_by,file_name FROM data_load_log WHERE table_name=? ORDER BY id DESC LIMIT 1', (table,)).fetchone()
            due = (now + timedelta(days=SEVERITY_DAYS[severity])).strftime('%Y-%m-%d %H:%M:%S')
            tid = connection.execute("""INSERT INTO dq_tickets(rule_id,rule_version,table_name,title,severity,reporter,assignee,
                imported_by,source_file,created_at,last_seen,due_at,failed_count,latest_run_id,failure_run_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rule_id, version, table, title or f'Rule #{rule_id}', severity, actor, actor,
                 source[0] if source else None, source[1] if source else None, timestamp, timestamp, due, failed, run_id, run_id)).lastrowid
            event(connection, tid, actor, 'created', str(failed), run_id)
    elif existing and checked > 0:
        connection.execute("UPDATE dq_tickets SET status='closed',closed_at=?,latest_run_id=?,failed_count=0 WHERE id=?",
                           (timestamp, run_id, existing[0]))
        event(connection, existing[0], actor, 'verified', str(checked), run_id)
    elif existing:
        event(connection, existing[0], actor, 'empty', '0', run_id)


def list_tickets():
    c = get_connection()
    c.row_factory = dict_row_factory
    try:
        return c.execute("""SELECT *, (status NOT IN ('closed','cancelled') AND due_at<datetime('now','localtime')) AS overdue
            FROM dq_tickets ORDER BY status IN ('closed','cancelled'),due_at,id""").fetchall()
    finally:
        c.close()


def ticket_details(ticket_id):
    c = get_connection()
    c.row_factory = dict_row_factory
    try:
        c.execute('BEGIN')
        ticket = c.execute('SELECT * FROM dq_tickets WHERE id=?', (ticket_id,)).fetchone()
        if ticket is None:
            raise AppError('Ticket not found.')
        history = c.execute('SELECT * FROM dq_ticket_events WHERE ticket_id=? ORDER BY id', (ticket_id,)).fetchall()
        errors = c.execute("""SELECT record_id,field_name,field_value,error_message FROM dq_field_results
            WHERE run_id=? AND rule_id=? AND test_result=1 ORDER BY id LIMIT 500""",
            (ticket['failure_run_id'], ticket['rule_id'])).fetchall()
        return ticket, history, errors
    finally:
        c.close()


def active_users():
    c = get_connection()
    try:
        return [row[0] for row in c.execute('SELECT username FROM users WHERE active=1 ORDER BY username')]
    finally:
        c.close()


def update_ticket(ticket_id, actor, assignee, status, comment=''):
    c = get_connection()
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            user = c.execute('SELECT role FROM users WHERE username COLLATE BINARY=? AND active=1', (actor,)).fetchone()
            row = c.execute('SELECT reporter,assignee,status FROM dq_tickets WHERE id=?', (ticket_id,)).fetchone()
            if row is None:
                raise AppError('Ticket not found.')
            if not user or (user[0] not in ('admin', 'superuser') and actor not in row[:2]):
                raise AppError('Only the reporter, assignee or a superuser can update this ticket.')
            terminal = ('closed', 'cancelled')
            if status not in STATUS_LABELS or (status in terminal and row[2] != status) or (row[2] in terminal and status != row[2]):
                raise AppError('Tickets close automatically after a successful DQ check with no errors.')
            if not c.execute('SELECT 1 FROM users WHERE username COLLATE BINARY=? AND active=1', (assignee,)).fetchone() and assignee != row[1]:
                raise AppError('Select an active assignee.')
            c.execute('UPDATE dq_tickets SET assignee=?,status=? WHERE id=?', (assignee, status, ticket_id))
            if (assignee, status) != (row[1], row[2]):
                event(c, ticket_id, actor, 'updated', json.dumps({'assignee': assignee, 'status': status}, ensure_ascii=False))
            if comment.strip():
                event(c, ticket_id, actor, 'comment', comment.strip())
    finally:
        c.close()
