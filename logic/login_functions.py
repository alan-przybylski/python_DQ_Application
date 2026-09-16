import sqlite3
from database.connection import get_connection
import bcrypt

def create_user(username: str, password: str, role: str = "user"):
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('ascii')
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, active) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, True)
        )
        conn.commit()
    except sqlite3.Error as e:
        raise Exception(f"Błąd przy tworzeniu użytkownika: {e}")
    finally:
        cursor.close()
        conn.close()

def change_password(username: str, new_password: str):
    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('ascii')
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET password_hash=?, active=TRUE WHERE username=?",
            (password_hash, username)
        )
        if cursor.rowcount == 0:
            raise Exception(f"Użytkownik '{username}' nie istnieje lub jest nieaktywny")
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def deactivate_user(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET active=FALSE WHERE username=? AND active=TRUE",
            (username,)
        )
        if cursor.rowcount == 0:
            raise Exception(f"Użytkownik '{username}' nie istnieje lub jest już dezaktywowany")
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def login_user(username: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT password_hash, role, active FROM users WHERE username=?",
            (username,)
        )
        result = cursor.fetchone()
        if not result:
            return None, None, "Nie ma takiego użytkownika"
        password_hash, role, active = result
        if not active:
            return None, None, "Użytkownik nieaktywny"
        if bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            return username, role, None
        return None, None, "Niepoprawne hasło"
    finally:
        cursor.close()
        conn.close()

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("Select username,active from users")
        users = [row[0] for row in cursor.fetchall()]
        return users
    finally:
        cursor.close()
        conn.close()
