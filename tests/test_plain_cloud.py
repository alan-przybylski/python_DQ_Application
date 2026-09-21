import json
import threading
import pytest
from database.connection import get_connection
from integrations.plain_sql import compile_sql,versioned_sql
from logic.databricks_profiles import save_profile
from logic.cloud_workspace import upload_table,send_rule
from logic.databricks_import import Source,Snapshot,save_snapshot,local_columns
from logic.rules import save_rule
from logic.dq_engine import run_checks,run_details
from logic.databricks_sync import mappings,definition


@pytest.fixture
def workspace(sqlite_database):
    c=get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
        c.execute('CREATE TABLE countries(id INTEGER PRIMARY KEY,country_code TEXT,currency TEXT)')
        c.executemany('INSERT INTO countries VALUES(?,?,?)',[(10,'PL','PLN'),(20,'FR','EUR')])
    c.close()
    save_profile('cloud',dict(hostname='example.cloud.databricks.com',http_path='/sql/1.0/warehouses/abc',catalog='workspace',schema='dq_app',table='countries'))


@pytest.mark.parametrize('query',[
    'SELECT p.id,p.name,CASE WHEN c.id IS NULL THEN 1 ELSE 0 END AS dq_check FROM customers p LEFT JOIN countries c ON p.name=c.country_code',
    'WITH c AS (SELECT * FROM countries) SELECT p.id,p.name,CASE WHEN EXISTS(SELECT 1 FROM c WHERE c.country_code=p.name) THEN 0 ELSE 1 END AS dq_check FROM customers p',
    'SELECT id,country_code,0 AS dq_check FROM countries UNION ALL SELECT id,name,1 AS dq_check FROM customers',
])
def test_sql_bindings_and_versions(query):
    sql,deps=compile_sql(query,'workspace','dq_app',['customers','countries'])
    assert set(deps)=={'customers','countries'}
    rendered=versioned_sql(sql,deps,{'customers':3,'countries':5})
    assert '`customers` VERSION AS OF 3' in rendered
    assert '`countries` VERSION AS OF 5' in rendered
    assert '{{' not in rendered


@pytest.mark.parametrize('query',[
    'DELETE FROM countries','SELECT * FROM countries; DROP TABLE countries',
    'SELECT * FROM sqlite_master','SELECT * FROM read_csv("secret.csv")',
    'SELECT * FROM other.countries',
])
def test_sql_rejects_non_dataset_access(query):
    with pytest.raises(ValueError):compile_sql(query,'workspace','dq_app',['countries'])


class FakeCloud:
    def __init__(self,fail_batch=False):
        self.statements=[];self.buffer=[];self.count=0;self.payload=None;self.fail_batch=fail_batch
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def cursor(self):return self
    def fetchmany(self,n):
        result,self.buffer=self.buffer[:n],self.buffer[n:]
        return result
    def execute(self,sql,params=()):
        self.statements.append((sql,params))
        self.buffer=[]
        if sql.startswith('INSERT INTO'):
            if self.fail_batch:raise ValueError('Upload interrupted')
            self.count+=len(params)//3
        elif sql.startswith('SELECT COUNT'):
            self.description=[('n',)];self.buffer=[(self.count,)]
        elif 'information_schema' in sql:
            self.description=[('table_name',)]
        elif sql.startswith('DESCRIBE HISTORY'):
            self.description=[('version',)];self.buffer=[(1,)]
        elif sql.startswith('DESCRIBE TABLE'):
            self.description=[('col_name',)];self.buffer=[('reference_versions',)]
        elif sql.startswith('EXPLAIN'):
            self.description=[('plan',)];self.buffer=[('Valid plan',)]
        elif sql.startswith('SELECT * FROM ('):
            self.description=[('id',),('country_code',),('dq_check',)]
        elif sql.startswith('SELECT revision'):
            from integrations.databricks_contract import revision,canonical
            self.description=[('revision',),('payload',)]
            if self.payload:self.buffer=[(revision(self.payload),canonical(self.payload))]
        elif sql.startswith('MERGE'):
            self.payload=json.loads(params[2])


def test_upload_keeps_name_and_ids(workspace):
    remote=FakeCloud()
    assert upload_table('Admin','cloud','countries',connect=lambda source:remote)==2
    assert any(sql.startswith('CREATE TABLE `workspace`.`dq_app`.`countries` USING DELTA AS SELECT') for sql,_ in remote.statements)
    inserts=[params for sql,params in remote.statements if sql.startswith('INSERT INTO')]
    assert inserts==[[10,'PL','PLN',20,'FR','EUR']]
    assert remote.statements[-1][0].startswith('DROP TABLE IF EXISTS')


def test_interrupted_upload_never_replaces_destination(workspace):
    remote=FakeCloud(fail_batch=True)
    with pytest.raises(ValueError,match='interrupted'):
        upload_table('Admin','cloud','countries',replace=True,connect=lambda source:remote)
    assert not any(sql.startswith('CREATE OR REPLACE') for sql,_ in remote.statements)
    assert remote.statements[-1][0].startswith('DROP TABLE IF EXISTS')


def test_send_rule_without_manual_mapping_and_run_locally(workspace):
    rid=save_rule('Check countries','SQL','countries','SELECT id,country_code,0 AS dq_check FROM countries','Invalid')
    remote=FakeCloud()
    send_rule('Admin','cloud',rid,connect=lambda source:remote)
    link,payload=definition(mappings()[0]['id'])
    assert payload['contract']==3
    assert payload['source']==['workspace','dq_app','countries']
    assert payload['references']=={}
    assert link['plain_sql']==1
    result=run_details(run_checks('countries','Admin',include_remote=True))
    assert result['passed']==2


def test_download_preserves_original_id(workspace):
    source=Source('example.cloud.databricks.com','/sql/1.0/warehouses/abc','workspace','dq_app','returned')
    cols=local_columns([('id','bigint'),('country_code','string')],preserve_names=True)
    snapshot=Snapshot(source,cols,[(10,'PL'),(20,'FR')],True)
    save_snapshot(snapshot,'returned','Admin')
    c=get_connection()
    assert c.execute('SELECT * FROM returned ORDER BY id').fetchall()==[(10,'PL'),(20,'FR')]
    assert [r[1] for r in c.execute('PRAGMA table_info(returned)')]==['id','country_code']
    c.close()
