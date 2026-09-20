"""One-time conversion from success flags to failure flags, with a backup."""

from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3

from database.connection import get_connection
from logic.datasets import quote


def convert_sql(connection, sql):
    if not sql or not sql.strip():
        return sql
    # Remove comments, but preserve quoted strings/identifiers containing comment markers.
    token = r"'(''|[^'])*'|\"(\"\"|[^\"])*\"|`(``|[^`])*`|\[[^\]]*\]|--[^\n]*|/\*[\s\S]*?\*/"
    clean = re.sub(token, lambda m: " " if m[0].startswith(("--", "/*")) else m[0], sql)
    clean = clean.strip().removesuffix(";").rstrip()
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    connection.set_authorizer(lambda action, a, b, db, source:
        sqlite3.SQLITE_OK if action in allowed and not (
            action == sqlite3.SQLITE_FUNCTION and (b or '').lower() == 'load_extension'
        ) else sqlite3.SQLITE_DENY)
    try:
        columns = [col[0] for col in connection.execute(f'SELECT * FROM (\n{clean}\n) LIMIT 0').description]
    finally:
        connection.set_authorizer(None)
    if 'dq_check' not in columns:
        # Already-invalid legacy rules remain invalid; no flag exists to convert.
        return sql
    projection = [
        'CASE "dq_check" WHEN 0 THEN 1 WHEN 1 THEN 0 ELSE "dq_check" END AS "dq_check"'
        if name == 'dq_check' else quote(name) for name in columns
    ]
    return '-- Migrated to 0 = PASS, 1 = FAIL.\nSELECT ' + ', '.join(projection) + f'\nFROM (\n{clean}\n) AS legacy_check;'


def upgrade_failure_flags(connection, destination):
    if connection.execute('PRAGMA user_version').fetchone()[0] >= 3:
        return
    tables = ('dq_rules', 'dq_rules_history', 'dq_field_results', 'dq_results')
    populated = any(connection.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() for table in tables)
    if populated:
        path = Path(destination)
        backup_dir = path.parent / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = get_connection(backup_dir / f'{path.stem}_before_failure_flags_{datetime.now():%Y%m%d_%H%M%S_%f}.db')
        try:
            connection.backup(backup)
        finally:
            backup.close()
    try:
        connection.execute('BEGIN IMMEDIATE')
        # Another opener may already have migrated while this one waited.
        if connection.execute('PRAGMA user_version').fetchone()[0] >= 3:
            connection.rollback()
            return
        for rid, sql in connection.execute('SELECT id,sql_query FROM dq_rules').fetchall():
            connection.execute('UPDATE dq_rules SET sql_query=? WHERE id=?', (convert_sql(connection, sql), rid))
        for hid, raw in connection.execute('SELECT history_id,rule_params FROM dq_rules_history').fetchall():
            try:
                params = json.loads(raw or '{}')
            except (ValueError, TypeError):
                continue
            if isinstance(params, dict) and isinstance(params.get('sql_query'), str):
                params['sql_query'] = convert_sql(connection, params['sql_query'])
                connection.execute('UPDATE dq_rules_history SET rule_params=? WHERE history_id=?',
                                   (json.dumps(params, ensure_ascii=False), hid))
        connection.execute('UPDATE dq_field_results SET test_result=CASE test_result WHEN 0 THEN 1 WHEN 1 THEN 0 ELSE test_result END')
        # Aggregated counts and error messages describe outcomes, so stay unchanged.
        connection.execute('PRAGMA user_version=3')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
