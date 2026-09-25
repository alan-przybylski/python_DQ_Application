"""Exercise real menu transitions without network access or production data."""
import os
import threading
import tkinter as tk

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(os.environ.get('DQ_GUI_TESTS') != '1', reason='Requires desktop')]


@pytest.fixture
def dashboard(sqlite_database, monkeypatch):
    from ui.dashboard_window import DashboardWindow
    from ui import databricks_sync_window
    from config import i18n
    monkeypatch.setattr(databricks_sync_window, 'startup_sync', lambda *args: threading.Event())
    monkeypatch.setattr(i18n, 'SETTINGS_PATH', sqlite_database.parent / 'settings.json')
    root = tk.Tk()
    view = DashboardWindow(root, 'Admin', 'superuser')
    root.update()
    yield view
    if root.winfo_exists():
        view.exit_program()
    i18n.set_language('EN', persist=False)


def test_main_menu_environment_navigation_and_report_filter(dashboard):
    assert set(dashboard.buttons) == {'Databricks', 'Local', 'Rule library', 'Quality report', 'DQ tickets', 'Manage users', 'Settings'}
    assert not hasattr(dashboard, 'environment')
    local = dashboard.open_environment('local')
    assert local.environment == 'local'
    assert set(local.buttons) == {'Browse tables and columns', 'SQL editor', 'Run checks', 'Quality report', 'Import / export data'}
    report = local.report()
    assert report.environment == 'local'
    assert not hasattr(report, 'environment_picker')
    report.go_back()
    dashboard.root.update()
    assert local.root.state() == 'normal' and dashboard.root.state() == 'withdrawn'
    local.close()
    dashboard.root.update()
    assert dashboard.root.state() == 'normal'
    shared = dashboard.open_quality_report()
    assert shared.environment is None
    shared.environment_picker.set('Databricks')
    shared.environment_picker.event_generate('<<ComboboxSelected>>')
    assert shared.environment == 'databricks' and shared.get_tables_to_dq_check() == []
    shared.environment_picker.set('Local / SQLite')
    shared.environment_picker.event_generate('<<ComboboxSelected>>')
    assert shared.get_tables_to_dq_check() == ['customers']
    shared.go_back()
    tickets = dashboard.open_tickets()
    tickets.environment_picker.set('Databricks')
    tickets.environment_picker.event_generate('<<ComboboxSelected>>')
    assert tickets.environment == 'databricks'
    assert 'environment' in tickets.tree['columns']
    tickets.go_back()


def test_settings_profile_language_and_cloud_menu(dashboard):
    from logic.databricks_profiles import load_profiles
    from ui.environment_menu import EnvironmentMenu
    from config.i18n import tr
    settings = dashboard.open_settings()
    settings.profile.set('test')
    values = dict(hostname='example.cloud.databricks.com', http_path='/sql/1.0/warehouses/abc', catalog='workspace', schema='dq_app', table='')
    for key, value in values.items(): settings.fields[key].set(value)
    settings.save()
    assert load_profiles()['selected'] == 'test'
    settings.fields['table'].set('unsaved_table')
    settings.language.set('PL')
    settings.apply_language()
    assert settings.fields['table'].get() == 'unsaved_table'
    settings.close()
    assert tr('Settings') in dashboard.buttons['Settings'].cget('text')
    cloud = dashboard.open_environment('databricks')
    assert cloud.profile.get() == 'test'
    assert 'Runs and schedules' in cloud.buttons
    assert 'Import CSV' not in cloud.buttons
    transfers = cloud.open_window(EnvironmentMenu, environment='databricks', section='Data transfers')
    assert set(transfers.buttons) == {'Send local table to Databricks', 'Create local snapshot from Databricks', 'Export cloud preview to CSV', 'Download all results'}
    transfers.main_menu()
    dashboard.root.update()
    assert dashboard.root.state() == 'normal'


def test_non_admin_has_no_user_management(dashboard):
    dashboard.role = 'user'
    dashboard.render()
    assert 'Manage users' not in dashboard.buttons
