"""Cloud-only SQL and rule drafts; datasets never pass through SQLite."""
import time
import uuid
import json

from database.connection import get_connection
from integrations.databricks_contract import name, revision
from integrations.plain_sql import native_sql
from logic.accounts import require_superuser
from logic.databricks_import import Source, connect_source
from logic.databricks_profiles import load_profiles
from logic.sql_workspace import Preview


def source_for_profile(profile):
    settings = load_profiles()['profiles'].get(profile)
    if not settings:
        raise ValueError('Choose a saved Databricks profile first.')
    source = Source(**{**settings, 'table': settings['table'] or '_catalog'})
    source.validate()
    return source


def execute(cursor, sql, cancel, timeout=60, parameters=None):
    """Poll on the worker thread; cancel the server operation, not just the UI."""
    if cancel.is_set():
        raise ValueError('Query cancelled.')
    start = time.monotonic()
    if parameters is None:
        cursor.execute_async(sql)
    else:
        cursor.execute_async(sql, parameters)
    while True:
        if cancel.is_set() or time.monotonic() - start >= timeout:
            cursor.cancel()
            raise ValueError('Query cancelled.' if cancel.is_set() else 'Databricks query exceeded 60 seconds.')
        if not cursor.is_query_pending():
            break
        cancel.wait(0.2)
    cursor.get_async_execution_result()


def preview_query(profile, sql, cancel, connect=connect_source, limit=500):
    rendered, _ = native_sql(sql)
    start = time.monotonic()
    with connect(source_for_profile(profile)) as remote, remote.cursor() as cursor:
        execute(cursor, f'SELECT * FROM ({rendered}) AS dq_preview LIMIT {int(limit) + 1}', cancel)
        data = cursor.fetchmany(limit + 1)
        if cancel.is_set():
            raise ValueError('Query cancelled.')
        return Preview([col[0] for col in cursor.description], data[:limit], len(data) > limit,
                       time.monotonic() - start)


def browse(profile, catalog, schema, cancel, connect=connect_source):
    """Read available tables and their declared types from Unity Catalog."""
    with connect(source_for_profile(profile)) as remote, remote.cursor() as cursor:
        execute(cursor, 'SELECT table_name,column_name,full_data_type FROM '
                + name(catalog, 'information_schema', 'columns')
                + ' WHERE table_schema=? ORDER BY table_name,ordinal_position LIMIT 10001', cancel, parameters=[schema])
        rows = cursor.fetchmany(10001)
        if len(rows) > 10000:
            raise ValueError('Too many columns. Choose a smaller schema.')
        tables = {}
        for table, column, kind in rows:
            tables.setdefault(table, []).append((column, kind))
        return tables


def save_draft(actor, profile, source_parts, description, sql, message='', severity='medium', rule_id=None, active=True):
    """Save/version a native draft without requiring a matching local dataset."""
    from logic.databricks_sync import endpoint
    rendered, dependencies = native_sql(sql)
    if list(source_parts) not in dependencies.values():
        raise ValueError('The rule must read its selected table.')
    if not description.strip() or severity not in ('low', 'medium', 'high'):
        raise ValueError('Enter a description and select low, medium or high severity.')
    source = source_for_profile(profile)
    catalog, schema, table = source_parts
    connection = get_connection()
    try:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            require_superuser(connection, actor)
            if rule_id is not None:
                from database.connection import dict_row_factory
                connection.row_factory = dict_row_factory
                old = connection.execute('SELECT * FROM dq_rules WHERE id=?', (rule_id,)).fetchone()
                link = connection.execute('SELECT * FROM dq_remote_links WHERE rule_id=?', (rule_id,)).fetchone()
                if not old or old['sql_engine'] != 'databricks' or not link or link['profile'] != profile:
                    raise ValueError('Choose a native rule from this Databricks profile.')
                if [link['source_catalog'], link['source_schema'], link['source_table']] != list(source_parts):
                    raise ValueError('Save a new rule when changing its source table.')
                values = (description.strip(), message, rendered, severity, 'ACTIVE' if active else 'INACTIVE')
                if values == (old['description'], old['error_message'], old['sql_query'], old['severity'], old['status']):
                    return link['id']
                connection.execute('''INSERT INTO dq_rules_history
                    (rule_id,version,status,created_at,description,rule_type,target_table,rule_params,deactivated_by,deactivated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'))''',
                    (rule_id,old['version'],old['status'],old['created_at'],old['description'],old['rule_type'],old['target_table'],
                     json.dumps({'sql_query':old['sql_query'],'error_message':old['error_message'],'severity':old['severity'],'sql_engine':'databricks'}),actor))
                major, minor = old['version'].split('.')
                connection.execute('UPDATE dq_rules SET description=?,error_message=?,sql_query=?,severity=?,status=?,version=? WHERE id=?',
                                   (*values, f'{major}.{int(minor)+1}', rule_id))
                connection.execute('UPDATE dq_remote_links SET remote_sql=? WHERE id=?', (rendered,link['id']))
                return link['id']
            rid = connection.execute('''INSERT INTO dq_rules
                (description,rule_type,target_table,error_message,sql_query,version,severity,rule_key,sql_engine,execution_mode,status)
                VALUES(?,'SQL',?,?,?,'1.0',?,?,'databricks','databricks',?)''',
                (description.strip(), name(*source_parts), message, rendered, severity, 'rule-' + uuid.uuid4().hex, 'ACTIVE' if active else 'INACTIVE')).lastrowid
            link_id = connection.execute('''INSERT INTO dq_remote_links
                (rule_id,profile,control_catalog,control_schema,source_catalog,source_schema,source_table,remote_sql,endpoint,auto_sync,owner)
                VALUES(?,?,?,'dq_control',?,?,?,?,?,1,?)''',
                (rid, profile, source.catalog, catalog, schema, table, rendered,
                 endpoint(source, source.catalog, 'dq_control'), actor)).lastrowid
            return link_id
    finally:
        connection.close()


def publish_draft(link_id, actor, cancel, connect=connect_source):
    """Validate dependencies/output in the selected warehouse before publication."""
    from logic.databricks_sync import definition, source_for, setup_remote, compare, publish
    link, payload = definition(link_id)
    if payload['contract'] != 3:
        raise ValueError('Choose a native Databricks rule.')
    expected = revision(payload)
    if payload['active']:
        with connect(source_for(link)) as remote, remote.cursor() as cursor:
            for parts in [payload['source'], *payload['references'].values()]:
                execute(cursor, 'DESCRIBE HISTORY ' + name(*parts) + ' LIMIT 1', cancel)
                if not cursor.fetchmany(1):
                    raise ValueError('Scheduled checks need Delta tables with snapshot history.')
            execute(cursor, f"SELECT * FROM ({payload['sql']}) AS dq_validate LIMIT 0", cancel)
            columns = [col[0] for col in cursor.description]
            if len(columns) != 3 or columns[0] != 'id' or columns[2] != 'dq_check' or columns[1] in ('id', 'dq_check'):
                raise ValueError('A rule must return exactly id, checked_value (any field name), dq_check (0=PASS, 1=FAIL).')
    if cancel.is_set():
        raise ValueError('Query cancelled.')
    setup_remote(link_id, actor, connect)
    compared = compare(link_id, connect)
    if revision(compared['local']) != expected:
        raise ValueError('The rule changed during validation. Publish again.')
    return publish(link_id, actor, expected, compared['remote_revision'], connect)
