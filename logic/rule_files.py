"""Portable TOML + SQL definitions with atomic, versioned database imports."""

import json
from pathlib import Path
import re
import tomllib
import uuid

from config.i18n import AppError
from database.connection import get_connection, dict_row_factory
from logic.accounts import require_superuser
from logic.datasets import checked_table, list_tables
from logic.dq_engine import evaluate, error_text

FIELDS = {'schema_version', 'key', 'description', 'rule_type', 'table', 'severity', 'error_message', 'active', 'sql_file'}


def read_definitions(directory):
    directory = Path(directory).resolve()
    paths = sorted(directory.rglob('*.rule.toml'))
    if not paths:
        raise AppError('No .rule.toml files found.')
    definitions, keys = [], set()
    for path in paths:
        if not path.resolve().is_relative_to(directory):
            raise AppError('Rule files must stay inside the selected directory.')
        data = tomllib.loads(path.read_text(encoding='utf-8'))
        if set(data) != FIELDS or type(data['schema_version']) is not int or data['schema_version'] != 1:
            raise AppError('Unsupported rule file format: {path}', path=str(path))
        for field in FIELDS - {'schema_version', 'active'}:
            if not isinstance(data[field], str):
                raise AppError('Rule metadata fields must be text.')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', data['key']) or data['key'] in keys:
            raise AppError('Rule keys must be unique lowercase letters, digits, underscores or hyphens.')
        if (data['severity'] not in ('low','medium','high') or type(data['active']) is not bool
                or not all(data[f].strip() for f in ('description','rule_type','table'))):
            raise AppError('Invalid rule metadata.')
        sql_name = data['sql_file']
        sql_path = (path.parent / sql_name).resolve()
        if (not sql_name.endswith('.sql') or '/' in sql_name or '\\' in sql_name
                or not sql_path.is_relative_to(path.parent.resolve())):
            raise AppError('SQL must be a .sql file beside its rule metadata.')
        data['sql_query'] = sql_path.read_text(encoding='utf-8').strip()
        if not data['sql_query']:
            raise AppError('Write a query first.')
        keys.add(data['key'])
        definitions.append(data)
    return definitions


def validate_definitions(connection, definitions):
    tables = list_tables(connection)
    for data in definitions:
        checked_table(connection, data['table'])
        evaluate(connection, data['sql_query'], tables)


def validate_files(directory):
    definitions = read_definitions(directory)
    c = get_connection()
    try:
        c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN')
        validate_definitions(c, definitions)
        return {'validated': len(definitions)}
    finally:
        c.close()


def import_rules(directory, actor):
    definitions = read_definitions(directory)
    c = get_connection()
    c.row_factory = dict_row_factory
    counts = {'created': 0, 'updated': 0, 'unchanged': 0}
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            # Account checks expect tuple rows.
            c.row_factory = None
            require_superuser(c, actor)
            validate_definitions(c, definitions)
            c.row_factory = dict_row_factory
            for data in definitions:
                old = c.execute('SELECT * FROM dq_rules WHERE rule_key=?', (data['key'],)).fetchone()
                values = (data['description'], data['rule_type'], data['table'], data['error_message'],
                          data['sql_query'], data['severity'], 'ACTIVE' if data['active'] else 'INACTIVE')
                if old is None:
                    c.execute("""INSERT INTO dq_rules(description,rule_type,target_table,error_message,sql_query,severity,status,rule_key,version)
                        VALUES(?,?,?,?,?,?,?,?,'1.0')""", (*values, data['key']))
                    counts['created'] += 1
                    continue
                previous = (old['description'], old['rule_type'], old['target_table'], error_text(old['error_message']),
                            (old['sql_query'] or '').strip(), old['severity'], old['status'])
                if previous == values:
                    counts['unchanged'] += 1
                    continue
                if old['target_table'] != data['table']:
                    raise AppError('Use a new rule key when changing its target table.')
                c.execute("""INSERT INTO dq_rules_history(rule_id,version,status,created_at,description,rule_type,target_table,rule_params,deactivated_by,deactivated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                    (old['id'], old['version'], old['status'], old['created_at'], old['description'], old['rule_type'], old['target_table'],
                     json.dumps({'sql_query': old['sql_query'], 'error_message': error_text(old['error_message']),
                                 'severity': old['severity']}, ensure_ascii=False), actor))
                parts = str(old['version'] or '1.0').split('.')
                version = f'{parts[0]}.{int(parts[1] if len(parts)>1 else 0)+1}'
                c.execute("""UPDATE dq_rules SET description=?,rule_type=?,target_table=?,error_message=?,sql_query=?,severity=?,status=?,version=?,
                    activated_at=CASE WHEN ?='ACTIVE' THEN datetime('now','localtime') ELSE activated_at END WHERE id=?""",
                    (*values, version, values[-1], old['id']))
                counts['updated'] += 1
        return counts
    finally:
        c.close()


def export_rules(directory, actor):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    c = get_connection()
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            require_superuser(c, actor)
            c.row_factory = dict_row_factory
            rules = c.execute('SELECT * FROM dq_rules ORDER BY id').fetchall()
            # Persist identities before writing files so retries always target the same rule.
            for row in rules:
                if not row['rule_key']:
                    row['rule_key'] = 'rule-' + uuid.uuid4().hex
                    c.execute('UPDATE dq_rules SET rule_key=? WHERE id=?', (row['rule_key'], row['id']))
                if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', row['rule_key']):
                    raise AppError('Invalid rule metadata.')
        planned = []
        for row in rules:
            key = row['rule_key']
            sql_name = key + '.sql'
            data = {'schema_version': 1, 'key': key, 'description': row['description'] or '',
                    'rule_type': row['rule_type'], 'table': row['target_table'], 'severity': row['severity'],
                    'error_message': error_text(row['error_message']), 'active': row['status'] == 'ACTIVE', 'sql_file': sql_name}
            text = '\n'.join(f'{k} = {json.dumps(v, ensure_ascii=False)}' for k, v in data.items()) + '\n'
            # Exclusive creation protects edited definitions from accidental overwrite.
            for path, content in ((directory / sql_name, (row['sql_query'] or '').strip() + '\n'),
                                  (directory / (key + '.rule.toml'), text)):
                if path.is_symlink():
                    raise AppError('Rule files must stay inside the selected directory.')
                if path.exists():
                    if path.read_text(encoding='utf-8') != content:
                        raise AppError('Export would overwrite an edited file: {path}. Choose an empty directory.', path=str(path))
                else:
                    planned.append((path, content))
        for path, content in planned:
            with path.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(content)
        return {'exported': len(rules)}
    finally:
        c.close()
