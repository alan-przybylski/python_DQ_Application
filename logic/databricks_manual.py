"""Interactive execution using the configured SQL warehouse and published rules."""

from contextlib import ExitStack
from datetime import datetime, timezone
import json
import uuid

from database.connection import get_connection
from integrations.databricks_contract import name, template_sql, canonical, snapshot_sql
from logic.databricks_import import connect_source
from logic.databricks_sync import mappings, source_for, remote_definition, rows, import_run


def run_remote_checks(actor, link_id=None, cancel=None, connect=connect_source, table=None, profile=None):
    c = get_connection()
    try:
        if not c.execute('SELECT 1 FROM users WHERE username=? COLLATE BINARY AND active=1', (actor,)).fetchone():
            raise ValueError('Account is inactive.')
        active = {r[0] for r in c.execute("SELECT id FROM dq_rules WHERE status='ACTIVE'")}
        known = {(r[0], r[1]) for r in c.execute('SELECT link_id,revision FROM dq_remote_versions')}
    finally:
        c.close()
    links = [l for l in mappings() if l['execution_mode']=='databricks' and l['rule_id'] in active
             and any(key[0] == l['id'] for key in known)
             and (profile is None or l['profile']==profile)
             and (table is None or l['target_table']==table)
             and (link_id is None or l['id']==link_id)]
    if not links:
        raise ValueError('No active published Databricks rules to run.')
    completed, failures = 0, []
    with ExitStack() as stack:
        connections = {}
        for link in links:
            if cancel and cancel.is_set():
                break
            try:
                source = source_for(link)
                key = (source.hostname, source.http_path)
                if key not in connections:
                    connections[key] = stack.enter_context(connect(source))
                with connections[key].cursor() as cursor:
                    found = remote_definition(cursor, link, link['rule_key'])
                    if not found or (link['id'],found['revision']) not in known:
                        raise ValueError('Compare and accept or publish the remote definition before running it.')
                    payload = json.loads(found['payload'])
                    if payload['source'] != [link['source_catalog'],link['source_schema'],link['source_table']]:
                        raise ValueError('Remote source differs from the mapping.')
                    if not payload['active']:
                        if link_id is not None:
                            raise ValueError('The published rule is inactive.')
                        continue
                    run = dict(run_id=uuid.uuid4().hex,rule_key=link['rule_key'],revision=found['revision'],
                               payload=canonical(payload),started_at=datetime.now(timezone.utc).isoformat(),
                               completed_at=None,status='running',source_version=None,execution_error=None)
                    prefix = (link['control_catalog'],link['control_schema'])
                    cursor.execute(f"INSERT INTO {name(*prefix,'dq_runs')} (run_id,rule_key,revision,payload,started_at,status) VALUES (?,?,?,?,?,?)",
                                   [run[k] for k in ('run_id','rule_key','revision','payload','started_at','status')])
                    result, errors = [], []
                    try:
                        version = rows(cursor, 'DESCRIBE HISTORY '+name(*payload['source'])+' LIMIT 1',limit=1)[0]['version']
                        run['source_version'] = int(version)
                        versions={alias:int(rows(cursor,'DESCRIBE HISTORY '+name(*parts)+' LIMIT 1',limit=1)[0]['version']) for alias,parts in payload.get('references',{}).items()}
                        run['reference_versions']=canonical(versions)
                        sql = snapshot_sql(payload,version,versions)
                        records = rows(cursor, 'SELECT * FROM (\n'+sql+'\n) dq_checked',limit=100000)
                        columns = [col[0] for col in cursor.description]
                        if len(columns)<3 or columns[0]!='id' or columns[1] in ('id','dq_check') or 'dq_check' not in columns or len(set(columns))!=len(columns):
                            raise ValueError('Return id, the checked field second, and dq_check.')
                        field = columns[1]
                        if any(r['id'] is None or str(r['id'])=='' or type(r['dq_check']) is not int or r['dq_check'] not in (0,1) for r in records):
                            raise ValueError('Invalid id or dq_check: expected integer 0 PASS or 1 FAIL.')
                        errors = [dict(run_id=run['run_id'],record_id=str(r['id']),field_name=field,
                                       field_value=None if r[field] is None else str(r[field]),error_message=payload['error_message'])
                                  for r in records if r['dq_check']==1]
                        # Parameterized batches avoid one network round trip per finding.
                        for offset in range(0,len(errors),100):
                            batch = errors[offset:offset+100]
                            cursor.execute(f"INSERT INTO {name(*prefix,'dq_errors')} (run_id,record_id,field_name,field_value,error_message) VALUES "+','.join(['(?,?,?,?,?)']*len(batch)),
                                           [e[k] for e in batch for k in ('run_id','record_id','field_name','field_value','error_message')])
                        result = [dict(run_id=run['run_id'],passed=len(records)-len(errors),failed=len(errors),field_name=field)]
                        cursor.execute(f"INSERT INTO {name(*prefix,'dq_results')} (run_id,passed,failed,field_name) VALUES (?,?,?,?)",
                                       [result[0][k] for k in ('run_id','passed','failed','field_name')])
                        run['status'] = 'completed'
                    except Exception as error:
                        run.update(status='failed',execution_error=str(error)[:4000])
                        result, errors = [], []
                    run['completed_at'] = datetime.now(timezone.utc).isoformat()
                    if payload['contract']>=2:
                        cursor.execute(f"UPDATE {name(*prefix,'dq_runs')} SET reference_versions=? WHERE run_id=?",[run.get('reference_versions'),run['run_id']])
                    cursor.execute(f"UPDATE {name(*prefix,'dq_runs')} SET status=?,completed_at=?,source_version=?,execution_error=? WHERE run_id=?",
                                   [run[k] for k in ('status','completed_at','source_version','execution_error','run_id')])
                    import_run(link,run,result,errors,actor)
                    if run['status']=='failed':
                        raise ValueError(run['execution_error'])
                    completed += 1
            except Exception as error:
                failures.append(link['rule_key']+': '+str(error))
    if failures:
        raise ValueError(f'Completed: {completed}. Failed: {len(failures)}.\n'+'\n'.join(failures))
    return completed
