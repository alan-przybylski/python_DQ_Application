import os
import tkinter as tk

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(os.environ.get('DQ_GUI_TESTS') != '1', reason='Requires desktop')]


@pytest.fixture(scope='module')
def gui_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.parametrize('language', ['PL','EN'])
def test_rule_file_buttons(sqlite_database, tmp_path, monkeypatch, language, gui_root):
    from config.i18n import set_language
    from database.connection import get_connection
    from logic.rules import save_rule
    from ui.data_quality import DataQualityWindow
    from tkinter import messagebox, filedialog
    set_language(language, persist=False)
    c = get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser')")
    save_rule('Name', 'required', 'customers', 'SELECT id,name,0 AS dq_check FROM customers', '')
    directory = tmp_path/'definitions'
    directory.mkdir()
    monkeypatch.setattr(filedialog, 'askdirectory', lambda **kw: str(directory))
    monkeypatch.setattr(messagebox, 'showinfo', lambda *a, **kw: None)
    monkeypatch.setattr(messagebox, 'showerror', lambda *a, **kw: pytest.fail(str(a)))
    root = gui_root
    window = tk.Toplevel(root)
    try:
        view = DataQualityWindow(window, 'Admin', 'superuser', root, tk.StringVar(root))
        view.export_rule_files()
        manifest = next(directory.glob('*.rule.toml'))
        manifest.write_text(manifest.read_text(encoding='utf-8').replace('severity = "medium"', 'severity = "high"'), encoding='utf-8')
        view.import_rule_files()
        assert c.execute('SELECT version,severity FROM dq_rules').fetchone() == ('1.1','high')
        assert view.tree.set(view.tree.get_children()[0], 'severity') == 'High'
    finally:
        c.close()
        window.destroy()
        set_language('EN', persist=False)
