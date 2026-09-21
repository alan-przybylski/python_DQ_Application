import json
import os
import pytest
from database.connection import get_connection
from integrations.cross_table import compile_check
from integrations.databricks_contract import validate_payload, snapshot_sql, revision, canonical
from logic.references import save_reference, create_cross_rule
from logic.dq_engine import run_checks, run_details
from logic.databricks_profiles import save_profile
from logic.databricks_sync import save_mapping, mappings, definition, import_run


@pytest.fixture
def country_setup(sqlite_database):
    c=get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
        c.execute('CREATE TABLE products (id INTEGER PRIMARY KEY,country_code TEXT,currency TEXT)')
        c.execute('CREATE TABLE countries (id INTEGER PRIMARY KEY,country_code TEXT,currency_code TEXT,active_flag INTEGER)')
        c.executemany('INSERT INTO products(country_code,currency) VALUES(?,?)',[
            ('PL','PLN'),('PL','EUR'),('FRA','EUR'),('FR','EUR'),(None,'EUR'),(' pl ','pln'),('RU','RUB')])
        c.executemany('INSERT INTO countries(country_code,currency_code,active_flag) VALUES(?,?,?)',[
            ('PL','PLN',1),('PL','PLN',1),('FR','EUR',1),('RU','RUB',0)])
    c.close()
    save_profile('cloud',{'hostname':'example.cloud.databricks.com','http_path':'/sql/1.0/warehouses/abc','catalog':'workspace','schema':'dq_app','table':'products'})
    save_reference('Admin','countries','countries','cloud','workspace','dq_app','ref_countries')
    return dict(reference='countries',key='id',pairs=[['country_code','country_code'],['currency','currency_code']],
                mode='exists',nulls='fail',normalize=False,active_column='active_flag')


@pytest.mark.parametrize('options,passed',[
    ({},2),({'normalize':True},3),({'nulls':'skip'},3),({'mode':'missing'},4),
])
def test_local_cross_checks_no_duplicate_inflation(country_setup,options,passed):
    spec={**country_setup,**options}
    create_cross_rule('Admin','Country and currency','products',spec,'Invalid pair','high')
    result=run_details(run_checks('products','Admin'))
    assert result['passed']==passed
    assert result['failed']==7-passed
    assert result['status']=='completed'


def test_missing_reference_is_execution_failure(country_setup):
    create_cross_rule('Admin','Country and currency','products',country_setup,'Invalid pair')
    c=get_connection()
    with c: c.execute("DELETE FROM dq_references WHERE alias='countries'")
    c.close()
    result=run_details(run_checks('products','Admin'))
    assert result['rules_completed']==0
    assert len(result['execution_errors'])==1
    assert result['failed']==0


def mapped(spec):
    rid=create_cross_rule('Admin','Country and currency','products',spec,'Invalid pair')
    save_mapping(rid,'Admin','cloud','workspace','dq_control','workspace','dq_app','products',compile_check(spec))
    return definition(mappings()[0]['id'])


def test_remote_payload_and_snapshot_compilation(country_setup):
    link,payload=mapped(country_setup)
    assert payload['contract']==2
    assert payload['references']=={'countries':['workspace','dq_app','ref_countries']}
    validate_payload(payload)
    sql=snapshot_sql(payload,10,{'countries':4})
    assert '`products` VERSION AS OF 10' in sql
    assert '`ref_countries` VERSION AS OF 4' in sql
    assert '{{' not in sql
    with pytest.raises(ValueError):
        validate_payload({**payload,'sql':payload['sql']+'; DELETE FROM x'})


def test_import_requires_reference_versions(country_setup):
    link,payload=mapped(country_setup)
    c=get_connection()
    with c:
        c.execute("UPDATE dq_rules SET execution_mode='databricks'")
        c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)',(link['id'],revision(payload),'1.0',canonical(payload)))
    c.close()
    run=dict(run_id='r1',rule_key=payload['rule_key'],revision=revision(payload),payload=canonical(payload),
             started_at='2026-09-21T10:00:00+00:00',completed_at='2026-09-21T10:01:00+00:00',status='completed',source_version=10,execution_error=None)
    results=[dict(run_id='r1',passed=7,failed=0,field_name='country_code')]
    with pytest.raises(ValueError,match='snapshot'):
        import_run(link,run,results,[],'Admin')
    run['reference_versions']='{"countries":4}'
    assert import_run(link,run,results,[],'Admin')
    c=get_connection()
    assert json.loads(c.execute('SELECT reference_versions FROM dq_remote_receipts').fetchone()[0])=={'countries':4}
    c.close()


def test_cross_rule_git_roundtrip(country_setup,tmp_path):
    from logic.rule_files import export_rules,import_rules,read_definitions
    create_cross_rule('Admin','Country and currency','products',country_setup,'Invalid pair')
    export_rules(tmp_path/'rules','Admin')
    assert read_definitions(tmp_path/'rules')[0]['cross_spec']==country_setup
    assert import_rules(tmp_path/'rules','Admin')['unchanged']==1


def test_manual_cross_execution_saves_both_versions(country_setup):
    from logic.databricks_manual import run_remote_checks
    link,payload=mapped(country_setup)
    c=get_connection()
    with c:
        c.execute("UPDATE dq_rules SET execution_mode='databricks'")
        c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)',(link['id'],revision(payload),'1.0',canonical(payload)))
    class Remote:
        def __init__(self): self.buffer=[]; self.updates=[]
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def cursor(self): return self
        def execute(self,sql,params=()):
            if sql.startswith('SELECT revision'):
                self.description=[('revision',),('payload',)]
                self.buffer=[(revision(payload),canonical(payload))]
            elif sql.startswith('DESCRIBE HISTORY'):
                self.description=[('version',)]
                self.buffer=[(4 if 'ref_countries' in sql else 12,)]
            elif sql.startswith('SELECT * FROM ('):
                assert '`ref_countries` VERSION AS OF 4' in sql
                assert '`products` VERSION AS OF 12' in sql
                sql=sql.replace('`workspace`.`dq_app`.`ref_countries` VERSION AS OF 4','countries').replace('`workspace`.`dq_app`.`products` VERSION AS OF 12','products')
                result=c.execute(sql)
                self.description=result.description
                self.buffer=result.fetchall()
            elif sql.startswith('UPDATE'):
                self.updates.append((sql,params))
        def fetchmany(self,n):
            result,self.buffer=self.buffer[:n],self.buffer[n:]
            return result
    remote=Remote()
    try:
        assert run_remote_checks('Admin',connect=lambda source:remote)==1
        assert c.execute('SELECT passed_count,failed_count FROM dq_results').fetchone()==(2,5)
        assert json.loads(c.execute('SELECT reference_versions FROM dq_remote_receipts').fetchone()[0])=={'countries':4}
        assert any('reference_versions' in sql for sql,_ in remote.updates)
    finally: c.close()


@pytest.mark.gui
@pytest.mark.skipif(os.environ.get('DQ_GUI_TESTS')!='1',reason='Requires desktop')
def test_builder_creates_rule(country_setup,monkeypatch):
    import tkinter as tk
    from ui.cross_table_window import CrossTableWindow
    from tkinter import messagebox
    root=tk.Tk()
    root.withdraw()
    win=tk.Toplevel(root)
    monkeypatch.setattr(messagebox,'showinfo',lambda *a,**k:None)
    monkeypatch.setattr('ui.cross_table_window.error_box',lambda error,*a:pytest.fail(str(error)))
    try:
        view=CrossTableWindow(win,'Admin',lambda:None)
        view.vars['description'].set('Country and currency')
        view.vars['table'].set('products')
        view.update_columns()
        for a,b in country_setup['pairs']:
            view.source_column.set(a)
            view.reference_column.set(b)
            view.add_pair()
        view.show_sql()
        root.update()
        assert 'EXISTS' in view.preview.get('1.0','end')
        view.create()
        assert run_details(run_checks('products','Admin'))['failed']==5
    finally: root.destroy()
