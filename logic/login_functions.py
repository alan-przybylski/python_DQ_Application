"""Public account functions; existing logins remain valid after policy changes."""

import bcrypt

from config.i18n import AppError, tr
from database.connection import get_connection
from logic.accounts import list_users, normalize_role, save_user


def create_user(username: str, password: str, role: str = "user", actor=None):
    return save_user(username, password, role, True, actor, create=True)


def change_password(username: str, new_password: str, actor=None):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT role FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            raise AppError("User not found.")
    finally:
        connection.close()
    return save_user(username, new_password, normalize_role(row[0]), True, actor)


def deactivate_user(username: str, actor=None):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT role FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            raise AppError("User not found.")
    finally:
        connection.close()
    return save_user(username, None, normalize_role(row[0]), False, actor)


def login_user(username: str, password: str):
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT password_hash,role,active FROM users WHERE username COLLATE BINARY=?", (username,)
        ).fetchone()
        if not row:
            return None, None, tr("User not found.")
        if not row[2]:
            return None, None, tr("Account is inactive.")
        try:
            valid = bcrypt.checkpw(password.encode(), row[0].encode())
        except ValueError:
            valid = False
        if valid:
            return username, normalize_role(row[1]), None
        return None, None, tr("Incorrect password.")
    finally:
        connection.close()


def get_all_users(actor=None):
    return [row[0] for row in list_users(actor)]
