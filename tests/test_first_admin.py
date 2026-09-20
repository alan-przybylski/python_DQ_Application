import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.accounts import needs_first_admin, save_user
from logic.login_functions import login_user


def test_first_account_and_existing_accounts_are_preserved(sqlite_database):
    assert needs_first_admin()
    save_user('Admin', 'ChosenSecret7', 'superuser', create=True)
    assert not needs_first_admin()
    assert login_user('Admin', 'ChosenSecret7') == ('Admin', 'superuser', None)
    with pytest.raises(AppError):
        save_user('Other', 'OtherSecret7', 'superuser', create=True)
    c = get_connection()
    try:
        assert c.execute('SELECT username,role FROM users').fetchall() == [('Admin', 'superuser')]
        with c:
            c.execute('UPDATE users SET active=0')
        assert not needs_first_admin()
    finally:
        c.close()


def test_invalid_password_does_not_create_account(sqlite_database):
    with pytest.raises(AppError):
        save_user('Admin', 'short', 'superuser', create=True)
    assert needs_first_admin()
