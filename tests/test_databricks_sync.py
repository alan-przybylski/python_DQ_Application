from datetime import datetime, timezone, timedelta
import json

import pytest

from database.connection import get_connection
from integrations.databricks_contract import canonical, revision, template_sql
from logic.databricks_profiles import save_profile
from logic.databricks_sync import save_mapping, definition, mappings, import_run, publish
from logic.dq_engine import run_checks
from logic.rules import save_rule
from logic.tickets import list_tickets


@pytest.fixture
def linked(sqlite_database):
    c=get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
    c.close()
    save_profile('test',{'hostname':'example.cloud.databricks.com','http_path':'/sql/1.0/warehouses/abc',
                         'catalog':'workspace','schema':'data','table':'customers'})
    rid=save_rule('Name','required','customers','SELECT id,name,0 AS dq_check FROM customers','Missing',severity='high')
    save_mapping(rid,'Admin','test','workspace','dq_control','workspace','data','customers',
                 'SELECT id,name,CASE WHEN name IS NULL THEN 1 ELSE 0 END AS dq_check FROM {{source}}',True)
    link,payload=definition(mappings()[0]['id'])
    c=get_connection()
    with c:
        c.execute("UPDATE dq_rules SET execution_mode='databricks' WHERE id=?",(rid,))
        c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)',(link['id'],revision(payload),'1.0',canonical(payload)))
    c.close()
    return link,payload


def bundle(payload, rid='remote-1', days=0, failed=1):
    started=datetime(2026,1,1,8,tzinfo=timezone.utc)+timedelta(days=days)
    run={'run_id':rid,'rule_key':payload['rule_key'],'revision':revision(payload),'payload':canonical(payload),
         'started_at':started.isoformat(),'completed_at':(started+timedelta(minutes=1)).isoformat(),
         'status':'completed','source_version':12,'execution_error':None}
    result=[{'run_id':rid,'passed':2,'failed':failed,'field_name':'name'}]
    errors=[{'run_id':rid,'record_id':'source-42','field_name':'name','field_value':None,'error_message':'Missing'}] if failed else []
    return run,result,errors


def test_idempotent_import_and_remote_ticket_dates(linked):
    link,payload=linked
    data=bundle(payload)
    assert import_run(link,*data,'Admin')
    assert not import_run(link,*data,'Admin')
    ticket=list_tickets()[0]
    assert datetime.fromisoformat(ticket['due_at'])-datetime.fromisoformat(ticket['created_at'])==timedelta(days=1)
    assert ticket['created_at'].startswith('2026-01-01')
    assert import_run(link,*bundle(payload,'remote-2',days=2,failed=0),'Admin')
    assert list_tickets()[0]['status']=='closed'
    assert import_run(link,*bundle(payload,'late',days=1),'Admin')
    assert len(list_tickets())==1 and list_tickets()[0]['status']=='closed'
    c=get_connection()
    assert c.execute('SELECT record_id FROM dq_field_results LIMIT 1').fetchone()[0]=='source-42'
    assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
    c.close()


def test_incomplete_data_and_unknown_revision_do_not_import(linked):
    link,payload=linked
    run,result,errors=bundle(payload)
    with pytest.raises(ValueError): import_run(link,run,result,[],'Admin')
    changed={**payload,'severity':'low'}
    with pytest.raises(ValueError): import_run(link,*bundle(changed),'Admin')
    c=get_connection()
    assert c.execute('SELECT COUNT(*) FROM dq_runs').fetchone()[0]==0
    c.close()


def test_failed_remote_run_does_not_close_ticket(linked):
    link,payload=linked
    import_run(link,*bundle(payload),'Admin')
    run,_,_=bundle(payload,'failed',days=1)
    run.update(status='failed',execution_error='SQL failed')
    assert import_run(link,run,[],[],'Admin')
    assert list_tickets()[0]['status']=='new'
    rid=run_checks('customers','Admin')
    c=get_connection()
    assert c.execute('SELECT status FROM dq_runs WHERE id=?',(rid,)).fetchone()[0]=='no_rules'
    c.close()


@pytest.mark.parametrize('sql',[
    'DELETE FROM {{source}}', 'SELECT * FROM {{source}}; DELETE FROM x',
    'SELECT * FROM {{source}} JOIN other ON true', 'SELECT * FROM {{source}}, other',
    'SELECT * FROM real_table', 'SELECT (SELECT 1 FROM x) FROM {{source}}',
])
def test_restricted_snapshot_template(sql):
    with pytest.raises(ValueError): template_sql(sql)


class FakeCursor:
    def __init__(self,payload): self.payload=payload; self.buffer=[]; self.writes=0
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,params=()):
        if sql.startswith('SELECT'):
            self.description=[('revision',),('payload',)]
            self.buffer=[(revision(self.payload),canonical(self.payload))] if self.payload else []
        elif sql.startswith('MERGE'):
            self.writes+=1
            self.payload=json.loads(params[2])
    def fetchmany(self,n):
        result,self.buffer=self.buffer[:n],self.buffer[n:]
        return result


class FakeRemote:
    def __init__(self,cursor): self.value=cursor
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def cursor(self): return self.value


def test_publish_conflict_and_explicit_success(linked):
    link,payload=linked
    changed={**payload,'description':'Changed remotely'}
    cursor=FakeCursor(changed)
    connect=lambda source:FakeRemote(cursor)
    with pytest.raises(ValueError): publish(link['id'],'Admin',revision(payload),revision(changed),connect)
    assert cursor.writes==0
    cursor.payload=None
    assert publish(link['id'],'Admin',revision(payload),None,connect)==revision(payload)
    assert cursor.writes==1


def test_accept_remote_is_idempotent_and_keeps_local_sql(linked):
    from logic.databricks_sync import accept_remote
    link,payload=linked
    changed={**payload,'description':'Changed remotely','severity':'low'}
    connect=lambda source:FakeRemote(FakeCursor(changed))
    accept_remote(link['id'],'Admin',revision(changed),connect)
    accept_remote(link['id'],'Admin',revision(changed),connect)
    c=get_connection()
    rule=c.execute('SELECT version,severity,sql_query FROM dq_rules WHERE id=?',(link['rule_id'],)).fetchone()
    assert rule==('1.1','low','SELECT id,name,0 AS dq_check FROM customers')
    assert c.execute('SELECT COUNT(*) FROM dq_rules_history').fetchone()[0]==1
    c.close()


def test_standalone_notebook_compiles(tmp_path):
    from scripts.build_databricks_notebook import build
    notebook=build(tmp_path/'job.py').read_text(encoding='utf-8')
    compile(notebook,'job.py','exec')
    assert 'from integrations' not in notebook
    assert 'def run_job(' in notebook


class HistoryCursor:
    def __init__(self, bundles):
        self.bundles = bundles
        self.buffer = []

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def execute(self, sql, params=()):
        if '`dq_runs`' in sql:
            records = [b[0] for b in self.bundles if b[0]['rule_key'] == params[0]]
        elif '`dq_results`' in sql:
            records = [r for b in self.bundles for r in b[1] if r['run_id'] == params[0]]
        else:
            records = [e for b in self.bundles for e in b[2] if e['run_id'] == params[0]]
        keys = list(records[0]) if records else []
        self.description = [(key,) for key in keys]
        self.buffer = [tuple(row[key] for key in keys) for row in records]

    def fetchmany(self, n):
        result, self.buffer = self.buffer[:n], self.buffer[n:]
        return result


def test_daily_checks_are_separate_history_objects_and_retry_is_idempotent(linked):
    from logic.databricks_sync import synchronize
    from logic.dq_engine import runs_for_table, run_details
    link, payload = linked
    bundles = [bundle(payload, f'day-{day}', days=day, failed=day % 2) for day in range(3)]
    connect = lambda source: FakeRemote(HistoryCursor(bundles))
    report = synchronize('Admin', connect=connect, detailed=True)
    assert (report.imported, report.existing, report.available) == (3, 0, 3)
    runs = runs_for_table('customers')
    assert len(runs) == 3
    assert [run_details(r['id'])['remote']['remote_run_id'] for r in runs] == ['day-2','day-1','day-0']
    assert all(r['rules_requested'] == 1 and r['rule_description'] == payload['description'] for r in runs)
    repeat = synchronize('Admin', connect=connect, detailed=True)
    assert (repeat.imported, repeat.existing) == (0, 3)
    assert '2026-01-03' in repeat.message()
    assert len(runs_for_table('customers')) == 3


def test_bad_run_does_not_block_later_days_or_other_checks(linked):
    from logic.databricks_sync import synchronize
    link, payload = linked
    bad = bundle(payload, 'incomplete')
    later = bundle(payload, 'next-day', days=1, failed=0)
    rid = save_rule('Second check','required','customers','SELECT id,name,0 AS dq_check FROM customers','Missing')
    save_mapping(rid,'Admin','test','workspace','dq_control','workspace','data','customers',payload['sql'])
    other_link, other_payload = definition(mappings()[-1]['id'])
    c = get_connection()
    with c:
        c.execute("UPDATE dq_rules SET execution_mode='databricks' WHERE id=?", (rid,))
        c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)',
                  (other_link['id'],revision(other_payload),'1.0',canonical(other_payload)))
    c.close()
    other = bundle(other_payload, 'other-check', days=1, failed=0)
    report = synchronize('Admin', detailed=True, connect=lambda source: FakeRemote(HistoryCursor([
        (bad[0],bad[1],[]), later, other])))
    assert report.imported == 2
    assert len(report.errors) == 1 and 'incomplete' in report.errors[0]
    c = get_connection()
    assert c.execute('SELECT COUNT(*) FROM dq_runs').fetchone()[0] == 2
    assert 'incomplete' in c.execute('SELECT last_error FROM dq_remote_links WHERE id=?',(link['id'],)).fetchone()[0]
    c.close()


def test_sync_reports_execution_failure_and_empty_remote_history(linked):
    from logic.databricks_sync import synchronize
    link, payload = linked
    empty = synchronize('Admin', detailed=True, connect=lambda source: FakeRemote(HistoryCursor([])))
    assert empty.available == 0 and 'setup_only=false' in empty.message()
    run, _, _ = bundle(payload)
    run.update(status='failed',execution_error='SQL failed')
    report = synchronize('Admin', detailed=True, connect=lambda source: FakeRemote(HistoryCursor([(run,[],[])])))
    assert report.imported == report.failed_runs == 1


def test_import_rejects_evidence_from_different_run(linked):
    link, payload = linked
    run, result, errors = bundle(payload)
    errors[0]['run_id'] = 'another-run'
    with pytest.raises(ValueError, match='another remote run'):
        import_run(link,run,result,errors,'Admin')


def test_notebook_executes_checks_by_default_and_explains_setup_only(monkeypatch,capsys):
    from pathlib import Path
    from types import SimpleNamespace
    from integrations import databricks_runner
    calls = []
    monkeypatch.setattr(databricks_runner,'setup',lambda *args: calls.append('setup'))
    monkeypatch.setattr(databricks_runner,'run_job',lambda *args: calls.append('run') or {'completed':3})
    class Widgets:
        def __init__(self, initial=None): self.values = dict(initial or {})
        def text(self, key, default): self.values.setdefault(key,default)
        def dropdown(self, key, default, choices): self.values.setdefault(key,default)
        def get(self, key): return self.values[key]
    code = Path('databricks_dq_job.py').read_text(encoding='utf-8')
    exec(compile(code,'job','exec'),{'dbutils':SimpleNamespace(widgets=Widgets()),'spark':object()})
    assert calls == ['setup','run']
    calls.clear()
    exec(compile(code,'job','exec'),{'dbutils':SimpleNamespace(widgets=Widgets({'setup_only':'true'})),'spark':object()})
    assert calls == ['setup']
    assert 'SETUP ONLY: no checks executed' in capsys.readouterr().out


def test_job_without_active_rules_is_not_a_success(linked,monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace
    from integrations.databricks_runner import run_job
    sql = ModuleType('pyspark.sql')
    sql.functions = SimpleNamespace()
    types = ModuleType('pyspark.sql.types')
    for name in ('ByteType','ShortType','IntegerType','LongType'):
        setattr(types,name,type(name,(),{}))
    monkeypatch.setitem(sys.modules,'pyspark',ModuleType('pyspark'))
    monkeypatch.setitem(sys.modules,'pyspark.sql',sql)
    monkeypatch.setitem(sys.modules,'pyspark.sql.types',types)
    payload = {**linked[1],'active':False}
    for records in ([],[{'rule_key':payload['rule_key'],'payload':canonical(payload),'revision':revision(payload)}]):
        spark = SimpleNamespace(conf=SimpleNamespace(set=lambda *args:None),
                                table=lambda name:SimpleNamespace(collect=lambda:records))
        with pytest.raises(RuntimeError,match='No active DQ rules'):
            run_job(spark,'workspace','dq_control')


class ExecutionCursor(FakeCursor):
    def __init__(self,payload,flag=1):
        super().__init__(payload)
        self.flag=flag
        self.statements=[]

    def execute(self,sql,params=()):
        self.statements.append((sql,params))
        if sql.startswith('DESCRIBE HISTORY'):
            self.description=[('version',)]
            self.buffer=[(12,)]
        elif sql.startswith('SELECT * FROM ('):
            assert 'VERSION AS OF 12' in sql
            self.description=[('id',),('name',),('dq_check',)]
            self.buffer=[('source-42',None,self.flag),('source-43','Valid',0)]
        elif sql.startswith('SELECT revision,payload'):
            super().execute(sql,params)


def test_manual_cloud_execution_imports_and_uses_published_snapshot(linked):
    from logic.databricks_manual import run_remote_checks
    link,payload=linked
    cursor=ExecutionCursor(payload)
    assert run_remote_checks('Admin',link['id'],connect=lambda source:FakeRemote(cursor))==1
    assert len(list_tickets())==1
    c=get_connection()
    assert c.execute('SELECT passed_count,failed_count FROM dq_results').fetchone()==(1,1)
    assert c.execute('SELECT source_version FROM dq_remote_receipts').fetchone()[0]==12
    c.close()
    writes=[sql for sql,_ in cursor.statements if sql.startswith(('INSERT','UPDATE'))]
    assert '`dq_errors`' in writes[1]
    assert writes[-1].startswith('UPDATE')


def test_manual_invalid_flags_record_failed_execution(linked):
    from logic.databricks_manual import run_remote_checks
    link,payload=linked
    cursor=ExecutionCursor(payload,flag=2)
    with pytest.raises(ValueError,match='Failed: 1'):
        run_remote_checks('Admin',connect=lambda source:FakeRemote(cursor))
    c=get_connection()
    assert c.execute('SELECT status FROM dq_runs').fetchone()[0]=='failed'
    assert c.execute('SELECT COUNT(*) FROM dq_results').fetchone()[0]==0
    c.close()


def test_manual_unknown_revision_does_not_execute(linked):
    from logic.databricks_manual import run_remote_checks
    link,payload=linked
    cursor=ExecutionCursor({**payload,'severity':'low'})
    with pytest.raises(ValueError,match='Compare and accept'):
        run_remote_checks('Admin',connect=lambda source:FakeRemote(cursor))
    assert not any(sql.startswith(('INSERT','DESCRIBE')) for sql,_ in cursor.statements)


def test_manual_table_filter_prevents_unrelated_execution(linked):
    from logic.databricks_manual import run_remote_checks
    def connect(source):
        pytest.fail('Must not connect for another table')
    with pytest.raises(ValueError,match='No active published'):
        run_remote_checks('Admin',table='another_dataset',connect=connect)


@pytest.fixture(scope='module')
def gui_root():
    import os
    if os.environ.get('DQ_GUI_TESTS')!='1':
        pytest.skip('Requires desktop')
    import tkinter as tk
    root=tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.gui
def test_report_dialog_selects_and_dispatches_cloud_rules(linked,monkeypatch,gui_root):
    import tkinter as tk
    from ui.check_dq_panel import CheckDqPanel
    root=gui_root
    panel=CheckDqPanel.__new__(CheckDqPanel)
    panel.root=root
    panel.report_table=tk.StringVar(root,value='customers')
    calls=[]
    monkeypatch.setattr(panel,'run_cloud_from_dialog',lambda dialog,table,rule_id:calls.append((table,rule_id)))
    try:
        panel.open_dq_dialog()
        root.update()
        assert panel.execution_location.get()=='Databricks'
        assert len(panel.rules_dict)==1
        dialog=next(child for child in root.winfo_children() if isinstance(child,tk.Toplevel))
        panel.run_dq_from_dialog(dialog)
        assert calls==[('customers',None)]
        panel.run_type.set('single')
        panel.run_dq_from_dialog(dialog)
        assert calls[-1]==('customers',linked[0]['rule_id'])
    finally:
        for child in root.winfo_children():
            child.destroy()


@pytest.mark.gui
def test_sync_window(linked,gui_root):
    import os
    if os.environ.get('DQ_GUI_TESTS')!='1':
        pytest.skip('Requires desktop')
    import tkinter as tk
    from ui.databricks_sync_window import DatabricksSyncWindow
    root=gui_root
    window=tk.Toplevel(root)
    try:
        view=DatabricksSyncWindow(window,'Admin','superuser',root,tk.StringVar(root))
        root.update()
        assert view.table.get()=='customers'
        assert len(view.rules)==1
        assert len(view.buttons)==6
        assert all(button.winfo_ismapped() for button in view.buttons)
        assert all(button.winfo_rooty()+button.winfo_height()<=window.winfo_rooty()+window.winfo_height() for button in view.buttons)
        if os.environ.get('DQ_CAPTURE_UI')=='1':
            from pathlib import Path
            from PIL import ImageGrab
            Path('artifacts').mkdir(exist_ok=True)
            ImageGrab.grab(window=window.winfo_id()).save('artifacts/simple-databricks.png')
        view.close()
    finally:
        for child in root.winfo_children():
            child.destroy()


@pytest.mark.gui
def test_sync_dialog_explains_zero_downloads(linked,gui_root,monkeypatch):
    import tkinter as tk
    from ui.cloud_window import CloudWindow
    from logic.databricks_sync import SyncReport
    from config.i18n import set_language
    set_language('EN',persist=False)
    notices = []
    monkeypatch.setattr('ui.cloud_window.messagebox.showwarning',lambda title,text,**kwargs:notices.append(text))
    win = tk.Toplevel(gui_root)
    view = CloudWindow(win,'Admin','superuser',gui_root,tk.StringVar(gui_root))
    win.after_cancel(view.poll_id)
    report = SyncReport(targets=['workspace.dq_control.dq_runs'])
    view.events.put((True,report))
    try:
        view.poll()
        assert 'Downloaded checks: 0' in view.status.get()
        assert len(notices) == 1 and 'setup_only=false' in notices[0]
    finally:
        view.close()


@pytest.mark.gui
def test_cloud_rule_definition_shows_runnable_local_sql(linked,gui_root):
    import tkinter as tk
    from types import SimpleNamespace
    from ui.rule_details import RuleDetailsWindow
    window=tk.Toplevel(gui_root)
    library=SimpleNamespace(root=gui_root,role='superuser')
    view=RuleDetailsWindow(window,linked[0]['rule_id'],library)
    def texts(parent):
        result=[]
        for child in parent.winfo_children():
            if isinstance(child,tk.Text): result.append(child.get('1.0','end-1c'))
            result.extend(texts(child))
        return result
    try:
        gui_root.update()
        content=texts(view.pages[0])
        assert 'SELECT id,name,0 AS dq_check FROM customers' in content
        assert all('{{source}}' not in text for text in content)
    finally:
        window.destroy()
