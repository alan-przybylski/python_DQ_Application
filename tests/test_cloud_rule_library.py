import os
import tkinter as tk

import pytest

from database.connection import get_connection
from integrations.databricks_contract import canonical, revision
from logic.cloud_rule_library import list_cloud_rules, list_library_rules
from logic.databricks_profiles import save_profile
from logic.databricks_sync import definition, save_mapping
from logic.databricks_workspace import save_draft
from logic.rules import save_rule


@pytest.fixture
def inventory(sqlite_database):
    c = get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
    save_profile('cloud', dict(hostname='example.cloud.databricks.com', http_path='/sql/1.0/warehouses/abc', catalog='workspace', schema='dq_app', table=''))
    ids = []
    for title in ['SKU uniqueness', 'EAN required', 'EAN length']:
        rid = save_rule(title, 'SQL', 'customers', 'SELECT id,name,0 AS dq_check FROM customers', 'Invalid')
        save_mapping(rid, 'Admin', 'cloud', 'workspace', 'dq_control', 'workspace', 'dq_app', 'products',
                     'SELECT product_id AS id,sku,0 AS dq_check FROM {{source}}')
        link_id = c.execute('SELECT id FROM dq_remote_links WHERE rule_id=?', (rid,)).fetchone()[0]
        _, payload = definition(link_id)
        with c:
            c.execute("UPDATE dq_rules SET execution_mode='databricks' WHERE id=?", (rid,))
            c.execute('UPDATE dq_remote_links SET base_revision=? WHERE id=?', (revision(payload), link_id))
            c.execute('INSERT INTO dq_remote_versions VALUES(?,?,?,?)', (link_id, revision(payload), '1.0', canonical(payload)))
        ids.append(rid)
    save_draft('Admin', 'cloud', ['workspace', 'dq_app', 'products'], 'Native rule',
               'SELECT product_id AS id,sku,0 AS dq_check FROM workspace.dq_app.products')
    save_rule('Local check', 'SQL', 'customers', 'SELECT id,name,0 AS dq_check FROM customers', 'Invalid')
    c.close()
    return ids


def test_cloud_inventory_includes_old_publications_and_new_drafts(inventory):
    rules = list_cloud_rules('cloud')
    assert len(rules) == 4
    assert [r['id'] for r in rules[:3]] == inventory
    for rule in rules[:3]:
        assert rule['publication_state'] == 'Published'
        assert rule['sql_engine'] == 'sqlite'
        assert '{{source}}' not in rule['display_sql']
        assert '`workspace`.`dq_app`.`products`' in rule['display_sql']
        assert 'customers' not in rule['display_sql']
    assert rules[-1]['publication_state'] == 'Draft'
    assert rules[-1]['sql_engine'] == 'databricks'
    assert list_cloud_rules('another-profile') == []


def test_legacy_display_uses_publication_not_modified_local_sql(inventory):
    c = get_connection()
    with c:
        c.execute("UPDATE dq_rules SET sql_query='SELECT changed_local_data',version='1.1',status='INACTIVE' WHERE id=?", (inventory[0],))
    c.close()
    rule = list_cloud_rules('cloud')[0]
    assert rule['display_version'] == '1.0'
    assert rule['display_active'] is True
    assert 'changed_local_data' not in rule['display_sql']


def test_single_library_environment_filters_without_duplicates(inventory):
    rules = list_library_rules()
    assert len(rules) == 5 and len({r['id'] for r in rules}) == 5
    assert len(list_library_rules('databricks')) == 4
    assert len(list_library_rules('databricks', 'cloud')) == 4
    local = list_library_rules('local')
    assert len(local) == 1 and local[0]['description'] == 'Local check'


@pytest.mark.gui
@pytest.mark.skipif(os.environ.get('DQ_GUI_TESTS') != '1', reason='Requires desktop')
def test_cloud_library_is_distinct_from_editor_and_opens_selected_publication(inventory, monkeypatch):
    from ui.environment_menu import EnvironmentMenu
    from ui.rule_library_window import RuleLibraryWindow
    from ui.databricks_workspace import DatabricksWorkspace
    import ui.databricks_workspace as editor_module
    errors = []
    monkeypatch.setattr(editor_module, 'error_box', lambda error, parent: errors.append(str(error)))
    root = tk.Tk()
    root.withdraw()
    menu = EnvironmentMenu(tk.Toplevel(root), 'Admin', 'superuser', root, tk.StringVar(root), environment='databricks')
    library = menu.rules()
    try:
        assert isinstance(library, RuleLibraryWindow)
        assert not hasattr(library, 'editor')
        assert len(library.tree.get_children()) == 5
        library.environment_choice.set('Local')
        library.refresh()
        assert len(library.tree.get_children()) == 1
        assert str(library.picker.cget('state')) == 'disabled'
        library.environment_choice.set('Databricks')
        library.refresh()
        assert len(library.tree.get_children()) == 4
        assert str(library.definition.cget('state')) == 'disabled'
        library.tree.selection_set(str(inventory[0]))
        library.show_definition()
        assert '`workspace`.`dq_app`.`products`' in library.definition.get('1.0', 'end-1c')
        editor = library.open_sql()
        assert isinstance(editor, DatabricksWorkspace)
        assert editor.selected_rule()['id'] == inventory[0]
        assert 'product_id AS id' in editor.editor.get('1.0', 'end-1c')
        editor.publish()
        assert errors  # A linked publication cannot be accidentally overwritten as a native draft.
        editor.close()
        root.update()
        assert library.root.state() == 'normal'
        empty = library.new_rule()
        assert empty.editor.get('1.0', 'end-1c') == ''
        empty.close()
        library.close()
        direct_editor = menu.editor()
        assert isinstance(direct_editor, DatabricksWorkspace)
        assert direct_editor.editor.get('1.0', 'end-1c') == ''
        direct_editor.close()
    finally:
        root.destroy()
