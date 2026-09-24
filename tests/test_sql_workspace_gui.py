import os
import time
import tkinter as tk

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(
    os.environ.get("DQ_GUI_TESTS") != "1", reason="Requires interactive desktop")]


@pytest.fixture(scope='module')
def workspace_root():
    root=tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.parametrize("language", ["PL", "EN"])
@pytest.mark.parametrize('screen_size',[(1920,1080),(1280,720)])
def test_preview_and_rule_handoff(sqlite_database, monkeypatch, language,screen_size,workspace_root):
    from config.i18n import set_language
    from ui.sql_workspace import SqlWorkspace
    from ui.data_quality import DataQualityWindow
    set_language(language, persist=False)
    monkeypatch.setattr(tk.Misc,'winfo_screenwidth',lambda self:screen_size[0])
    monkeypatch.setattr(tk.Misc,'winfo_screenheight',lambda self:screen_size[1])
    root = workspace_root
    window = tk.Toplevel(root)
    workspace = SqlWorkspace(window, "Admin", "superuser", root, tk.StringVar(root))
    try:
        workspace.table_query()
        deadline = time.monotonic() + 5
        while workspace.running and time.monotonic() < deadline:
            root.update()
            time.sleep(.02)
        assert not workspace.running
        assert len(workspace.results["columns"]) == 4
        workspace.editor.delete('1.0','end')
        workspace.editor.insert('1.0','SELECT id,name,0 AS dq_check FROM {{SOURCE}}')
        workspace.run()
        deadline=time.monotonic()+5
        while workspace.running and time.monotonic()<deadline:
            root.update()
            time.sleep(.02)
        assert not workspace.running
        assert len(workspace.results['columns']) == 3
        captured = {}
        monkeypatch.setattr(DataQualityWindow, "rule_form", lambda self, **kw: captured.update(kw))
        workspace.editor.delete("1.0", "end")
        sql = 'SELECT id,name,0 AS dq_check FROM customers'
        workspace.editor.insert("1.0", sql)
        workspace.create_rule()
        assert captured == {"initial_sql": sql, "initial_table": "customers"}
        for child in window.winfo_children():
            if isinstance(child, tk.Toplevel):
                child.destroy()
        root.update()
        for widget in (workspace.editor, workspace.results, workspace.run_button, workspace.schema):
            assert widget.winfo_width() > 100
            assert widget.winfo_rootx() + widget.winfo_width() <= window.winfo_rootx() + window.winfo_width()
        def check_buttons(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, tk.Button):
                    assert widget.winfo_ismapped()
                    assert widget.winfo_rooty() + widget.winfo_height() <= window.winfo_rooty() + window.winfo_height()
                check_buttons(widget)
        check_buttons(window)
        if os.environ.get("DQ_CAPTURE_DIR"):
            from pathlib import Path
            from PIL import ImageGrab
            path = Path(os.environ["DQ_CAPTURE_DIR"])
            path.mkdir(parents=True, exist_ok=True)
            window.lift()
            root.update()
            ImageGrab.grab(window=window.winfo_id()).save(path / f"sql-{language}.png")
    finally:
        workspace.go_back()
        root.withdraw()
        set_language("EN", persist=False)
