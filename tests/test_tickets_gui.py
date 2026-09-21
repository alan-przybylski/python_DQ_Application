import os
import tkinter as tk
from tkinter import ttk
from pathlib import Path

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(os.environ.get('DQ_GUI_TESTS') != '1', reason='Requires desktop')]


@pytest.mark.parametrize('language', ['PL', 'EN'])
@pytest.mark.parametrize('screen_size', [(1920,1080), (1366,768)])
def test_ticket_windows_and_assignment(sqlite_database, monkeypatch, language, screen_size):
    from config.i18n import set_language, tr
    from database.connection import get_connection
    from logic.rules import save_rule
    from logic.dq_engine import run_checks
    from logic.tickets import list_tickets
    from ui.tickets_window import TicketsWindow
    from tkinter import messagebox
    set_language(language, persist=False)
    monkeypatch.setattr(tk.Misc, 'winfo_screenwidth', lambda self: screen_size[0])
    monkeypatch.setattr(tk.Misc, 'winfo_screenheight', lambda self: screen_size[1])
    monkeypatch.setattr(messagebox, 'showerror', lambda *a, **k: pytest.fail(str(a)))
    c = get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('Admin','unused','superuser'),('Anna','unused','user')")
        c.execute("INSERT INTO customers(name,email) VALUES('Anna',NULL),('Jan',NULL)")
    c.close()
    save_rule('Missing email addresses', 'required', 'customers', 'SELECT id,email,1 AS dq_check FROM customers', 'Email missing', severity='high')
    run_checks('customers', 'Admin')
    root = tk.Tk()
    root.withdraw()
    win = tk.Toplevel(root)
    view = TicketsWindow(win, 'Admin', 'superuser', root, tk.StringVar(root))
    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)
    def check(window):
        window.update()
        for widget in descendants(window):
            if isinstance(widget, (tk.Button, ttk.Combobox)) and widget.winfo_viewable():
                assert widget.winfo_rooty() + widget.winfo_height() <= window.winfo_rooty() + window.winfo_height()
                assert widget.winfo_rootx() + widget.winfo_width() <= window.winfo_rootx() + window.winfo_width()
    try:
        assert len(view.tree.get_children()) == 1
        check(win)
        details = view.show_details(1)
        check(details)
        combos = [w for w in descendants(details) if isinstance(w, ttk.Combobox)]
        combos[0].set('Anna')
        combos[1].set(tr('In progress'))
        comment = next(w for w in descendants(details) if isinstance(w, tk.Text) and str(w.cget('state')) == 'normal')
        comment.insert('1.0', 'Checking the source file.')
        if os.environ.get('DQ_CAPTURE_DIR') and screen_size == (1920,1080):
            from PIL import ImageGrab
            path = Path(os.environ['DQ_CAPTURE_DIR'])
            path.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab(window=details.winfo_id()).save(path / f'ticket-{language}.png')
        save = next(w for w in descendants(details) if isinstance(w, tk.Button) and w.cget('text') == tr('Save changes'))
        save.invoke()
        ticket = list_tickets()[0]
        assert ticket['assignee'] == 'Anna' and ticket['status'] == 'in_progress'
    finally:
        root.destroy()
        set_language('EN', persist=False)
