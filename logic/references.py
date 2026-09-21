"""Named reference datasets; local copies and remote mappings are explicit."""
import re
import json
from database.connection import get_connection, dict_row_factory
from logic.accounts import require_superuser
from logic.datasets import checked_table, quote
from logic.databricks_profiles import load_profiles
from integrations.cross_table import validate_spec, compile_check


def references():
    c=get_connection()
    c.row_factory=dict_row_factory
    try: return c.execute('SELECT * FROM dq_references ORDER BY alias').fetchall()
    finally: c.close()


def save_reference(actor,alias,local_table,profile='',catalog='',schema_name='',table_name=''):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',alias):
        raise ValueError('Use a lowercase reference alias, e.g. countries.')
    if any((profile,catalog,schema_name,table_name)) and not all((profile,catalog,schema_name,table_name)):
        raise ValueError('Fill all remote fields or leave them all empty.')
    if profile and profile not in load_profiles()['profiles']:
        raise ValueError('Choose a saved Databricks profile.')
    c=get_connection()
    try:
        with c:
            require_superuser(c,actor)
            checked_table(c,local_table)
            c.execute('INSERT INTO dq_references VALUES(?,?,?,?,?,?) ON CONFLICT(alias) DO UPDATE SET local_table=excluded.local_table,profile=excluded.profile,catalog=excluded.catalog,schema_name=excluded.schema_name,table_name=excluded.table_name',
                      (alias,local_table,profile,catalog,schema_name,table_name))
    finally: c.close()


def resolve_local(c,sql):
    def replace(match):
        cursor=c.cursor()
        cursor.row_factory=None
        row=cursor.execute('SELECT local_table FROM dq_references WHERE alias=?',(match[1],)).fetchone()
        if not row: raise ValueError('Missing reference: '+match[1])
        checked_table(c,row[0])
        return quote(row[0])
    return re.sub(r'\{\{ref:([a-z][a-z0-9_]*)\}\}',replace,sql)


def remote_references(c,spec,profile):
    cursor=c.cursor()
    cursor.row_factory=None
    row=cursor.execute('SELECT profile,catalog,schema_name,table_name FROM dq_references WHERE alias=?',(spec['reference'],)).fetchone()
    profiles=load_profiles()['profiles']
    if not row or not row[0] or row[0] not in profiles or profile not in profiles:
        raise ValueError('Configure the remote reference before publishing.')
    if profiles[row[0]]['hostname'].lower()!=profiles[profile]['hostname'].lower():
        raise ValueError('The reference and source must be in the same Databricks workspace.')
    return {spec['reference']:list(row[1:])}


def create_cross_rule(actor,description,table,spec,message,severity='medium'):
    from logic.rules import save_rule
    validate_spec(spec)
    c=get_connection()
    try: require_superuser(c,actor)
    finally: c.close()
    return save_rule(description,'cross_table',table,compile_check(spec,quote(table)),message,
                     severity=severity,cross_spec=spec)
