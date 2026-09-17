import bcrypt
import pytest

from database.connection import get_connection
from logic.login_functions import login_user


@pytest.fixture
def account(sqlite_database):
    connection = get_connection()
    try:
        with connection:
            connection.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                ("admin", bcrypt.hashpw(b"Admin123", bcrypt.gensalt()).decode(), "superuser"),
            )
    finally:
        connection.close()


def test_exact_username_and_password_work(account):
    assert login_user("admin", "Admin123") == ("admin", "superuser", None)


@pytest.mark.parametrize("username", ["Admin", "ADMIN", "aDmIn", "ádmin", "admin ", " admin"])
def test_non_exact_username_rejected(account, username):
    result = login_user(username, "Admin123")
    assert result[0] is None and result[1] is None and result[2]


def test_password_still_case_sensitive(account):
    assert login_user("admin", "admin123")[0] is None
