"""Idempotent, additive migration; never invent links for legacy results."""

from datetime import datetime
from pathlib import Path


RUN_SCHEMA = """CREATE TABLE IF NOT EXISTS dq_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    username TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    completed_at TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    rules_requested INTEGER NOT NULL DEFAULT 0,
    rules_completed INTEGER NOT NULL DEFAULT 0,
    execution_errors TEXT NOT NULL DEFAULT '[]'
)"""


def upgrade(connection, destination):
    columns = {
        table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        for table in ("dq_results", "dq_field_results")
    }
    needs_upgrade = any("run_id" not in names for names in columns.values())
    if not needs_upgrade:
        with connection:
            connection.execute("UPDATE users SET role='superuser' WHERE role='admin'")
        return
    # Back up established databases once, before altering columns or account roles.
    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        from database.connection import get_connection

        destination = Path(destination)
        backup_dir = destination.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = (
            backup_dir
            / f"{destination.stem}_before_runs_{datetime.now():%Y%m%d_%H%M%S_%f}.db"
        )
        backup = get_connection(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(RUN_SCHEMA)
        for table, names in columns.items():
            if "run_id" not in names:
                connection.execute(
                    f'ALTER TABLE "{table}" ADD COLUMN run_id INTEGER REFERENCES dq_runs(id)'
                )
            connection.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{table}_run" ON "{table}"(run_id)'
            )
        connection.execute("UPDATE users SET role='superuser' WHERE role='admin'")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
