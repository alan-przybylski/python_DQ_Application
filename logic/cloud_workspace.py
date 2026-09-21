"""Same-name table upload and ordinary SQL publication using one saved profile."""
import uuid
from contextlib import contextmanager
from database.connection import get_connection,dict_row_factory
from logic.accounts import require_superuser
from logic.datasets import checked_table,table_columns,quote,list_tables
from logic.databricks_profiles import load_profiles
from logic.databricks_import import Source,connect_source
from logic.databricks_sync import endpoint,definition,setup_remote,compare,publish,rows
from integrations.databricks_contract import name,revision
from integrations.plain_sql import compile_sql


def destination(profile,table):
    settings=load_profiles()['profiles'].get(profile)
    if not settings:
        raise ValueError('Choose a saved Databricks connection.')
    source=Source(**{**settings,'table':table})
    source.validate()
    return source


def upload_table(actor,profile,table,replace=False,cancel=None,connect=connect_source):
    c=get_connection()
    try:
        c.execute('BEGIN')
        require_superuser(c,actor)
        checked_table(c,table)
        columns=table_columns(table,c)
        data=c.execute('SELECT * FROM '+quote(table)).fetchmany(100001)
        if len(data)>100000 or sum(sum(64+len(str(v).encode('utf-8')) for v in row) for row in data)>50*1024*1024:
            raise ValueError('Table exceeds the upload limit: 100000 rows or 50 MB.')
    finally: c.close()
    source=destination(profile,table)
    def check():
        if cancel and cancel.is_set(): raise ValueError('Upload cancelled; destination was not replaced.')
    types={'INTEGER':'BIGINT','REAL':'DOUBLE','TEXT':'STRING','BLOB':'BINARY'}
    fields=[]
    for col in columns:
        if col['type'] not in types: raise ValueError('Unsupported local column type: '+col['type'])
        fields.append(name(col['name'])+' '+types[col['type']])
    stage=name(source.catalog,source.schema,'__dq_upload_'+uuid.uuid4().hex)
    created=False
    check()
    with connect(source) as remote,remote.cursor() as cursor:
        try:
            cursor.execute('CREATE SCHEMA IF NOT EXISTS '+name(source.catalog,source.schema))
            existing=rows(cursor,'SELECT table_name FROM '+name(source.catalog,'information_schema','tables')+' WHERE table_schema=? AND lower(table_name)=lower(?)',[source.schema,source.table],2)
            if existing and not replace:
                raise ValueError('This table already exists in Databricks. Select the replacement option if you want to replace its schema and data.')
            cursor.execute('CREATE TABLE '+stage+' ('+', '.join(fields)+') USING DELTA')
            created=True
            for offset in range(0,len(data),100):
                check()
                batch=data[offset:offset+100]
                cursor.execute('INSERT INTO '+stage+' VALUES '+','.join(['('+','.join('?' for _ in columns)+')']*len(batch)),
                               [v for row in batch for v in row])
            actual=rows(cursor,'SELECT COUNT(*) AS n FROM '+stage,limit=1)[0]['n']
            if actual!=len(data): raise ValueError('Upload verification failed; destination was not changed.')
            check()
            cursor.execute(('CREATE OR REPLACE TABLE ' if replace else 'CREATE TABLE ')+source.sql_name+' USING DELTA AS SELECT * FROM '+stage)
        finally:
            if created: cursor.execute('DROP TABLE IF EXISTS '+stage)
    return len(data)


def send_rule(actor,profile,rule_id,connect=connect_source):
    c=get_connection()
    try:
        require_superuser(c,actor)
        c.row_factory=dict_row_factory
        rule=c.execute('SELECT * FROM dq_rules WHERE id=?',(rule_id,)).fetchone()
        if not rule: raise ValueError('Select a rule.')
        source=destination(profile,rule['target_table'])
        sql,dependencies=compile_sql(rule['sql_query'],source.catalog,source.schema,list_tables())
        if rule['target_table'] not in dependencies:
            raise ValueError('The SQL must read the rule target table.')
    finally: c.close()
    with connect(source) as remote:
        @contextmanager
        def reuse(_): yield remote
        # Validate names, columns and dialect before changing any local mapping.
        with remote.cursor() as cursor:
            for parts in dependencies.values():
                rows(cursor,'DESCRIBE HISTORY '+name(*parts)+' LIMIT 1',limit=1)
            plan=rows(cursor,'EXPLAIN '+sql)
            if any('AnalysisException' in str(value) or '== Errors ==' in str(value) for row in plan for value in row.values()):
                raise ValueError('Databricks could not validate this SQL. Check table names, columns and functions.')
            # LIMIT 0 forces analysis without executing the full data quality check.
            cursor.execute('SELECT * FROM (\n'+sql+'\n) dq_validate LIMIT 0')
            output=[col[0] for col in cursor.description]
            if len(output)<3 or output[0]!='id' or output[1] in ('id','dq_check') or 'dq_check' not in output:
                raise ValueError('Return id, the checked field and dq_check.')
        c=get_connection()
        try:
            with c:
                c.execute('BEGIN IMMEDIATE')
                require_superuser(c,actor)
                current=c.execute('SELECT version,sql_query FROM dq_rules WHERE id=?',(rule_id,)).fetchone()
                if current!=(rule['version'],rule['sql_query']):
                    raise ValueError('The rule changed. Send it again.')
                old=c.execute('SELECT id,endpoint,source_table,base_revision,source_catalog,source_schema FROM dq_remote_links WHERE rule_id=?',(rule_id,)).fetchone()
                target=endpoint(source,source.catalog,'dq_control')
                if old and old[3] and (old[1]!=target or old[2]!=source.table or old[4]!=source.catalog or old[5]!=source.schema):
                    raise ValueError('This legacy rule points to a different remote table. Keep it unchanged and save a new rule with the desired table name.')
                key=rule['rule_key'] or 'rule-'+uuid.uuid4().hex
                c.execute('UPDATE dq_rules SET rule_key=? WHERE id=?',(key,rule_id))
                c.execute('''INSERT INTO dq_remote_links(rule_id,profile,control_catalog,control_schema,source_catalog,source_schema,source_table,remote_sql,endpoint,owner,plain_sql)
                    VALUES(?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(rule_id) DO UPDATE SET profile=excluded.profile,source_catalog=excluded.source_catalog,
                    control_catalog=excluded.control_catalog,control_schema=excluded.control_schema,
                    source_schema=excluded.source_schema,source_table=excluded.source_table,remote_sql=excluded.remote_sql,endpoint=excluded.endpoint,plain_sql=1''',
                          (rule_id,profile,source.catalog,'dq_control',source.catalog,source.schema,source.table,sql,target,actor))
                link_id=c.execute('SELECT id FROM dq_remote_links WHERE rule_id=?',(rule_id,)).fetchone()[0]
        finally: c.close()
        setup_remote(link_id,actor,reuse)
        compared=compare(link_id,reuse)
        return publish(link_id,actor,revision(compared['local']),compared['remote_revision'],reuse)
