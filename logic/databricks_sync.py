"""Explicit publication with optimistic conflicts; bounded remote result imports."""

from datetime import datetime, timezone
from contextlib import ExitStack, contextmanager
import json
import uuid

from database.connection import get_connection, dict_row_factory
from integrations.databricks_contract import TABLES, name, canonical, revision, validate_payload
from logic.accounts import require_superuser
from logic.databricks_import import Source, connect_source
from logic.databricks_profiles import load_profiles
from logic.tickets import sync_ticket

MAX_RUNS = 10000
MAX_ERRORS = 100000


def endpoint(source, catalog, schema):
    return canonical([source.hostname.lower(), catalog, schema])


def mappings():
    c = get_connection()
    c.row_factory = dict_row_factory
    try:
        return c.execute('SELECT l.*,r.rule_key,r.description,r.target_table,r.execution_mode FROM dq_remote_links l JOIN dq_rules r ON r.id=l.rule_id ORDER BY l.id').fetchall()
    finally:
        c.close()


def source_for(link):
    settings = load_profiles()['profiles'].get(link['profile'])
    if not settings:
        raise ValueError('Saved connection profile is missing.')
    source = Source(**{**settings, 'table': link['source_table'], 'catalog': link['source_catalog'], 'schema': link['source_schema']})
    source.validate()
    if endpoint(source, link['control_catalog'], link['control_schema']) != link['endpoint']:
        raise ValueError('The profile now points to another workspace. Recreate the mapping explicitly.')
    return source


def save_mapping(rule_id, actor, profile, control_catalog, control_schema, source_catalog, source_schema, source_table, remote_sql, auto_sync=False):
    settings = load_profiles()['profiles'].get(profile)
    if not settings:
        raise ValueError('Choose a saved Databricks profile first.')
    source = Source(**{**settings, 'catalog': source_catalog, 'schema': source_schema, 'table': source_table})
    source.validate()
    target = endpoint(source, control_catalog, control_schema)
    name(control_catalog, control_schema)
    from integrations.databricks_contract import template_sql
    c = get_connection()
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            require_superuser(c, actor)
            spec_row=c.execute('SELECT cross_spec FROM dq_rules WHERE id=?',(rule_id,)).fetchone()
            template_sql(remote_sql,json.loads(spec_row[0]) if spec_row and spec_row[0] else None)
            old = c.execute('SELECT endpoint,source_catalog,source_schema,source_table,base_revision,remote_sql FROM dq_remote_links WHERE rule_id=?', (rule_id,)).fetchone()
            if old and old[4] and tuple(old[:4]) != (target,source_catalog,source_schema,source_table):
                raise ValueError('Published mappings cannot change source or workspace. Use a new rule.')
            rule = c.execute('SELECT rule_key FROM dq_rules WHERE id=?', (rule_id,)).fetchone()
            if not rule:
                raise ValueError('Rule no longer exists.')
            if not rule[0]:
                c.execute('UPDATE dq_rules SET rule_key=? WHERE id=?', ('rule-'+uuid.uuid4().hex, rule_id))
            if old and old[4] and old[5].strip()!=remote_sql.strip():
                c.row_factory=dict_row_factory
                previous=c.execute('SELECT * FROM dq_rules WHERE id=?',(rule_id,)).fetchone()
                c.row_factory=None
                c.execute('''INSERT INTO dq_rules_history(rule_id,version,status,created_at,description,rule_type,target_table,rule_params,deactivated_by,deactivated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'))''',
                    (rule_id,previous['version'],previous['status'],previous['created_at'],previous['description'],previous['rule_type'],previous['target_table'],
                     json.dumps({'sql_query':old[5],'severity':previous['severity'],'error_message':previous['error_message']}),actor))
                parts=previous['version'].split('.')
                c.execute('UPDATE dq_rules SET version=? WHERE id=?',(f'{parts[0]}.{int(parts[1])+1}',rule_id))
            c.execute('''INSERT INTO dq_remote_links(rule_id,profile,control_catalog,control_schema,source_catalog,source_schema,source_table,remote_sql,endpoint,auto_sync,owner)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(rule_id) DO UPDATE SET profile=excluded.profile,
                control_catalog=excluded.control_catalog,control_schema=excluded.control_schema,
                source_catalog=excluded.source_catalog,source_schema=excluded.source_schema,source_table=excluded.source_table,
                remote_sql=excluded.remote_sql,endpoint=excluded.endpoint,auto_sync=excluded.auto_sync,owner=excluded.owner''',
                (rule_id,profile,control_catalog,control_schema,source_catalog,source_schema,source_table,remote_sql.strip(),target,int(auto_sync),actor))
    finally:
        c.close()


def definition(link_id):
    c = get_connection()
    c.row_factory = dict_row_factory
    try:
        link = c.execute('SELECT * FROM dq_remote_links WHERE id=?', (link_id,)).fetchone()
        if not link:
            raise ValueError('Select a saved mapping.')
        rule = c.execute('SELECT * FROM dq_rules WHERE id=?', (link['rule_id'],)).fetchone()
        payload = {'contract':1,'rule_key':rule['rule_key'],'local_version':rule['version'],
                   'description':rule['description'] or '', 'rule_type':rule['rule_type'], 'severity':rule['severity'],
                   'error_message':rule['error_message'] or '', 'active':rule['status']=='ACTIVE',
                   'source':[link['source_catalog'],link['source_schema'],link['source_table']], 'sql':link['remote_sql']}
        if link.get('plain_sql'):
            from integrations.plain_sql import compile_sql
            from logic.datasets import list_tables
            sql,dependencies=compile_sql(rule['sql_query'],link['source_catalog'],link['source_schema'],list_tables())
            if rule['target_table'] not in dependencies:
                raise ValueError('The rule must read its selected table.')
            dependencies.pop(rule['target_table'])
            payload.update(contract=3,sql=sql,references=dependencies)
        elif rule['cross_spec']:
            from logic.references import remote_references
            spec=json.loads(rule['cross_spec'])
            payload.update(contract=2,cross_spec=spec,references=remote_references(c,spec,link['profile']))
        return link, validate_payload(payload)
    finally:
        c.close()


def rows(cursor, sql, parameters=(), limit=MAX_RUNS):
    cursor.execute(sql, parameters)
    names = [col[0] for col in cursor.description]
    output, size = [], 0
    while True:
        batch = cursor.fetchmany(500)
        if not batch:
            break
        for raw in batch:
            size += sum(len(str(v).encode('utf-8')) + 64 for v in raw)
            if len(output) >= limit or size > 50*1024*1024:
                raise ValueError('Remote data exceeds the import limit. Nothing from this run was imported.')
            output.append(dict(zip(names, raw)))
    return output


def remote_definition(cursor, link, key):
    result = rows(cursor, f"SELECT revision,payload FROM {name(link['control_catalog'],link['control_schema'],'dq_rules')} WHERE rule_key=?", [key], 2)
    if len(result)>1:
        raise ValueError('Duplicate remote rule keys. Resolve them in Databricks before synchronizing.')
    if result:
        payload = validate_payload(json.loads(result[0]['payload']))
        if revision(payload) != result[0]['revision'] or payload['rule_key'] != key:
            raise ValueError('Remote rule checksum does not match its definition.')
        return result[0]
    return None


def compare(link_id, connect=connect_source):
    link, payload = definition(link_id)
    with connect(source_for(link)) as remote, remote.cursor() as cursor:
        found = remote_definition(cursor,link,payload['rule_key'])
    return {'local':payload,'remote':json.loads(found['payload']) if found else None,
            'remote_revision':found['revision'] if found else None,'base_revision':link['base_revision']}


def setup_remote(link_id, actor, connect=connect_source):
    link, payload = definition(link_id)
    c = get_connection()
    try:
        require_superuser(c,actor)
    finally:
        c.close()
    with connect(source_for(link)) as remote, remote.cursor() as cursor:
        cursor.execute('CREATE SCHEMA IF NOT EXISTS '+name(link['control_catalog'],link['control_schema']))
        for table, fields in TABLES.items():
            cursor.execute(f"CREATE TABLE IF NOT EXISTS {name(link['control_catalog'],link['control_schema'],table)} ({fields}) USING DELTA")
        columns=rows(cursor,'DESCRIBE TABLE '+name(link['control_catalog'],link['control_schema'],'dq_runs'))
        if not any(r['col_name']=='reference_versions' for r in columns):
            cursor.execute('ALTER TABLE '+name(link['control_catalog'],link['control_schema'],'dq_runs')+' ADD COLUMNS (reference_versions STRING)')


def accept_remote(link_id, actor, expected_remote, connect=connect_source):
    link, local = definition(link_id)
    with connect(source_for(link)) as remote, remote.cursor() as cursor:
        found = remote_definition(cursor,link,local['rule_key'])
    if not found or found['revision']!=expected_remote:
        raise ValueError('Remote definition changed. Compare again.')
    payload = json.loads(found['payload'])
    if payload.get('cross_spec')!=local.get('cross_spec') or payload.get('references')!=local.get('references'):
        raise ValueError('Cross-table dependencies differ. Configure matching references and a new rule before accepting.')
    if payload['source'] != local['source']:
        raise ValueError('Remote source differs from the saved mapping.')
    c = get_connection()
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            require_superuser(c,actor)
            c.row_factory = dict_row_factory
            old = c.execute('SELECT * FROM dq_rules WHERE id=?',(link['rule_id'],)).fetchone()
            if (link['base_revision']==found['revision'] and link['remote_sql']==payload['sql']
                    and all(old[k]==payload[k] for k in ('description','rule_type','severity','error_message'))
                    and (old['status']=='ACTIVE')==payload['active']):
                return
            parts = old['version'].split('.')
            local_version = f'{parts[0]}.{int(parts[1])+1}'
            c.execute('''INSERT INTO dq_rules_history(rule_id,version,status,created_at,description,rule_type,target_table,rule_params,deactivated_by,deactivated_at)
                VALUES(?,?,?,?,?,?,?,?,?,datetime('now','localtime'))''',
                (old['id'],old['version'],old['status'],old['created_at'],old['description'],old['rule_type'],old['target_table'],
                 json.dumps({'sql_query':old['sql_query'],'severity':old['severity'],'error_message':old['error_message']}),actor))
            c.execute("UPDATE dq_rules SET description=?,rule_type=?,severity=?,error_message=?,status=?,version=?,execution_mode='databricks' WHERE id=?",
                      (payload['description'],payload['rule_type'],payload['severity'],payload['error_message'],'ACTIVE' if payload['active'] else 'INACTIVE',local_version,old['id']))
            c.execute('UPDATE dq_remote_links SET remote_sql=?,base_revision=? WHERE id=?',(payload['sql'],found['revision'],link_id))
            c.execute('INSERT OR IGNORE INTO dq_remote_versions(link_id,revision,local_version,payload) VALUES(?,?,?,?)',
                      (link_id,found['revision'],local_version,canonical(payload)))
    finally:
        c.close()


def publish(link_id, actor, expected_local, expected_remote, connect=connect_source):
    link, payload = definition(link_id)
    c = get_connection()
    try:
        require_superuser(c, actor)
    finally:
        c.close()
    digest = revision(payload)
    if digest != expected_local:
        raise ValueError('Local rule changed. Compare again before publishing.')
    with connect(source_for(link)) as remote, remote.cursor() as cursor:
        found = remote_definition(cursor, link, payload['rule_key'])
        current = found['revision'] if found else None
        if current != expected_remote:
            raise ValueError('Remote rule changed. Compare again before publishing.')
        if current not in (None, link['base_revision'], digest):
            raise ValueError('Conflict: the remote definition changed outside this app. Download its definition first.')
        table = name(link['control_catalog'], link['control_schema'], 'dq_rules')
        cursor.execute(f'''MERGE INTO {table} t USING (SELECT ? AS rule_key, ? AS revision, ? AS payload) s
            ON t.rule_key=s.rule_key WHEN MATCHED AND t.revision <=> ? THEN
            UPDATE SET t.revision=s.revision,t.payload=s.payload,t.updated_at=current_timestamp()
            WHEN NOT MATCHED THEN INSERT(rule_key,revision,payload,updated_at) VALUES(s.rule_key,s.revision,s.payload,current_timestamp())''',
            [payload['rule_key'],digest,canonical(payload),current])
        saved = remote_definition(cursor,link,payload['rule_key'])
        if not saved or saved['revision'] != digest:
            raise ValueError('Concurrent publication detected. Compare definitions again.')
    c = get_connection()
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            require_superuser(c,actor)
            c.execute('INSERT OR IGNORE INTO dq_remote_versions(link_id,revision,local_version,payload) VALUES(?,?,?,?)',
                      (link_id,digest,payload['local_version'],canonical(payload)))
            c.execute('UPDATE dq_remote_links SET base_revision=? WHERE id=?', (digest,link_id))
            c.execute("UPDATE dq_rules SET execution_mode='databricks' WHERE id=?",(link['rule_id'],))
    finally:
        c.close()
    return digest


def import_run(link, run, result, errors, actor):
    payload = validate_payload(json.loads(run['payload']))
    if revision(payload) != run['revision'] or payload['rule_key'] != run['rule_key']:
        raise ValueError('Remote run has an invalid rule snapshot.')
    if payload['source'] != [link['source_catalog'],link['source_schema'],link['source_table']]:
        raise ValueError('Remote run source does not match the mapping.')
    started = datetime.fromisoformat(run['started_at'])
    ended = datetime.fromisoformat(run['completed_at'])
    if started.tzinfo is None or ended.tzinfo is None or ended < started:
        raise ValueError('Remote timestamps must include their timezone.')
    stamp = lambda value: value.astimezone().replace(tzinfo=None).strftime('%Y-%m-%d %H:%M:%S')
    success = run['status'] == 'completed'
    ref_versions=json.loads(run.get('reference_versions') or '{}')
    if success and (set(ref_versions)!=set(payload.get('references',{})) or any(type(v) is not int or v<0 for v in ref_versions.values())):
        raise ValueError('Reference snapshot versions are missing or invalid.')
    if run['status'] not in ('completed','failed'):
        raise ValueError('Run is not complete.')
    if success:
        if len(result)!=1:
            raise ValueError('Run summary is incomplete.')
        result = result[0]
        if any(type(result[k]) is not int or result[k]<0 for k in ('passed','failed')) or len(errors)!=result['failed']:
            raise ValueError('Error rows do not match the complete run summary.')
        if any(e['field_name']!=result['field_name'] or e['record_id'] is None or str(e['record_id'])=='' for e in errors):
            raise ValueError('Invalid error details.')
    c = get_connection()
    try:
        with c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM users WHERE username COLLATE BINARY=? AND active=1',(actor,)).fetchone():
                raise ValueError('Account is inactive.')
            if c.execute('SELECT 1 FROM dq_remote_receipts WHERE endpoint=? AND remote_run_id=?',(link['endpoint'],run['run_id'])).fetchone():
                return False
            rule = c.execute('SELECT rule_key,target_table,execution_mode FROM dq_rules WHERE id=?',(link['rule_id'],)).fetchone()
            if not rule or rule[0]!=payload['rule_key'] or rule[2]!='databricks':
                raise ValueError('The local rule is no longer mapped to Databricks.')
            version = c.execute('SELECT local_version,payload FROM dq_remote_versions WHERE link_id=? AND revision=?',(link['id'],run['revision'])).fetchone()
            if not version or json.loads(version[1])!=payload:
                raise ValueError('Unrecognized remote rule revision. Publish or accept its definition before importing results.')
            last = c.execute('''SELECT MAX(r.started_at) FROM dq_remote_receipts x JOIN dq_runs r ON r.id=x.local_run_id
                WHERE x.endpoint=? AND x.rule_key=?''',(link['endpoint'],payload['rule_key'])).fetchone()[0]
            execution_errors = [] if success else [{'rule_id':link['rule_id'],'version':version[0],'description':payload['description'],'message':run['execution_error']}]
            local_id = c.execute('''INSERT INTO dq_runs(table_name,username,started_at,completed_at,mode,status,rules_requested,rules_completed,execution_errors)
                VALUES(?,?,?,?,?,?,?,?,?)''',(rule[1],actor,stamp(started),stamp(ended),'databricks',run['status'],1,int(success),json.dumps(execution_errors))).lastrowid
            if success:
                c.execute('INSERT INTO dq_results(rule_id,rule_version,failed_count,passed_count,timestamp,run_id) VALUES(?,?,?,?,?,?)',
                          (link['rule_id'],version[0],result['failed'],result['passed'],stamp(ended),local_id))
                c.executemany('''INSERT INTO dq_field_results(rule_id,rule_version,record_id,field_name,field_value,test_result,error_message,timestamp,target_table,run_id)
                    VALUES(?,?,?,?,?,1,?,?,?,?)''',[(link['rule_id'],version[0],e['record_id'],e['field_name'],e['field_value'],e['error_message'],stamp(ended),rule[1],local_id) for e in errors])
                # Late older runs are history only and cannot reopen/close a newer ticket.
                if not last or stamp(started)>=last:
                    sync_ticket(c,link['rule_id'],version[0],rule[1],payload['description'],payload['severity'],local_id,
                                link['owner'],result['failed'],result['failed']+result['passed'],started.astimezone().replace(tzinfo=None))
            c.execute('INSERT INTO dq_remote_receipts(endpoint,remote_run_id,local_run_id,source_version,rule_key,revision) VALUES(?,?,?,?,?,?)',
                      (link['endpoint'],run['run_id'],local_id,run['source_version'],payload['rule_key'],run['revision']))
            c.execute('UPDATE dq_remote_receipts SET reference_versions=? WHERE endpoint=? AND remote_run_id=?',
                      (canonical(ref_versions),link['endpoint'],run['run_id']))
            return True
    finally:
        c.close()


def synchronize(actor, auto_only=False, cancel=None, connect=connect_source):
    with ExitStack() as stack:
        connections={}
        @contextmanager
        def cached(source):
            key=(source.hostname,source.http_path)
            if key not in connections:
                connections[key]=stack.enter_context(connect(source))
            yield connections[key]
        return _synchronize(actor,auto_only,cancel,cached)


def _synchronize(actor, auto_only=False, cancel=None, connect=connect_source):
    imported = 0
    for link in mappings():
        if link['execution_mode']!='databricks' or (auto_only and not link['auto_sync']):
            continue
        try:
            if cancel and cancel.is_set():
                return imported
            with connect(source_for(link)) as remote, remote.cursor() as cursor:
                prefix = (link['control_catalog'],link['control_schema'])
                runs = rows(cursor,f"SELECT * FROM {name(*prefix,'dq_runs')} WHERE rule_key=? AND status IN ('completed','failed') ORDER BY started_at,run_id",[link['rule_key']])
                c = get_connection()
                seen = {r[0] for r in c.execute('SELECT remote_run_id FROM dq_remote_receipts WHERE endpoint=?',(link['endpoint'],))}
                c.close()
                for run in runs:
                    if cancel and cancel.is_set():
                        return imported
                    if run['run_id'] in seen:
                        continue
                    result = rows(cursor,f"SELECT * FROM {name(*prefix,'dq_results')} WHERE run_id=?",[run['run_id']],2) if run['status']=='completed' else []
                    errors = rows(cursor,f"SELECT * FROM {name(*prefix,'dq_errors')} WHERE run_id=?",[run['run_id']],MAX_ERRORS) if run['status']=='completed' else []
                    if cancel and cancel.is_set():
                        return imported
                    imported += import_run(link,run,result,errors,actor)
            c = get_connection()
            with c:
                c.execute("UPDATE dq_remote_links SET last_sync=datetime('now','localtime'),last_error=NULL WHERE id=?",(link['id'],))
            c.close()
        except Exception as error:
            c = get_connection()
            with c:
                c.execute('UPDATE dq_remote_links SET last_error=? WHERE id=?',(str(error),link['id']))
            c.close()
            raise
    return imported
