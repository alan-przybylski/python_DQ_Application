import os
import tkinter as tk

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.skipif(
    os.environ.get('DQ_GUI_TESTS') != '1', reason='Requires desktop')]


@pytest.mark.parametrize('language', ['PL', 'EN'])
def test_setup_validation_and_login(sqlite_database, monkeypatch, language):
    from config.i18n import set_language
    from logic.accounts import needs_first_admin
    from ui.login_window import LoginWindow
    import ui.login_window as login
    import ui.dashboard_window as dashboard

    set_language(language, persist=False)
    root = tk.Tk()
    errors, opened = [], []
    monkeypatch.setattr(login, 'error_box', lambda error, parent: errors.append(str(error)))
    monkeypatch.setattr(dashboard, 'DashboardWindow', lambda root, user, role: opened.append((user, role)))
    try:
        view = LoginWindow(root)
        assert view.setup and view.username_entry.get() == 'Admin'
        view.password_entry.insert(0, 'ChosenSecret7')
        view.confirm_entry.insert(0, 'Different7')
        view.validate_login()
        assert errors and needs_first_admin()
        view.confirm_entry.delete(0, 'end')
        view.confirm_entry.insert(0, 'ChosenSecret7')
        root.update()
        assert view.confirm_entry.winfo_ismapped()
        view.validate_login()
        assert opened == [('Admin', 'superuser')]
        assert not needs_first_admin()
        reopened = LoginWindow(root)
        assert not reopened.setup
        assert not hasattr(reopened, 'confirm_entry')
    finally:
        root.destroy()
        set_language('EN', persist=False)
