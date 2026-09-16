"""Password policy and account administration with actor checks."""

import bcrypt
import sqlite3

from config.i18n import AppError, tr
from database.connection import get_connection

ROLES = ("superuser", "user")


def password_checks(password):
    return [
        ("At least 6 characters", len(password) >= 6),
        (
            "At least one uppercase letter",
            any(character.isupper() for character in password),
        ),
        ("At least one digit", any(character.isdigit() for character in password)),
        ("At most 72 UTF-8 bytes", len(password.encode("utf-8")) <= 72),
    ]


def validate_password(password):
    missing = [tr(label) for label, passed in password_checks(password) if not passed]
    if missing:
        raise AppError(
            "Password does not meet: {requirements}", requirements="; ".join(missing)
        )


def normalize_role(role):
    return "superuser" if role == "admin" else role


def require_superuser(connection, actor):
    record = connection.execute(
        "SELECT role,active FROM users WHERE username=?", (actor,)
    ).fetchone()
    if not record or not record[1] or normalize_role(record[0]) != "superuser":
        raise AppError("A superuser account is required.")


def save_user(
    username, password=None, role="user", active=True, actor=None, create=False
):
    username = username.strip()
    role = normalize_role(role)
    if not username:
        raise AppError("Username is required.")
    if role not in ROLES:
        raise AppError("Invalid role.")
    if create or password is not None:
        validate_password(password or "")
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            bootstrap = (
                create
                and actor is None
                and not connection.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            )
            if not bootstrap:
                require_superuser(connection, actor)
            elif role != "superuser":
                raise AppError("A superuser account is required.")
            existing = connection.execute(
                "SELECT id,role,active FROM users WHERE username=?", (username,)
            ).fetchone()
            if create and existing:
                raise AppError("Username already exists.")
            if not create and not existing:
                raise AppError("User not found.")
            if (
                existing
                and existing[2]
                and normalize_role(existing[1]) == "superuser"
                and (role != "superuser" or not active)
            ):
                others = connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role IN ('admin','superuser') AND active=1 AND id!=?",
                    (existing[0],),
                ).fetchone()[0]
                if not others:
                    raise AppError(
                        "The last active superuser cannot be deactivated or demoted."
                    )
            password_hash = (
                bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode("ascii")
                if password is not None
                else None
            )
            if create:
                connection.execute(
                    "INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,?)",
                    (username, password_hash, role, int(active)),
                )
            elif password_hash:
                connection.execute(
                    "UPDATE users SET password_hash=?,role=?,active=? WHERE id=?",
                    (password_hash, role, int(active), existing[0]),
                )
            else:
                connection.execute(
                    "UPDATE users SET role=?,active=? WHERE id=?",
                    (role, int(active), existing[0]),
                )
    except sqlite3.IntegrityError as error:
        raise AppError("Username already exists.") from error
    finally:
        connection.close()


def list_users(actor):
    connection = get_connection()
    try:
        require_superuser(connection, actor)
        return connection.execute(
            "SELECT username,role,active FROM users ORDER BY username"
        ).fetchall()
    finally:
        connection.close()
