import os
import time
import tkinter as tk
import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(os.environ.get('DQ_GUI_TESTS') != '1', reason='Requires desktop')]


@pytest.mark.parametrize('language', ['PL', 'EN'])
def test_cloud_editor_browse_query_and_isolated_report(sqlite_database, monkeypatch, language):
    from config.i18n import set_language
    from logic.databricks_profiles import save_profile
    from logic.sql_workspace import Preview
    from ui.databricks_workspace import DatabricksWorkspace
    from ui.check_dq_panel import CheckDqPanel
    from logic import databricks_workspace as cloud
    set_language(language, persist=False)
    save_profile('cloud', dict(hostname='example.cloud.databricks.com', http_path='/sql/1.0/warehouses/abc', catalog='workspace', schema='dq_app', table=''))
    monkeypatch.setattr(cloud, 'browse', lambda *a: {'products': [('product_id', 'BIGINT'), ('country_code', 'STRING')]})
    queries = []
    def preview(profile, sql, cancel):
        queries.append((profile, sql))
        return Preview(['id', 'country_code', 'dq_check'], [(1, 'XX', 1)], False, .01)
    monkeypatch.setattr(cloud, 'preview_query', preview)
    root = tk.Tk()
    root.withdraw()
    window = tk.Toplevel(root)
    workspace = DatabricksWorkspace(window, 'Admin', 'superuser', root, tk.StringVar(root))
    def finish():
        deadline = time.monotonic() + 5
        while workspace.running and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        assert not workspace.running
    try:
        workspace.browse()
        finish()
        item = workspace.tables.get_children()[0]
        workspace.tables.selection_set(item)
        workspace.preview_table()
        finish()
        assert queries == [('cloud', 'SELECT * FROM `workspace`.`dq_app`.`products`')]
        assert len(workspace.results.get_children()) == 1
        report_root = tk.Toplevel(root)
        report = CheckDqPanel(report_root, 'Admin', 'superuser', root, tk.StringVar(root), environment='databricks', profile='cloud')
        assert report.get_tables_to_dq_check() == []
        report.go_back()
        root.update()
    finally:
        workspace.close()
        root.destroy()
        set_language('EN', persist=False)
