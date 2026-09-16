from pathlib import Path
import hashlib

import pytest

from config.paths import DATABASE_PATH
from database.connection import get_connection
from scripts.seed_demo import create_demo_database, DEMO_APPLICATION_ID, DEMO_PASSWORD


def test_demo_contains_synthetic_history_and_never_resets_it(tmp_path):
    path = create_demo_database(tmp_path / "demo.db")
    connection = get_connection(path)
    try:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == DEMO_APPLICATION_ID
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 12
        assert connection.execute("SELECT COUNT(*) FROM dq_results").fetchone()[0] == 9
        assert connection.execute("SELECT COUNT(*) FROM dq_field_results").fetchone()[0] == 108
        assert connection.execute("SELECT COUNT(*) FROM data_load_log").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM customers WHERE email NOT LIKE '%@example.test'").fetchone()[0] == 0
        assert connection.execute("SELECT SUM(failed_count) FROM dq_results WHERE timestamp LIKE '2026-09-03%'").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        import bcrypt
        password_hash = connection.execute("SELECT password_hash FROM users WHERE username='demo'").fetchone()[0]
        assert bcrypt.checkpw(DEMO_PASSWORD.encode(), password_hash.encode())
    finally:
        connection.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert create_demo_database(path) == path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_demo_refuses_private_database():
    with pytest.raises(ValueError):
        create_demo_database(DATABASE_PATH)


def test_demo_refuses_existing_unknown_file(tmp_path):
    from database.connection import initialize_database
    path = tmp_path / "unknown.db"
    initialize_database(path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        create_demo_database(path)
    assert path.read_bytes() == before
