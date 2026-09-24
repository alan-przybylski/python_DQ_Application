import threading
import pytest

from database.connection import get_connection, initialize_database
from integrations.databricks_contract import revision, canonical, snapshot_sql
from integrations.plain_sql import native_sql
from logic.databricks_profiles import save_profile
from logic.databricks_workspace import save_draft, preview_query, execute, browse
from logic.databricks_sync import definition, import_run, synchronize
from logic.dq_engine import run_checks, trend_for_table
from logic.workspaces import run_ids, report_tables

SQL = '''SELECT p.product_id AS id, p.country_code,
CASE WHEN c.country_code IS NULL THEN 1 ELSE 0 END AS dq_check
FROM workspace.dq_app.products p
LEFT JOIN workspace.dq_app.ref_countries c ON p.country_code=c.country_code'''


@pytest.fixture
def cloud_profile(sqlite_database):
    c = get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
    c.close()
    save_profile('cloud', dict(hostname='example.cloud.databricks.com', http_path='/sql/1.0/warehouses/abc',
                              catalog='workspace', schema='dq_app', table=''))
    return sqlite_database


def test_native_join_without_local_datasets_and_idempotent_migration(cloud_profile):
    link_id = save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Country exists', SQL)
    initialize_database(cloud_profile)
    link, payload = definition(link_id)
    assert payload['contract'] == 3
    assert payload['references'] == {'table_1': ['workspace', 'dq_app', 'ref_countries']}
    query = snapshot_sql(payload, 12, {'table_1': 7})
    assert 'VERSION AS OF 12' in query and 'VERSION AS OF 7' in query
    assert '{{' not in query
    c = get_connection()
    assert not c.execute("SELECT name FROM sqlite_master WHERE name IN ('products','ref_countries')").fetchall()
    assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    assert c.execute('SELECT sql_engine FROM dq_rules').fetchone()[0] == 'databricks'
    c.close()
    assert report_tables('local') == ['customers']
    assert report_tables('databricks', 'cloud') == ['`workspace`.`dq_app`.`products`']
    assert report_tables('databricks', 'other') == []


@pytest.mark.parametrize('sql', [
    'DELETE FROM workspace.dq_app.products',
    'SELECT * FROM products',
    'SELECT * FROM workspace.dq_app.products; DROP TABLE products',
    'SELECT * FROM {{SOURCE}}',
])
def test_native_sql_rejects_ambiguous_or_mutating_queries(sql):
    with pytest.raises(Exception):
        native_sql(sql)


def test_native_cte_preserves_join_dependencies():
    rendered, deps = native_sql('WITH p AS (SELECT * FROM workspace.dq_app.products) SELECT * FROM p')
    assert list(deps.values()) == [['workspace', 'dq_app', 'products']]
    assert 'WITH' in rendered


def test_native_edits_keep_published_snapshot_until_publish(cloud_profile):
    link_id = save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Country exists', SQL)
    link, old_payload = definition(link_id)
    c = get_connection()
    with c:
        c.execute('UPDATE dq_remote_links SET base_revision=? WHERE id=?', (revision(old_payload), link_id))
        c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)', (link_id, revision(old_payload), '1.0', canonical(old_payload)))
    c.close()
    save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Country exists', SQL,
               rule_id=link['rule_id'], active=False)
    updated, payload = definition(link_id)
    assert payload['local_version'] == '1.1' and payload['active'] is False
    assert updated['base_revision'] == revision(old_payload) != revision(payload)
    c = get_connection()
    assert c.execute('SELECT COUNT(*) FROM dq_rules_history').fetchone()[0] == 1
    assert c.execute('SELECT payload FROM dq_remote_versions').fetchone()[0] == canonical(old_payload)
    c.close()


class Remote:
    def __init__(self, cancel=None):
        self.sql = ''
        self.cancelled = False
        self.cancel_event = cancel
        self.description = [('id',), ('country_code',), ('dq_check',)]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self
    def execute_async(self, sql, parameters=None):
        self.sql = sql
        self.parameters = parameters
        if self.cancel_event: self.cancel_event.set()
    def is_query_pending(self): return False
    def get_async_execution_result(self): pass
    def fetchmany(self, count): return [(1, 'XX', 1)] * count
    def cancel(self): self.cancelled = True


def test_cloud_preview_limit_and_server_cancellation(cloud_profile):
    remote = Remote()
    result = preview_query('cloud', SQL, threading.Event(), connect=lambda source: remote)
    assert len(result.rows) == 500 and result.truncated
    assert remote.sql.endswith('LIMIT 501')
    cancel = threading.Event()
    remote = Remote(cancel)
    with pytest.raises(ValueError, match='cancelled'):
        execute(remote, 'SELECT 1', cancel)
    assert remote.cancelled


def test_schema_names_are_bound_parameters(cloud_profile):
    remote = Remote()
    remote.fetchmany = lambda _: [('products', 'price', 'decimal(10,2)')]
    schema = "unusual\\'schema"
    assert browse('cloud', 'workspace', schema, threading.Event(), connect=lambda _: remote) == {'products': [('price', 'decimal(10,2)')]}
    assert schema not in remote.sql and remote.parameters == [schema]


def test_cloud_run_import_and_environment_scoping(cloud_profile):
    from datetime import datetime, timezone
    link_id = save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Country exists', SQL)
    link, payload = definition(link_id)
    c = get_connection()
    with c:
        c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)', (link_id, revision(payload), '1.0', canonical(payload)))
        c.execute('UPDATE dq_remote_links SET base_revision=? WHERE id=?', (revision(payload), link_id))
    c.close()
    now = datetime.now(timezone.utc).isoformat()
    run = dict(run_id='daily-1', rule_key=payload['rule_key'], revision=revision(payload), payload=canonical(payload),
               started_at=now, completed_at=now, status='completed', source_version=2,
               reference_versions='{"table_1":3}', execution_error=None)
    results = [dict(run_id='daily-1', passed=1, failed=0, field_name='country_code')]
    assert import_run(link, run, results, [], 'Admin')
    assert not import_run(link, run, results, [], 'Admin')
    local_run = run_checks('customers', 'Admin')
    assert local_run in run_ids('local')
    assert local_run not in run_ids('databricks')
    assert len(run_ids('databricks', 'cloud')) == 1
    assert not run_ids('databricks', 'other')
    table = '`workspace`.`dq_app`.`products`'
    assert len(trend_for_table(table, 'databricks', 'cloud')) == 1
    assert not trend_for_table(table, 'local')
    assert synchronize('Admin', profile='other', detailed=True, connect=lambda _: pytest.fail('wrong profile')).targets == []


def test_unpublished_native_draft_does_not_connect_during_sync(cloud_profile):
    save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Country exists', SQL)
    report = synchronize('Admin', detailed=True, connect=lambda _: pytest.fail('draft must not query remote control tables'))
    assert not report.targets and not report.errors


def test_native_publication_validates_cloud_contract_first(cloud_profile, monkeypatch):
    from logic.databricks_workspace import publish_draft
    from logic import databricks_sync as sync
    link_id = save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Country exists', SQL)
    _, payload = definition(link_id)
    calls = []
    monkeypatch.setattr(sync, 'setup_remote', lambda *args: calls.append('setup'))
    monkeypatch.setattr(sync, 'compare', lambda *args: dict(local=payload, remote_revision=None))
    monkeypatch.setattr(sync, 'publish', lambda *args: calls.append(('publish', args[2])))
    publish_draft(link_id, 'Admin', threading.Event(), connect=lambda _: Remote())
    assert calls == ['setup', ('publish', revision(payload))]
    calls.clear()
    remote = Remote()
    remote.description = [('id',), ('country_code',)]
    with pytest.raises(ValueError, match='exactly id'):
        publish_draft(link_id, 'Admin', threading.Event(), connect=lambda _: remote)
    assert not calls
